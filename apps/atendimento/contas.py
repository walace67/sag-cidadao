"""
SAG-Cidadão — views de conta: cadastro, ativação, login, senha e dados pessoais
App: atendimento/contas.py

Segurança aplicada neste módulo:
    - Resposta idêntica no cadastro (contra enumeração de CPFs)
    - Confirmação por e-mail (conta inativa até o titular clicar no link)
    - Limite de tentativas por IP e bloqueio temporário por login
    - Tokens de uso único com prazo (ativação e redefinição de senha)
LGPD:
    - Página "Meus dados": acesso, correção e exportação pelo titular
"""
import json

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.core.serializers.json import DjangoJSONEncoder
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from django.views.decorators.http import require_http_methods

from . import seguranca, services
from .forms import CadastroCidadaoForm, LoginForm, MeusDadosForm

User = get_user_model()

# Limites (tentativas, janela em segundos)
LIMITE_CADASTRO = (5, 60 * 60)        # 5 cadastros por hora por IP
LIMITE_LOGIN_IP = (20, 15 * 60)       # 20 tentativas de login por 15 min por IP
LIMITE_LOGIN_CONTA = (5, 15 * 60)     # 5 senhas erradas -> bloqueio de 15 min
LIMITE_SENHA = (5, 60 * 60)           # 5 pedidos de redefinição por hora por IP


def _enviar(request, destinatarios, assunto, modelo, contexto):
    corpo = render_to_string(modelo, {**contexto, "site": request.build_absolute_uri("/").rstrip("/")})
    send_mail(assunto, corpo, settings.DEFAULT_FROM_EMAIL, destinatarios)


# ---------------------------------------------------------------------------
# Cadastro com confirmação por e-mail
# ---------------------------------------------------------------------------
@require_http_methods(["GET", "POST"])
@seguranca.limitar("cadastro", *LIMITE_CADASTRO)
def cadastro(request):
    if request.user.is_authenticated:
        return redirect("atendimento:inicio")

    form = CadastroCidadaoForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        tipo, destinatarios, cidadao = services.solicitar_cadastro(
            nome_completo=d["nome_completo"], cpf=d["cpf"], email=d["email"],
            telefone=d["telefone"], bairro=d["bairro"], senha=d["senha1"],
        )
        if tipo == "ativacao":
            u = cidadao.usuario
            link = request.build_absolute_uri(reverse("atendimento:ativar", kwargs={
                "uidb64": urlsafe_base64_encode(force_bytes(u.pk)),
                "token": default_token_generator.make_token(u),
            }))
            _enviar(request, destinatarios, "Confirme seu cadastro no SAG-Cidadão",
                    "atendimento/email/ativacao.txt", {"nome": u.first_name, "link": link})
        elif destinatarios:
            _enviar(request, destinatarios, "Tentativa de cadastro com seus dados no SAG-Cidadão",
                    "atendimento/email/aviso_cadastro.txt", {"login": request.build_absolute_uri(reverse("login")),
                                                            "senha": request.build_absolute_uri(reverse("password_reset"))})
        # Mesma tela nos dois casos: quem tenta descobrir CPFs não vê diferença
        return render(request, "atendimento/cadastro_enviado.html", {"email": d["email"]})

    return render(request, "atendimento/cadastro.html", {"form": form})


def ativar(request, uidb64, token):
    """
    O link traz o id do usuário (base64) e um token assinado com a SECRET_KEY.
    O token expira (PASSWORD_RESET_TIMEOUT) e vale uma vez só: ao entrar,
    o last_login muda e o token deixa de bater.
    """
    try:
        usuario = User.objects.select_related("cidadao").get(pk=urlsafe_base64_decode(uidb64).decode())
    except (User.DoesNotExist, ValueError, TypeError, OverflowError):
        usuario = None

    valido = (
        usuario is not None and hasattr(usuario, "cidadao") and usuario.cidadao.pendente
        and default_token_generator.check_token(usuario, token)
    )
    if not valido:
        seguranca.log.info("link de ativacao invalido ou expirado ip=%s", seguranca.ip_do_cliente(request))
        return render(request, "atendimento/ativacao_invalida.html", status=400)

    services.ativar_cadastro(usuario)
    login(request, usuario, backend="django.contrib.auth.backends.ModelBackend")
    messages.success(request, f"Cadastro confirmado. Bem-vindo(a), {usuario.first_name}!")
    return redirect("atendimento:minhas")


# ---------------------------------------------------------------------------
# Login com limite por IP e bloqueio temporário por conta
# ---------------------------------------------------------------------------
class LoginSeguro(auth_views.LoginView):
    authentication_form = LoginForm

    def _chave_conta(self):
        bruto = self.request.POST.get("username", "").strip().lower()
        digitos = "".join(c for c in bruto if c.isdigit())
        return f"login-falhas:{digitos if len(digitos) == 11 else bruto}"

    def post(self, request, *args, **kwargs):
        limite_ip, janela_ip = LIMITE_LOGIN_IP
        if seguranca.registrar_tentativa(f"limite:login:{seguranca.ip_do_cliente(request)}", janela_ip) > limite_ip:
            return seguranca.resposta_429(request, janela_ip, motivo="login-ip")
        # O bloqueio vale até para logins que não existem: assim o bloqueio
        # também não revela quais contas existem.
        if seguranca.contagem(self._chave_conta()) >= LIMITE_LOGIN_CONTA[0]:
            seguranca.log.warning("login bloqueado conta=%s ip=%s",
                                  seguranca.anonimizar(self._chave_conta()), seguranca.ip_do_cliente(request))
            form = self.get_form()
            form.errors.clear()
            form.add_error(None, "Muitas tentativas para este login. Aguarde 15 minutos ou redefina sua senha.")
            return self.render_to_response(self.get_context_data(form=form), status=429)
        return super().post(request, *args, **kwargs)

    def form_invalid(self, form):
        falhas = seguranca.registrar_tentativa(self._chave_conta(), LIMITE_LOGIN_CONTA[1])
        if falhas == LIMITE_LOGIN_CONTA[0]:
            seguranca.log.warning("conta bloqueada por 15 min apos %s senhas erradas conta=%s ip=%s", falhas,
                                  seguranca.anonimizar(self._chave_conta()), seguranca.ip_do_cliente(self.request))
        return super().form_invalid(form)

    def form_valid(self, form):
        seguranca.zerar(self._chave_conta())
        return super().form_valid(form)


# ---------------------------------------------------------------------------
# Redefinição de senha (o Django já responde igual exista ou não o e-mail)
# ---------------------------------------------------------------------------
@method_decorator(seguranca.limitar("senha", *LIMITE_SENHA), name="dispatch")
class RedefinirSenha(auth_views.PasswordResetView):
    template_name = "atendimento/senha/pedir.html"
    email_template_name = "atendimento/email/redefinir_senha.txt"
    subject_template_name = "atendimento/email/redefinir_senha_assunto.txt"
    success_url = reverse_lazy("password_reset_done")


# ---------------------------------------------------------------------------
# LGPD: direitos do titular (art. 18)
# ---------------------------------------------------------------------------
@login_required
@require_http_methods(["GET", "POST"])
def meus_dados(request):
    if not hasattr(request.user, "cidadao"):
        return redirect("atendimento:inicio")
    cidadao = request.user.cidadao
    form = MeusDadosForm(request.POST or None, instance=cidadao)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Dados atualizados.")
        return redirect("atendimento:meus_dados")
    return render(request, "atendimento/meus_dados.html", {
        "c": cidadao, "form": form, "total": cidadao.solicitacoes.count(),
    })


@login_required
def exportar_dados(request):
    """Cópia dos dados pessoais em formato estruturado (JSON)."""
    if not hasattr(request.user, "cidadao"):
        return redirect("atendimento:inicio")
    c = request.user.cidadao
    dados = {
        "gerado_em": timezone.now(),
        "titular": {
            "nome_completo": c.nome_completo, "cpf": c.cpf, "email": request.user.email,
            "telefone": c.telefone, "bairro": c.bairro.nome, "cadastro_em": request.user.date_joined,
            "ciencia_aviso_privacidade_em": c.termo_aceito_em, "email_confirmado_em": c.email_confirmado_em,
        },
        "solicitacoes": [
            {
                "protocolo": s.protocolo, "servico": s.categoria.nome, "bairro": s.bairro.nome,
                "endereco": s.endereco_referencia, "descricao": s.descricao, "status": s.get_status_display(),
                "aberta_em": s.criado_em, "concluida_em": s.concluida_em,
                "historico": [
                    {"data": h.registrado_em, "situacao": h.get_status_novo_display(), "observacao": h.observacao}
                    for h in s.historico.order_by("registrado_em")
                ],
            }
            for s in c.solicitacoes.select_related("categoria", "bairro").prefetch_related("historico")
        ],
    }
    resposta = HttpResponse(
        json.dumps(dados, cls=DjangoJSONEncoder, ensure_ascii=False, indent=2),
        content_type="application/json; charset=utf-8",
    )
    resposta["Content-Disposition"] = 'attachment; filename="meus-dados-sag-cidadao.json"'
    return resposta
