from django import template

from apps.gestao.permissoes import eh_gestor as _eh_gestor

register = template.Library()


@register.filter
def eh_gestor(user):
    """Uso no template: {% if user|eh_gestor %} ... {% endif %}"""
    return _eh_gestor(user)


@register.filter
def mascara_cpf(cpf):
    """LGPD: exibe só o miolo do CPF -> ***.982.247-**"""
    d = "".join(c for c in (cpf or "") if c.isdigit())
    return f"***.{d[3:6]}.{d[6:9]}-**" if len(d) == 11 else "—"


@register.filter
def atributo(obj, caminho):
    """Lê 'campo' ou 'relacao.campo' de um objeto; booleanos viram Sim/Não."""
    valor = obj
    for parte in caminho.split("."):
        exibir = getattr(valor, f"get_{parte}_display", None)
        valor = exibir() if callable(exibir) else getattr(valor, parte, None)
        if valor is None:
            return "—"
    if isinstance(valor, bool):
        return "Sim" if valor else "Não"
    if hasattr(valor, "strftime"):
        return valor.strftime("%d/%m/%Y")
    return valor
