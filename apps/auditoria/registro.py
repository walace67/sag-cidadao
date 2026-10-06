"""
Função única para gravar na trilha de auditoria:

    from apps.auditoria.registro import registrar, A
    registrar(A.DESATIVAR, request=request, objeto=servidor.usuario)

Nunca grava senha nem CPF completo (LGPD: minimização também no log).
"""
import ipaddress
import logging

from .models import RegistroAuditoria

A = RegistroAuditoria.Acao
log = logging.getLogger("sag.auditoria")

CAMPOS_SECRETOS = {"senha", "password", "password1", "password2", "new_password1", "new_password2", "segredo"}


def nome_seguro(usuario):
    """Identificação legível sem expor o CPF (o login dos cidadãos é o CPF)."""
    if usuario is None or not getattr(usuario, "pk", None):
        return ""
    if hasattr(usuario, "cidadao"):
        return f"{usuario.get_full_name() or 'Cidadão'} (cidadão nº {usuario.pk})"
    return usuario.get_full_name() or usuario.get_username()


def _texto(valor):
    if valor is None:
        return ""
    if isinstance(valor, bool):
        return "Sim" if valor else "Não"
    if hasattr(valor, "all") and callable(valor.all):  # ManyToMany
        return ", ".join(str(v) for v in valor.all())
    return str(valor)


def diferencas(form, iniciais=None):
    """
    {campo: [antes, depois]} só dos campos alterados, a partir de um Form
    já validado. Campos de senha aparecem como "alterada", sem o valor.
    """
    iniciais = iniciais if iniciais is not None else form.initial
    mudou = {}
    for campo in form.changed_data:
        if campo in CAMPOS_SECRETOS:
            if form.cleaned_data.get(campo):
                mudou[campo] = ["", "alterada"]
            continue
        rotulo = str(form.fields[campo].label or campo)
        antes = iniciais.get(campo)
        campo_form = form.fields[campo]
        if antes is not None and hasattr(campo_form, "queryset") and not hasattr(antes, "pk"):
            antes = campo_form.queryset.model.objects.filter(pk=antes).first() or antes
        mudou[rotulo] = [_texto(antes), _texto(form.cleaned_data.get(campo))]
    return mudou


def _ip(request):
    from apps.atendimento.seguranca import ip_do_cliente

    if request is None:
        return None
    try:
        return str(ipaddress.ip_address(ip_do_cliente(request)))
    except ValueError:  # requisição sem IP (ex.: login feito pelo shell ou em testes)
        return None


def registrar(acao, *, request=None, usuario=None, objeto=None, objeto_nome=None, detalhes=None):
    if objeto_nome is None and objeto is not None:
        objeto_nome = nome_seguro(objeto) if hasattr(objeto, "get_username") else str(objeto)
    if usuario is None and request is not None and getattr(request, "user", None) and request.user.is_authenticated:
        usuario = request.user
    registro = RegistroAuditoria.objects.create(
        usuario=usuario if getattr(usuario, "pk", None) else None,
        usuario_nome=nome_seguro(usuario),
        acao=acao,
        objeto_tipo=str(objeto._meta.verbose_name) if objeto is not None else "",
        objeto_id=str(objeto.pk) if objeto is not None and objeto.pk is not None else "",
        objeto_nome=(objeto_nome or "")[:200],
        detalhes=detalhes or {},
        ip=_ip(request),
    )
    log.info("auditoria %s usuario=%s objeto=%s:%s", acao, registro.usuario_id, registro.objeto_tipo, registro.objeto_id)
    return registro
