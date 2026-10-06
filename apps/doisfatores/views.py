"""
Telas da verificação em duas etapas:
    /contas/2fa/verificar/      segunda etapa do login
    /contas/2fa/                situação da conta (ativa, códigos restantes)
    /contas/2fa/configurar/     QR code + confirmação + códigos de recuperação
    /contas/2fa/codigos/        gerar novos códigos de recuperação
    /contas/2fa/desativar/      desligar (só para quem não é obrigado)
"""
import time

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from apps.atendimento import seguranca
from apps.auditoria.registro import A, registrar

from . import servicos
from .forms import CodigoForm, VerificacaoForm

User = get_user_model()
PENDENTE = "2fa_pendente"
VALIDADE_PENDENTE = 5 * 60        # 5 minutos entre a senha e o código
LIMITE_CODIGO = (5, 15 * 60)       # 5 códigos errados -> volta para a senha


def iniciar_segunda_etapa(request, usuario, destino):
    """Chamado pelo login depois da senha correta: ainda NÃO autentica."""
    request.session[PENDENTE] = {
        "uid": usuario.pk, "backend": usuario.backend,
        "expira": time.time() + VALIDADE_PENDENTE, "destino": destino,
    }
    return redirect("doisfatores:verificar")


def verificar(request):
    pendente = request.session.get(PENDENTE)
    if not pendente or pendente["expira"] < time.time():
        request.session.pop(PENDENTE, None)
        messages.error(request, "O tempo para informar o código acabou. Entre novamente.")
        return redirect("login")
    usuario = User.objects.filter(pk=pendente["uid"], is_active=True).first()
    if usuario is None:
        request.session.pop(PENDENTE, None)
        return redirect("login")

    form = VerificacaoForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        codigo = form.cleaned_data["codigo"]
        dispositivo = servicos.dispositivo_ativo(usuario)
        por_recuperacao = False
        ok = servicos.verificar_totp(dispositivo, codigo)
        if not ok and servicos.usar_codigo_recuperacao(usuario, codigo):
            ok = por_recuperacao = True
        if ok:
            request.session.pop(PENDENTE, None)
            seguranca.zerar(f"2fa-falhas:{usuario.pk}")
            login(request, usuario, backend=pendente["backend"])
            request.session["2fa_ok"] = True
            if por_recuperacao:
                restam = servicos.codigos_restantes(usuario)
                registrar(A.DOIS_FATORES, request=request, objeto=usuario,
                          detalhes={"evento": "entrada com código de recuperação", "códigos restantes": restam})
                messages.warning(request, f"Você usou um código de recuperação. Restam {restam}. "
                                          "Se perdeu o celular, configure o aplicativo de novo.")
            destino = pendente.get("destino") or ""
            if not url_has_allowed_host_and_scheme(destino, {request.get_host()}, require_https=request.is_secure()):
                destino = settings.LOGIN_REDIRECT_URL
            return redirect(destino)

        falhas = seguranca.registrar_tentativa(f"2fa-falhas:{usuario.pk}", LIMITE_CODIGO[1])
        registrar(A.DOIS_FATORES, request=request, usuario=usuario, objeto=usuario,
                  detalhes={"evento": "código recusado", "tentativa": falhas})
        if falhas >= LIMITE_CODIGO[0]:
            request.session.pop(PENDENTE, None)
            messages.error(request, "Muitos códigos errados. Entre novamente com a senha.")
            return redirect("login")
        form.add_error("codigo", "Código inválido ou já utilizado. Confira o relógio do celular e tente o próximo código.")
    return render(request, "doisfatores/verificar.html", {"form": form})


@login_required
def situacao(request):
    dispositivo = servicos.dispositivo_ativo(request.user)
    return render(request, "doisfatores/situacao.html", {
        "dispositivo": dispositivo,
        "restantes": servicos.codigos_restantes(request.user) if dispositivo else 0,
        "obrigatorio": servicos.precisa_2fa(request.user),
        "form": CodigoForm(),
    })


@login_required
def configurar(request):
    usuario = request.user
    trocando = request.session.get("2fa_trocar", False)
    if servicos.dispositivo_ativo(usuario) and not trocando:
        return redirect("doisfatores:situacao")

    if request.method == "POST":
        from .models import DispositivoTOTP

        dispositivo = DispositivoTOTP.objects.filter(usuario=usuario, confirmado_em__isnull=True).order_by("-pk").first()
        form = CodigoForm(request.POST)
        if dispositivo and form.is_valid():
            codigos = servicos.confirmar(dispositivo, form.cleaned_data["codigo"])
            if codigos:
                request.session["2fa_ok"] = True
                request.session["2fa_exige"] = True
                request.session["2fa_configurar"] = False
                request.session.pop("2fa_trocar", None)
                registrar(A.DOIS_FATORES, request=request, objeto=usuario,
                          detalhes={"evento": "aplicativo trocado" if trocando else "verificação ativada"})
                return render(request, "doisfatores/codigos.html", {"codigos": codigos, "novo": True})
            form.add_error("codigo", "Código não confere. Confira se escaneou o QR code certo e se o relógio do celular está correto.")
        if dispositivo is None:
            return redirect("doisfatores:configurar")
    else:
        dispositivo, _ = servicos.iniciar_configuracao(usuario)
        form = CodigoForm()
    return render(request, "doisfatores/configurar.html", {
        "form": form, "qr": servicos.qr_svg(dispositivo), "segredo": servicos.segredo_formatado(dispositivo),
        "obrigatorio": servicos.precisa_2fa(usuario), "trocando": trocando,
    })


def _confere_codigo_atual(request):
    form = CodigoForm(request.POST)
    return form.is_valid() and servicos.verificar_totp(servicos.dispositivo_ativo(request.user), form.cleaned_data["codigo"])


@login_required
@require_POST
def trocar(request):
    """Trocar de celular: exige o código do aplicativo atual."""
    if not _confere_codigo_atual(request):
        messages.error(request, "Código inválido. Para trocar de aparelho, informe um código do aplicativo atual.")
        return redirect("doisfatores:situacao")
    request.session["2fa_trocar"] = True
    return redirect("doisfatores:configurar")


@login_required
@require_POST
def novos_codigos(request):
    if not _confere_codigo_atual(request):
        messages.error(request, "Código inválido. Os códigos antigos continuam valendo.")
        return redirect("doisfatores:situacao")
    codigos = servicos.gerar_codigos_recuperacao(request.user)
    registrar(A.DOIS_FATORES, request=request, objeto=request.user, detalhes={"evento": "novos códigos de recuperação"})
    return render(request, "doisfatores/codigos.html", {"codigos": codigos, "novo": False})


@login_required
@require_POST
def desativar(request):
    if servicos.precisa_2fa(request.user):
        messages.error(request, "Para a equipe da prefeitura, a verificação em duas etapas é obrigatória.")
        return redirect("doisfatores:situacao")
    if not _confere_codigo_atual(request):
        messages.error(request, "Código inválido. A verificação continua ativa.")
        return redirect("doisfatores:situacao")
    servicos.remover(request.user)
    request.session["2fa_exige"] = False
    registrar(A.DOIS_FATORES, request=request, objeto=request.user, detalhes={"evento": "verificação desativada pelo titular"})
    messages.success(request, "Verificação em duas etapas desativada.")
    return redirect("doisfatores:situacao")
