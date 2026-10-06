"""
SAG-Cidadão — views (o "controller" do MVC)
App: atendimento/views.py

Toda view baseada em função segue o mesmo ciclo:
    1. Recebe um objeto HttpRequest (método, usuário logado, GET, POST...)
    2. Decide o que fazer (chama o services.py)
    3. Devolve um HttpResponse (render de template ou redirect)

Conceitos de prova neste arquivo:
    - Autenticação (@login_required) x Autorização (filtro por secretaria)
    - GET (consultar, não altera nada) x POST (altera dados)
    - Padrão Post/Redirect/Get (PRG): evita reenvio do formulário com F5
    - 403 Forbidden x 404 Not Found
    - CSRF: o {% csrf_token %} nos templates + o middleware do Django
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from . import seguranca, services
from apps.gestao.permissoes import eh_gestor

from .forms import (
    AlterarStatusForm,
    PrioridadeForm,
    CadastroCidadaoForm,
    ConsultaProtocoloForm,
    FiltroPainelForm,
    NovaSolicitacaoForm,
)
from .models import Solicitacao


# ---------------------------------------------------------------------------
# Auxiliares de autorização
# ---------------------------------------------------------------------------
def _escopo(request):
    """
    Quem pode ver solicitações internas e com que alcance:
      servidor -> (servidor, secretaria dele)
      gestor   -> (servidor ou None, None = todas as secretarias)
    Qualquer outro perfil: 403.
    """
    servidor = request.user.servidor if hasattr(request.user, "servidor") else None
    if eh_gestor(request.user):
        return servidor, None
    if servidor is None:
        raise PermissionDenied("Área restrita a servidores.")
    return servidor, servidor.secretaria


def _cidadao_ou_403(request):
    if not hasattr(request.user, "cidadao"):
        raise PermissionDenied("Área restrita a cidadãos cadastrados.")
    return request.user.cidadao


# ---------------------------------------------------------------------------
# Página inicial: encaminha cada perfil para sua área
# ---------------------------------------------------------------------------
def inicio(request):
    if request.user.is_authenticated:
        if eh_gestor(request.user):
            return redirect("gestao:dashboard")
        if hasattr(request.user, "servidor"):
            return redirect("atendimento:painel")
        if hasattr(request.user, "cidadao"):
            return redirect("atendimento:minhas")
    return render(request, "atendimento/inicio.html", {"form": ConsultaProtocoloForm()})


def privacidade(request):
    return render(request, "atendimento/privacidade.html")


# ---------------------------------------------------------------------------
# RF04 — Painel do servidor
# ---------------------------------------------------------------------------
@login_required
def painel(request):
    servidor, secretaria = _escopo(request)

    # Filtros chegam por GET (request.GET), pois apenas CONSULTAM dados.
    filtro = FiltroPainelForm(request.GET or None, gestor=secretaria is None)
    filtros = filtro.cleaned_data if filtro.is_valid() else {}
    if secretaria is None and filtros.get("secretaria"):
        secretaria = filtros["secretaria"]  # gestor escolheu uma secretaria

    qs = services.solicitacoes_da_secretaria(
        secretaria,
        status=filtros.get("status"),
        bairro=filtros.get("bairro"),
        busca=filtros.get("busca"),
    )

    # Paginação: LIMIT/OFFSET no SQL. Nunca carregue a tabela inteira.
    pagina = Paginator(qs, 20).get_page(request.GET.get("page"))
    for s in pagina:
        s.atrasada = services.esta_atrasada(s)

    # Mantém os filtros ao trocar de página
    params = request.GET.copy()
    params.pop("page", None)

    return render(
        request,
        "atendimento/painel.html",
        {
            "servidor": servidor,
            "secretaria": secretaria,
            "filtro": filtro,
            "pagina": pagina,
            "querystring": params.urlencode(),
        },
    )


# ---------------------------------------------------------------------------
# RF05 — Detalhe e mudança de status
# ---------------------------------------------------------------------------
@login_required
@require_http_methods(["GET", "POST"])
def detalhe(request, pk):
    servidor, secretaria = _escopo(request)

    # A busca JÁ filtra pela secretaria (gestor: secretaria=None, vê todas).
    # Se a solicitação for de outra secretaria, respondemos 404 (e não 403)
    # para não revelar que ela existe. Sem esse filtro, bastaria trocar o
    # número na URL para ver dados alheios (IDOR).
    solicitacao = services.detalhe_para_servidor(pk, secretaria)
    if solicitacao is None:
        raise Http404("Solicitação não encontrada.")

    # Mudar status: só o servidor da secretaria responsável.
    # Mudar prioridade: o servidor da secretaria ou o gestor.
    pode_status = servidor is not None and servidor.secretaria_id == solicitacao.categoria.secretaria_id
    pode_prioridade = pode_status or eh_gestor(request.user)

    form = AlterarStatusForm(status_atual=solicitacao.status)
    form_prioridade = PrioridadeForm(initial={"prioridade": solicitacao.prioridade})

    if request.method == "POST":
        acao = request.POST.get("acao")
        if acao == "prioridade" and pode_prioridade:
            form_prioridade = PrioridadeForm(request.POST)
            if form_prioridade.is_valid():
                services.alterar_prioridade(
                    solicitacao_id=solicitacao.pk,
                    prioridade=int(form_prioridade.cleaned_data["prioridade"]),
                    usuario=request.user,
                )
                messages.success(request, "Prioridade atualizada.")
                return redirect("atendimento:detalhe", pk=solicitacao.pk)
        elif acao == "status" and pode_status:
            form = AlterarStatusForm(request.POST, status_atual=solicitacao.status)
            if form.is_valid():
                try:
                    services.alterar_status(
                        solicitacao_id=solicitacao.pk,
                        novo_status=form.cleaned_data["novo_status"],
                        usuario=request.user,
                        observacao=form.cleaned_data["observacao"],
                        responsavel=servidor,
                    )
                except services.TransicaoInvalida as erro:
                    messages.error(request, str(erro))
                else:
                    messages.success(request, "Status atualizado.")
                # PRG: depois de um POST, sempre redirecionar.
                return redirect("atendimento:detalhe", pk=solicitacao.pk)
        else:
            raise PermissionDenied("Ação não permitida para o seu perfil.")

    return render(
        request,
        "atendimento/detalhe.html",
        {
            "s": solicitacao,
            "form": form,
            "form_prioridade": form_prioridade,
            "pode_status": pode_status,
            "pode_prioridade": pode_prioridade,
            "historico": services.historico(solicitacao),
            "data_limite": services.data_limite(solicitacao),
            "atrasada": services.esta_atrasada(solicitacao),
        },
    )


# ---------------------------------------------------------------------------
# RF02 — Cidadão abre solicitação
# ---------------------------------------------------------------------------
@login_required
@require_http_methods(["GET", "POST"])
def nova_solicitacao(request):
    cidadao = _cidadao_ou_403(request)

    if request.method == "POST":
        form = NovaSolicitacaoForm(request.POST)
        if form.is_valid():
            # O cidadão vem da SESSÃO (request.user), nunca do formulário:
            # assim ninguém abre solicitação em nome de outra pessoa.
            solicitacao = services.abrir_solicitacao(cidadao=cidadao, **form.cleaned_data)
            messages.success(
                request, f"Solicitação registrada. Protocolo: {solicitacao.protocolo}"
            )
            return redirect("atendimento:minhas")
    else:
        # Sugere o bairro do cidadão (pode ser alterado)
        form = NovaSolicitacaoForm(initial={"bairro": cidadao.bairro})

    return render(request, "atendimento/nova.html", {"form": form})


@login_required
def minhas_solicitacoes(request):
    cidadao = _cidadao_ou_403(request)
    solicitacoes = list(services.solicitacoes_do_cidadao(cidadao))
    for s in solicitacoes:
        # A tela só mostra o botão; quem decide de verdade é o serviço.
        s.cancelavel = services.pode_cancelar(s)
    return render(request, "atendimento/minhas.html", {"solicitacoes": solicitacoes})


@login_required
@require_POST
def cancelar_solicitacao(request, pk):
    """
    Só aceita POST (@require_POST responde 405 a um GET). Cancelar altera
    dados, então não pode ser um simples link: um <img src="/cancelar/5/">
    em qualquer site faria o navegador da vítima disparar o cancelamento.
    """
    cidadao = _cidadao_ou_403(request)
    try:
        services.cancelar_pelo_cidadao(
            solicitacao_id=pk,
            cidadao=cidadao,
            motivo=request.POST.get("motivo", "").strip()[:200],
        )
    except Solicitacao.DoesNotExist:
        # Não existe OU é de outra pessoa: mesma resposta (não revela nada)
        raise Http404("Solicitação não encontrada.")
    except services.CancelamentoNaoPermitido as erro:
        messages.error(request, str(erro))
    else:
        messages.success(request, "Solicitação cancelada.")
    return redirect("atendimento:minhas")  # PRG


# ---------------------------------------------------------------------------
# RF03 — Consulta pública por protocolo (sem login)
# ---------------------------------------------------------------------------
@seguranca.limitar("protocolo", limite=30, janela=60, metodos=("GET",))
def consulta_protocolo(request):
    form = ConsultaProtocoloForm(request.GET or None)
    solicitacao = None
    historico = None

    if form.is_valid():
        solicitacao = (
            Solicitacao.objects.select_related("categoria", "bairro")
            .filter(protocolo=form.cleaned_data["protocolo"])
            .first()
        )
        if solicitacao is None:
            form.add_error("protocolo", "Nenhuma solicitação com este protocolo.")
        else:
            historico = services.historico(solicitacao)

    # O template público mostra status, categoria, bairro e datas, mas NÃO
    # mostra nome, CPF ou descrição (princípio da necessidade da LGPD).
    return render(
        request,
        "atendimento/consulta.html",
        {"form": form, "s": solicitacao, "historico": historico},
    )


# ---------------------------------------------------------------------------
# RF07 — Relatório por zona e status
# ---------------------------------------------------------------------------
@login_required
def relatorio(request):
    servidor, secretaria = _escopo(request)
    linhas, totais, total_geral = services.relatorio_por_zona(secretaria)
    return render(
        request,
        "atendimento/relatorio.html",
        {
            "servidor": servidor,
            "secretaria": secretaria,
            "status_labels": [s.label for s in Solicitacao.Status],
            "linhas": linhas,
            "totais": totais,
            "total_geral": total_geral,
        },
    )
