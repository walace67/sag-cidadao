"""
Consulta da trilha de auditoria (somente leitura, perfil Gestor).
Não existe tela, rota nem botão para alterar ou apagar registros.
"""
from datetime import timedelta

from django.core.paginator import Paginator
from django.shortcuts import render
from django.utils import timezone

from apps.gestao.cadastros import CADASTROS
from apps.gestao.permissoes import gestor_required

from .models import RegistroAuditoria

PERIODOS = [(1, "24 horas"), (7, "7 dias"), (30, "30 dias"), (0, "Tudo")]


def _descrever(valor):
    """[antes, depois] vira "antes → depois"; o resto, texto simples."""
    if isinstance(valor, list) and len(valor) == 2:
        return f"{valor[0] or '(vazio)'} → {valor[1] or '(vazio)'}"
    return str(valor)


@gestor_required
def lista(request):
    qs = RegistroAuditoria.objects.all()
    acao = request.GET.get("acao", "")
    if acao in RegistroAuditoria.Acao.values:
        qs = qs.filter(acao=acao)
    quem = request.GET.get("quem", "").strip()
    if quem:
        qs = qs.filter(usuario_nome__icontains=quem)
    try:
        dias = int(request.GET.get("dias", 7))
    except ValueError:
        dias = 7
    if dias:
        qs = qs.filter(registrado_em__gte=timezone.now() - timedelta(days=dias))
    pagina = Paginator(qs, 50).get_page(request.GET.get("page"))
    for r in pagina:
        r.linhas = [(chave, _descrever(valor)) for chave, valor in (r.detalhes or {}).items()]
    return render(request, "auditoria/lista.html", {
        "pagina": pagina, "acoes": RegistroAuditoria.Acao.choices, "acao": acao, "quem": quem,
        "dias": dias, "periodos": PERIODOS, "cadastros": CADASTROS,
    })
