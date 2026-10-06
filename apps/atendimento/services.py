"""
SAG-Cidadão — camada de serviço (regras de negócio)
App: atendimento/services.py

Por que este arquivo existe?
    A view cuida do HTTP (ler o pedido, devolver a página). A regra de
    negócio ("quem pode mudar de qual status para qual", "toda mudança gera
    histórico") fica aqui. Assim a mesma regra vale para a tela, para o
    admin, para uma API futura e para os testes automatizados.

Conceitos de prova neste arquivo:
    - Transação e propriedades ACID (transaction.atomic)
    - Controle de concorrência com bloqueio pessimista (select_for_update)
    - Máquina de estados (transições permitidas)
    - ORM x SQL: filter, Q, select_related, annotate, Count
"""
from datetime import timedelta

from django.db import transaction
from django.db.models import Count, Max, Q
from django.utils import timezone

from . import tarefas
from .models import HistoricoSolicitacao, Solicitacao

Status = Solicitacao.Status


class TransicaoInvalida(Exception):
    """Mudança de status que a regra de negócio não permite."""


# ---------------------------------------------------------------------------
# Máquina de estados: de cada status, para quais ele pode ir.
# CON e IND são estados finais (conjunto vazio).
# Usamos .value (o código gravado no banco, ex.: "ABE") como chave, porque é
# isso que vem do banco e do formulário.
# ---------------------------------------------------------------------------
TRANSICOES = {
    Status.ABERTA.value: {Status.EM_ANALISE.value, Status.INDEFERIDA.value},
    Status.EM_ANALISE.value: {Status.EM_EXECUCAO.value, Status.INDEFERIDA.value},
    Status.EM_EXECUCAO.value: {Status.CONCLUIDA.value},
    Status.CONCLUIDA.value: set(),
    Status.INDEFERIDA.value: set(),
    Status.CANCELADA.value: set(),
}
# Repare: CAN não aparece como destino de nenhum status acima. Assim o
# servidor nunca vê "Cancelada" no formulário dele. O cancelamento tem uma
# regra própria, com outro ator (o cidadão), na função cancelar_pelo_cidadao.


def proximos_status(status_atual):
    """Lista de (código, rótulo) dos status permitidos a partir do atual."""
    permitidos = TRANSICOES.get(str(status_atual), set())
    return [(s.value, s.label) for s in Status if s.value in permitidos]


# ---------------------------------------------------------------------------
# Escrita: autocadastro do cidadão (RF01)
# ---------------------------------------------------------------------------
def _criar_cidadao(*, nome_completo, cpf, email, telefone, bairro, senha, ativo):
    """Cria o usuário de login e o perfil de cidadão (dentro de uma transação)."""
    from django.contrib.auth.models import User
    from .models import Cidadao

    partes = nome_completo.split(maxsplit=1)
    usuario = User.objects.create_user(
        username=cpf,  # CPF como login, como no gov.br; nunca exibido em telas públicas
        email=email,
        password=senha,  # create_user grava só o hash (PBKDF2), nunca a senha
        first_name=partes[0][:150],
        last_name=(partes[1] if len(partes) > 1 else "")[:150],
        is_active=ativo,
    )
    agora = timezone.now()
    return Cidadao.objects.create(
        usuario=usuario, cpf=cpf, nome_completo=nome_completo, telefone=telefone,
        bairro=bairro, termo_aceito_em=agora, email_confirmado_em=agora if ativo else None,
    )


@transaction.atomic
def solicitar_cadastro(*, nome_completo, cpf, email, telefone, bairro, senha):
    """
    Autocadastro (RF01) resistente a enumeração.

    Quem chama recebe SEMPRE a mesma resposta ("enviamos um e-mail"). O que
    muda é para quem vai o e-mail e o que ele diz:

    - CPF e e-mail livres: cria a conta INATIVA e envia o link de ativação
      para o e-mail informado. Só quem tem acesso a esse e-mail ativa.
    - CPF (ou e-mail) já usado por uma conta confirmada: NÃO cria nada e
      avisa o e-mail JÁ CADASTRADO. O atacante não vê diferença; o dono
      real fica sabendo da tentativa.
    - Cadastro anterior ainda PENDENTE (nunca confirmado): é substituído.
      Assim ninguém "sequestra" um CPF alheio deixando um cadastro pendente.

    Devolve (tipo, destinatarios, cidadao) para a view enviar os e-mails.
    """
    from django.contrib.auth.models import User
    from .models import Cidadao

    existente = Cidadao.objects.select_related("usuario").filter(cpf=cpf).first()
    if existente and existente.pendente:
        existente.usuario.delete()  # CASCADE apaga o perfil pendente
        existente = None

    mesmo_email = [
        u for u in User.objects.filter(email__iexact=email)
        if not (hasattr(u, "cidadao") and u.cidadao.pendente)
    ]
    for u in User.objects.filter(email__iexact=email, is_active=False, last_login__isnull=True):
        if hasattr(u, "cidadao") and u.cidadao.pendente:
            u.delete()

    if existente or mesmo_email:
        avisar = {existente.usuario.email} if existente else set()
        avisar |= {u.email for u in mesmo_email}
        return "aviso", sorted(e for e in avisar if e), None

    cidadao = _criar_cidadao(
        nome_completo=nome_completo, cpf=cpf, email=email, telefone=telefone,
        bairro=bairro, senha=senha, ativo=False,
    )
    return "ativacao", [email], cidadao


def ativar_cadastro(usuario):
    """Confirma o e-mail e libera o login."""
    usuario.is_active = True
    usuario.save(update_fields=["is_active"])
    usuario.cidadao.email_confirmado_em = timezone.now()
    usuario.cidadao.save(update_fields=["email_confirmado_em"])
    return usuario


def apagar_cadastros_pendentes(horas=24):
    """
    LGPD (necessidade e prazo de retenção): cadastro não confirmado não
    tem finalidade; os dados são apagados após o prazo do link.
    """
    from django.contrib.auth.models import User

    limite = timezone.now() - timedelta(hours=horas)
    qs = User.objects.filter(
        is_active=False, last_login__isnull=True, date_joined__lt=limite,
        cidadao__email_confirmado_em__isnull=True, cidadao__termo_aceito_em__isnull=False,
    )
    total = qs.count()
    qs.delete()
    return total


# ---------------------------------------------------------------------------
# Escrita: abrir solicitação
# ---------------------------------------------------------------------------
def anexar_fotos(solicitacao, fotos, usuario, etapa):
    """Grava as fotos já tratadas (imagens.processar_foto) ligadas à solicitação."""
    from .models import FotoSolicitacao

    for conteudo in fotos:
        foto = FotoSolicitacao(solicitacao=solicitacao, etapa=etapa, enviada_por=usuario, tamanho=conteudo.size)
        foto.arquivo.save("foto.jpg", conteudo, save=True)


@transaction.atomic
def abrir_solicitacao(*, cidadao, categoria, bairro, descricao, endereco_referencia,
                      latitude=None, longitude=None, fotos=()):
    """
    Cria a solicitação e o primeiro registro de histórico.

    @transaction.atomic = BEGIN ... COMMIT em volta da função inteira.
    Se a criação do histórico falhar, a solicitação também é desfeita
    (ROLLBACK). Isso é a ATOMICIDADE: tudo ou nada.
    """
    solicitacao = Solicitacao.objects.create(
        cidadao=cidadao,
        categoria=categoria,
        bairro=bairro,
        descricao=descricao,
        endereco_referencia=endereco_referencia,
        latitude=latitude,
        longitude=longitude,
    )
    anexar_fotos(solicitacao, fotos, cidadao.usuario, "PRO")
    HistoricoSolicitacao.objects.create(
        solicitacao=solicitacao,
        usuario=cidadao.usuario,
        status_anterior=Status.ABERTA,
        status_novo=Status.ABERTA,
        observacao="Solicitação aberta pelo cidadão.",
    )
    # Só depois do COMMIT: se algo falhar e houver ROLLBACK, nenhum e-mail sai
    transaction.on_commit(lambda: tarefas.avisar_abertura.enqueue(solicitacao.pk))
    return solicitacao


# ---------------------------------------------------------------------------
# Escrita: alterar status
# ---------------------------------------------------------------------------
def alterar_status(*, solicitacao_id, novo_status, usuario, observacao="", responsavel=None, fotos=()):
    """
    Muda o status e grava o histórico numa ÚNICA transação.

    select_for_update() gera "SELECT ... FOR UPDATE": a linha fica bloqueada
    até o COMMIT. Se dois servidores clicarem ao mesmo tempo, o segundo
    espera o primeiro terminar e então enxerga o status já atualizado.
    Sem isso, os dois leriam "ABE" e ambos gravariam a transição
    (anomalia conhecida como "atualização perdida" / lost update).
    Obs.: no SQLite o bloqueio é do banco inteiro; o comando faz efeito
    real no PostgreSQL, Oracle e MySQL.
    """
    with transaction.atomic():
        solicitacao = (
            Solicitacao.objects.select_for_update().get(pk=solicitacao_id)
        )
        anterior = str(solicitacao.status)
        novo_status = str(novo_status)

        if novo_status not in TRANSICOES.get(anterior, set()):
            raise TransicaoInvalida(
                f"Não é permitido mudar de '{Status(anterior).label}' "
                f"para '{Status(novo_status).label}'."
            )

        solicitacao.status = novo_status
        # Mantém coerência com o CHECK ck_solic_conclusao_coerente do banco
        solicitacao.concluida_em = timezone.now() if novo_status == Status.CONCLUIDA else None
        if responsavel is not None and solicitacao.responsavel_id is None:
            solicitacao.responsavel = responsavel
        solicitacao.save()

        anexar_fotos(solicitacao, fotos, usuario, "SER")
        historico = HistoricoSolicitacao.objects.create(
            solicitacao=solicitacao,
            usuario=usuario,
            status_anterior=anterior,
            status_novo=novo_status,
            observacao=observacao,
        )
        # Aviso ao cidadão em segundo plano, só depois do COMMIT
        transaction.on_commit(lambda: tarefas.avisar_mudanca_status.enqueue(historico.pk))
    return solicitacao


# ---------------------------------------------------------------------------
# Escrita: prioridade (RF05)
# ---------------------------------------------------------------------------
def alterar_prioridade(*, solicitacao_id, prioridade, usuario):
    """Muda a prioridade e registra no histórico (o status não muda)."""
    with transaction.atomic():
        s = Solicitacao.objects.select_for_update().get(pk=solicitacao_id)
        if s.prioridade == prioridade:
            return s
        anterior = s.get_prioridade_display()
        s.prioridade = prioridade
        s.save(update_fields=["prioridade", "atualizado_em"])
        HistoricoSolicitacao.objects.create(
            solicitacao=s, usuario=usuario,
            status_anterior=s.status, status_novo=s.status,
            observacao=f"Prioridade alterada de {anterior} para {s.get_prioridade_display()}.",
        )
    return s


# ---------------------------------------------------------------------------
# Escrita: cancelamento pelo cidadão
# ---------------------------------------------------------------------------
class CancelamentoNaoPermitido(Exception):
    """O cidadão tentou cancelar algo que não pode mais ser cancelado."""


def pode_cancelar(solicitacao):
    """Regra de negócio: só cancela enquanto ninguém começou a analisar."""
    return str(solicitacao.status) == Status.ABERTA.value


def cancelar_pelo_cidadao(*, solicitacao_id, cidadao, motivo=""):
    """
    Duas verificações diferentes, de naturezas diferentes:

    1. AUTORIZAÇÃO (quem pode): o filtro cidadao=cidadao faz a busca falhar
       se a solicitação for de outra pessoa -> Solicitacao.DoesNotExist,
       que a view transforma em 404.
    2. REGRA DE NEGÓCIO (quando pode): só no status "Aberta".

    O select_for_update evita uma corrida real: a Maria clica em "Cancelar"
    no mesmo instante em que a Ana muda para "Em análise". Quem pegar o
    bloqueio primeiro vence; o segundo lê o status já atualizado.
    """
    with transaction.atomic():
        solicitacao = Solicitacao.objects.select_for_update().get(
            pk=solicitacao_id, cidadao=cidadao
        )
        if not pode_cancelar(solicitacao):
            raise CancelamentoNaoPermitido(
                "Esta solicitação já está "
                f"'{Status(solicitacao.status).label}' e não pode mais ser cancelada."
            )
        anterior = str(solicitacao.status)
        solicitacao.status = Status.CANCELADA
        solicitacao.save(update_fields=["status", "atualizado_em"])
        HistoricoSolicitacao.objects.create(
            solicitacao=solicitacao,
            usuario=cidadao.usuario,
            status_anterior=anterior,
            status_novo=Status.CANCELADA,
            observacao=motivo or "Cancelada pelo cidadão.",
        )
    return solicitacao


# ---------------------------------------------------------------------------
# Leitura: consultas usadas pelas telas
# ---------------------------------------------------------------------------
def _com_relacionados(queryset):
    """
    select_related faz JOIN e traz as tabelas relacionadas na MESMA consulta.

    Sem ele, uma lista de 50 solicitações que mostra cidadão, categoria e
    bairro faria 1 consulta para a lista + 50 x 3 consultas extras:
    o famoso "problema das N+1 consultas".
    """
    return queryset.select_related(
        "cidadao", "categoria", "categoria__secretaria", "bairro", "responsavel__usuario"
    )


def solicitacoes_da_secretaria(secretaria, *, status=None, bairro=None, busca=None):
    """
    Painel do servidor (RF04): só as solicitações da secretaria dele.

    Equivalente aproximado em SQL:
        SELECT ... FROM solicitacao s
        JOIN categoria_servico c ON c.id = s.categoria_id
        WHERE c.secretaria_id = %s
          AND (s.status = %s)                       -- se informado
          AND (s.descricao LIKE %s OR ...)          -- se houver busca
        ORDER BY s.prioridade DESC, s.criado_em
    """
    qs = Solicitacao.objects.all()
    if secretaria is not None:  # None = gestor, todas as secretarias
        qs = qs.filter(categoria__secretaria=secretaria)
    if status:
        qs = qs.filter(status=status)
    if bairro:
        qs = qs.filter(bairro=bairro)
    if busca:
        # Q permite montar OR; filter encadeado sempre faz AND.
        # icontains vira LIKE '%texto%' (sem diferenciar maiúsculas).
        qs = qs.filter(
            Q(descricao__icontains=busca)
            | Q(endereco_referencia__icontains=busca)
            | Q(cidadao__nome_completo__icontains=busca)
        )
    return _com_relacionados(qs).order_by("-prioridade", "criado_em")


STATUS_FINAIS = [Status.CONCLUIDA.value, Status.INDEFERIDA.value, Status.CANCELADA.value]


def solicitacoes_do_cidadao(cidadao):
    """
    Lista do cidadão com a data de ENCERRAMENTO de cada solicitação.

    Só "Concluída" tem coluna própria (concluida_em); o CHECK do banco
    obriga ela a ficar vazia nos outros status. Para "Indeferida" e
    "Cancelada", a data vem do histórico: é o registro que levou a
    solicitação ao status final. Isso é um dado DERIVADO (calculado),
    e não armazenado.

    Max(..., filter=Q(...)) vira, no SQL:
        MAX(CASE WHEN h.status_novo IN ('CON','IND','CAN')
                 THEN h.registrado_em END)
        ... LEFT JOIN historico_solicitacao h ... GROUP BY s.id, ...
    Tudo numa consulta só, sem N+1.
    """
    return (
        _com_relacionados(cidadao.solicitacoes.all())
        .annotate(
            encerrada_em=Max(
                "historico__registrado_em",
                filter=Q(historico__status_novo__in=STATUS_FINAIS),
            )
        )
        .order_by("-criado_em")
    )


def detalhe_para_servidor(pk, secretaria):
    """Busca a solicitação JÁ filtrando pela secretaria (autorização). None = todas (gestor)."""
    qs = Solicitacao.objects.filter(pk=pk)
    if secretaria is not None:
        qs = qs.filter(categoria__secretaria=secretaria)
    return _com_relacionados(qs).first()


def historico(solicitacao):
    return solicitacao.historico.select_related("usuario").order_by("registrado_em")


def data_limite(solicitacao):
    """Prazo de atendimento (SLA) = data de abertura + prazo da categoria."""
    return solicitacao.criado_em + timedelta(days=solicitacao.categoria.prazo_dias)


def esta_atrasada(solicitacao):
    finais = {Status.CONCLUIDA.value, Status.INDEFERIDA.value, Status.CANCELADA.value}
    return str(solicitacao.status) not in finais and timezone.now() > data_limite(solicitacao)


# ---------------------------------------------------------------------------
# Relatório (RF07): agregação = GROUP BY
# ---------------------------------------------------------------------------
def relatorio_por_zona(secretaria=None):
    """
    Conta solicitações por zona e status.

    values(...) + annotate(Count) gera exatamente:
        SELECT b.zona, s.status, COUNT(s.id) AS total
        FROM solicitacao s JOIN bairro b ON b.id = s.bairro_id
        GROUP BY b.zona, s.status

    Devolve uma tabela pronta para o template:
        [{"zona": "Zona Norte", "por_status": [2, 0, 1, 0, 0], "total": 3}, ...]
    """
    qs = Solicitacao.objects.all()
    if secretaria is not None:
        qs = qs.filter(categoria__secretaria=secretaria)

    agrupado = qs.values("bairro__zona", "status").annotate(total=Count("id"))

    from .models import Bairro  # import local só para os rótulos das zonas

    linhas = {z.value: {"zona": z.label, "contagem": {}, "total": 0} for z in Bairro.Zona}
    for item in agrupado:
        linha = linhas[item["bairro__zona"]]
        linha["contagem"][item["status"]] = item["total"]
        linha["total"] += item["total"]

    resultado = []
    for linha in linhas.values():
        linha["por_status"] = [linha["contagem"].get(s.value, 0) for s in Status]
        resultado.append(linha)
    totais_status = [sum(l["por_status"][i] for l in resultado) for i in range(len(Status))]
    return resultado, totais_status, sum(totais_status)
