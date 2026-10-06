"""
SAG-Cidadão — regras de negócio da gestão e indicadores do dashboard
App: gestao/services.py

Os indicadores são calculados NO BANCO, com agregações do ORM
(Count, Avg, filter=Q, TruncDate). Cada bloco do dashboard é uma única
consulta SQL com GROUP BY, por maior que seja a tabela.
"""
from datetime import timedelta

from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import (
    Avg, Count, DurationField, ExpressionWrapper, F, Q,
)
from django.db.models.functions import TruncDate
from django.utils import timezone

from apps.atendimento.models import Bairro, Secretaria, Servidor, Solicitacao

from .permissoes import grupo_gestor

S = Solicitacao.Status
FINAIS = [S.CONCLUIDA.value, S.INDEFERIDA.value, S.CANCELADA.value]
EM_ANDAMENTO = [S.ABERTA.value, S.EM_ANALISE.value, S.EM_EXECUCAO.value]


# ---------------------------------------------------------------------------
# Servidores: usuário + perfil na mesma transação
# ---------------------------------------------------------------------------
@transaction.atomic
def salvar_servidor(dados, servidor=None):
    if servidor is None:
        usuario = User(username=dados["username"])
    else:
        usuario = servidor.usuario
        usuario.username = dados["username"]
    usuario.first_name = dados["first_name"]
    usuario.last_name = dados["last_name"]
    usuario.email = dados["email"]
    if dados.get("senha"):
        usuario.set_password(dados["senha"])  # grava só o hash
    usuario.save()

    if dados.get("gestor"):
        usuario.groups.add(grupo_gestor())
    else:
        usuario.groups.remove(grupo_gestor())

    if servidor is None:
        servidor = Servidor(usuario=usuario)
    servidor.matricula = dados["matricula"]
    servidor.secretaria = dados["secretaria"]
    servidor.save()
    return servidor


def alternar_ativo(usuario):
    """
    Desativar em vez de excluir: is_active=False impede o login, mas o
    usuário continua no histórico das solicitações que atendeu.
    """
    usuario.is_active = not usuario.is_active
    usuario.save(update_fields=["is_active"])
    return usuario.is_active


# ---------------------------------------------------------------------------
# Indicadores do dashboard
# ---------------------------------------------------------------------------
def _base(dias, secretaria):
    qs = Solicitacao.objects.all()
    if dias:
        qs = qs.filter(criado_em__gte=timezone.now() - timedelta(days=dias))
    if secretaria:
        qs = qs.filter(categoria__secretaria=secretaria)
    return qs


def indicadores(dias=30, secretaria=None):
    from django.db.models import DateTimeField

    agora = timezone.now()
    prazo = ExpressionWrapper(
        F("criado_em") + F("categoria__prazo_dias") * timedelta(days=1),
        output_field=DateTimeField(),
    )
    duracao = ExpressionWrapper(F("concluida_em") - F("criado_em"), output_field=DurationField())
    qs = _base(dias, secretaria).annotate(prazo_final=prazo, duracao=duracao)

    concluida = Q(status=S.CONCLUIDA.value)

    # 1) Números principais: UMA consulta com várias agregações condicionais
    #    COUNT(*) FILTER (WHERE ...) no PostgreSQL
    k = qs.aggregate(
        total=Count("id"),
        andamento=Count("id", filter=Q(status__in=EM_ANDAMENTO)),
        concluidas=Count("id", filter=concluida),
        concluidas_no_prazo=Count("id", filter=concluida & Q(concluida_em__lte=F("prazo_final"))),
        atrasadas=Count("id", filter=Q(status__in=EM_ANDAMENTO, prazo_final__lt=agora)),
        canceladas=Count("id", filter=Q(status__in=[S.INDEFERIDA.value, S.CANCELADA.value])),
        tempo_medio=Avg("duracao", filter=concluida),
    )
    k["pct_no_prazo"] = round(100 * k["concluidas_no_prazo"] / k["concluidas"]) if k["concluidas"] else None

    # 2) Por status (GROUP BY status)
    contagem = dict(qs.values_list("status").annotate(n=Count("id")))
    por_status = [{"rotulo": s.label, "codigo": s.value, "valor": contagem.get(s.value, 0)} for s in S]

    # 3) Desempenho por secretaria (GROUP BY secretaria)
    por_secretaria = list(
        qs.values(sigla=F("categoria__secretaria__sigla"))
        .annotate(
            total=Count("id"),
            andamento=Count("id", filter=Q(status__in=EM_ANDAMENTO)),
            concluidas=Count("id", filter=concluida),
            no_prazo=Count("id", filter=concluida & Q(concluida_em__lte=F("prazo_final"))),
            atrasadas=Count("id", filter=Q(status__in=EM_ANDAMENTO, prazo_final__lt=agora)),
            tempo_medio=Avg("duracao", filter=concluida),
        )
        .order_by("-total")
    )
    for linha in por_secretaria:
        linha["pct_no_prazo"] = round(100 * linha["no_prazo"] / linha["concluidas"]) if linha["concluidas"] else None

    # 4) Por zona da cidade (GROUP BY zona)
    contagem_zona = dict(qs.values_list("bairro__zona").annotate(n=Count("id")))
    por_zona = [{"rotulo": z.label, "valor": contagem_zona.get(z.value, 0)} for z in Bairro.Zona]

    # 5) Categorias mais pedidas (GROUP BY categoria ... LIMIT 5)
    top_categorias = list(
        qs.values(rotulo=F("categoria__nome"), sigla=F("categoria__secretaria__sigla"))
        .annotate(valor=Count("id")).order_by("-valor")[:5]
    )

    # 6) Evolução diária (GROUP BY data), preenchendo os dias sem registro
    janela = dias or 30
    inicio = (timezone.localtime(agora) - timedelta(days=janela - 1)).date()
    por_dia = dict(
        _base(janela, secretaria).annotate(dia=TruncDate("criado_em"))
        .values_list("dia").annotate(n=Count("id"))
    )
    serie_diaria = [{"dia": inicio + timedelta(days=i), "valor": por_dia.get(inicio + timedelta(days=i), 0)} for i in range(janela)]

    # 7) Fila crítica: em andamento e com prazo vencido, mais antigas primeiro
    vencidas = list(
        qs.filter(status__in=EM_ANDAMENTO, prazo_final__lt=agora)
        .select_related("categoria__secretaria", "bairro")
        .order_by("prazo_final")[:6]
    )
    for s in vencidas:
        s.dias_atraso = (agora - s.prazo_final).days

    return {
        "k": k,
        "por_status": por_status,
        "por_secretaria": por_secretaria,
        "por_zona": por_zona,
        "top_categorias": top_categorias,
        "serie_diaria": serie_diaria,
        "vencidas": vencidas,
    }


def secretarias_ativas():
    return Secretaria.objects.filter(ativa=True).order_by("sigla")
