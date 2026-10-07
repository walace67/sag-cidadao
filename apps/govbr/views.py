"""
Telas do login gov.br:
    /contas/govbr/entrar/     manda para o gov.br
    /contas/govbr/retorno/    volta do gov.br (troca o code, valida o id_token)
    /contas/govbr/completar/  primeiro acesso: bairro, telefone e ciência do aviso
"""
import logging
import secrets
import time

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.db import transaction
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone

from apps.atendimento.models import Cidadao
from apps.atendimento.models import validar_cpf
from apps.auditoria.registro import A, registrar

from . import oidc
from .forms import CompletarCadastroForm

log = logging.getLogger("sag.govbr")
PEDIDO, DADOS = "govbr_pedido", "govbr_dados"
VALIDADE = 10 * 60  # o retorno precisa chegar em até 10 minutos


def _redirect_uri(request):
    return settings.GOVBR_REDIRECT_URI or request.build_absolute_uri(reverse("govbr:retorno"))


def entrar(request):
    if not oidc.habilitado():
        raise Http404
    pedido = oidc.novo_pedido()
    request.session[PEDIDO] = pedido
    return redirect(oidc.url_de_autorizacao(pedido, _redirect_uri(request)))


def _falha(request, motivo):
    log.warning("login gov.br recusado: %s", motivo)
    messages.error(request, "Não foi possível concluir a entrada com gov.br. Tente de novo.")
    return redirect("login")


def _entrar_como(request, usuario):
    login(request, usuario, backend="django.contrib.auth.backends.ModelBackend")
    # O gov.br já é uma autenticação forte: não pede a segunda etapa do SAG
    request.session["2fa_ok"] = True
    return redirect("atendimento:inicio")


def retorno(request):
    pedido = request.session.pop(PEDIDO, None)
    if request.GET.get("error"):
        return _falha(request, f"gov.br respondeu {request.GET.get('error')}")
    if (not pedido or time.time() - pedido["criado"] > VALIDADE
            or not secrets.compare_digest(request.GET.get("state", ""), pedido["state"])):
        return _falha(request, "state ausente, expirado ou diferente")
    try:
        tokens = oidc.trocar_code(request.GET.get("code", ""), pedido["verifier"], _redirect_uri(request))
        claims = oidc.validar_id_token(tokens.get("id_token", ""), pedido["nonce"])
    except oidc.ErroGovbr as erro:
        return _falha(request, str(erro))

    cpf = "".join(c for c in str(claims["sub"]) if c.isdigit())
    try:
        validar_cpf(cpf)
    except Exception:
        return _falha(request, "sub não é um CPF válido")

    cidadao = Cidadao.objects.select_related("usuario").filter(cpf=cpf).first()
    if cidadao and not cidadao.pendente:
        if not cidadao.usuario.is_active:
            messages.error(request, "Seu acesso está bloqueado. Procure o atendimento da prefeitura.")
            return redirect("login")
        return _entrar_como(request, cidadao.usuario)

    # Primeiro acesso: guarda só o necessário e pede o que falta
    request.session[DADOS] = {
        "cpf": cpf, "nome": claims.get("name", "")[:150], "email": claims.get("email", ""),
        "email_verificado": bool(claims.get("email_verified")), "criado": time.time(),
    }
    return redirect("govbr:completar")


def completar(request):
    dados = request.session.get(DADOS)
    if not dados or time.time() - dados["criado"] > VALIDADE:
        request.session.pop(DADOS, None)
        return redirect("login")
    form = CompletarCadastroForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        from apps.atendimento.services import _criar_cidadao

        with transaction.atomic():
            # Um autocadastro pendente com este CPF é descartado: o gov.br
            # acabou de provar quem é o dono verdadeiro.
            pendente = Cidadao.objects.select_related("usuario").filter(cpf=dados["cpf"]).first()
            if pendente and pendente.pendente:
                pendente.usuario.delete()
            cidadao = _criar_cidadao(
                nome_completo=dados["nome"] or "Cidadão", cpf=dados["cpf"], email=dados["email"],
                telefone=form.cleaned_data["telefone"], bairro=form.cleaned_data["bairro"],
                senha=None, ativo=True,  # sem senha local: entra sempre pelo gov.br
            )
            if not dados["email_verificado"]:
                cidadao.email_confirmado_em = None
                cidadao.save(update_fields=["email_confirmado_em"])
        request.session.pop(DADOS, None)
        registrar(A.CRIAR, request=request, usuario=cidadao.usuario, objeto=cidadao.usuario,
                  detalhes={"origem": "conta gov.br", "e-mail verificado pelo gov.br": "Sim" if dados["email_verificado"] else "Não"})
        messages.success(request, f"Bem-vindo(a), {cidadao.usuario.first_name}! Sua conta foi criada com os dados do gov.br.")
        return _entrar_como(request, cidadao.usuario)
    return render(request, "govbr/completar.html", {"form": form, "dados": dados})
