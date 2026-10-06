"""
SAG-Cidadão — API REST
App: atendimento/api.py

Endpoints (prefixo /api/):

    POST   /api/token/                         -> obtém o token (usuário + senha)
    GET    /api/solicitacoes/                  -> lista (servidor: da secretaria; cidadão: as dele)
    POST   /api/solicitacoes/                  -> cidadão abre solicitação            -> 201
    GET    /api/solicitacoes/{id}/             -> detalhe com histórico               -> 200 / 404
    POST   /api/solicitacoes/{id}/status/      -> servidor muda o status              -> 200 / 409
    POST   /api/solicitacoes/{id}/cancelar/    -> cidadão cancela                     -> 200 / 409
    GET    /api/protocolo/{uuid}/              -> consulta pública, sem login         -> 200 / 404

    PUT, PATCH e DELETE não existem: respondem 405 (Method Not Allowed).
    Toda mudança passa pelas regras do services.py.

Conceitos de prova:
    - REST: recursos identificados por URL; verbos HTTP dizem a ação
    - Stateless: cada requisição leva o token; o servidor não guarda sessão
    - Códigos de status: 200, 201, 400, 401, 403, 404, 405, 409
    - Idempotência: GET é seguro e idempotente; POST não é idempotente
"""
from django.db.models import Prefetch
from rest_framework import mixins, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.response import Response
from rest_framework.authtoken.views import ObtainAuthToken
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from . import services
from .models import HistoricoSolicitacao, Solicitacao
from .serializers import (
    AlterarStatusSerializer,
    CancelarSerializer,
    ConsultaPublicaSerializer,
    NovaSolicitacaoSerializer,
    SolicitacaoDetalheSerializer,
    SolicitacaoSerializer,
)


# ---------------------------------------------------------------------------
# Permissões (autorização)
# ---------------------------------------------------------------------------
class EhServidorOuCidadao(permissions.BasePermission):
    """Autenticado (401 se não) e com perfil de servidor ou cidadão (403 se não)."""

    message = "Usuário sem perfil de servidor ou de cidadão."

    def has_permission(self, request, view):
        u = request.user
        return bool(u and u.is_authenticated and (hasattr(u, "servidor") or hasattr(u, "cidadao")))


def _servidor(request):
    return getattr(request.user, "servidor", None) if hasattr(request.user, "servidor") else None


def _cidadao(request):
    return getattr(request.user, "cidadao", None) if hasattr(request.user, "cidadao") else None


# ---------------------------------------------------------------------------
# Recurso: solicitações
# ---------------------------------------------------------------------------
class SolicitacaoViewSet(
    mixins.ListModelMixin,      # GET  /solicitacoes/
    mixins.RetrieveModelMixin,  # GET  /solicitacoes/{id}/
    viewsets.GenericViewSet,    # (create e as ações são escritas à mão)
):
    permission_classes = [EhServidorOuCidadao]

    def get_queryset(self):
        """
        O ESCOPO de dados é a autorização: cada perfil só "enxerga" o que é seu.
        Pedir o id de algo fora do escopo resulta em 404 (IDOR bloqueado).
        """
        servidor, cidadao = _servidor(self.request), _cidadao(self.request)
        if servidor:
            qs = services.solicitacoes_da_secretaria(
                servidor.secretaria, status=self.request.query_params.get("status")
            )
        else:
            qs = services.solicitacoes_do_cidadao(cidadao)
            if self.request.query_params.get("status"):
                qs = qs.filter(status=self.request.query_params["status"])
        if self.action == "retrieve":
            qs = qs.prefetch_related(
                Prefetch("historico", queryset=HistoricoSolicitacao.objects.select_related("usuario").order_by("registrado_em"))
            )
        return qs

    def get_serializer_class(self):
        return SolicitacaoDetalheSerializer if self.action == "retrieve" else SolicitacaoSerializer

    # POST /api/solicitacoes/ -------------------------------------------------
    def create(self, request):
        cidadao = _cidadao(request)
        if cidadao is None:
            raise PermissionDenied("Somente cidadãos abrem solicitações.")  # 403
        entrada = NovaSolicitacaoSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)  # 400 com os erros, campo a campo
        solicitacao = services.abrir_solicitacao(cidadao=cidadao, **entrada.validated_data)
        saida = SolicitacaoSerializer(solicitacao).data
        # 201 Created + cabeçalho Location com a URL do novo recurso
        url = request.build_absolute_uri(f"{solicitacao.pk}/")
        return Response(saida, status=status.HTTP_201_CREATED, headers={"Location": url})

    # POST /api/solicitacoes/{id}/status/ -------------------------------------
    @action(detail=True, methods=["post"], url_path="status")
    def alterar_status(self, request, pk=None):
        servidor = _servidor(request)
        if servidor is None:
            raise PermissionDenied("Somente servidores alteram o status.")
        solicitacao = self.get_object()  # 404 se for de outra secretaria
        entrada = AlterarStatusSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        try:
            solicitacao = services.alterar_status(
                solicitacao_id=solicitacao.pk,
                novo_status=entrada.validated_data["novo_status"],
                usuario=request.user,
                observacao=entrada.validated_data.get("observacao", ""),
                responsavel=servidor,
            )
        except services.TransicaoInvalida as erro:
            # 409 Conflict: a requisição é válida, mas conflita com o
            # ESTADO atual do recurso.
            return Response({"detail": str(erro)}, status=status.HTTP_409_CONFLICT)
        return Response(SolicitacaoSerializer(self.get_queryset().get(pk=solicitacao.pk)).data)

    # POST /api/solicitacoes/{id}/cancelar/ -----------------------------------
    @action(detail=True, methods=["post"])
    def cancelar(self, request, pk=None):
        cidadao = _cidadao(request)
        if cidadao is None:
            raise PermissionDenied("Somente o cidadão autor pode cancelar.")
        entrada = CancelarSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        try:
            services.cancelar_pelo_cidadao(
                solicitacao_id=pk, cidadao=cidadao, motivo=entrada.validated_data.get("motivo", "")
            )
        except Solicitacao.DoesNotExist:
            raise NotFound("Solicitação não encontrada.")
        except services.CancelamentoNaoPermitido as erro:
            return Response({"detail": str(erro)}, status=status.HTTP_409_CONFLICT)
        return Response(SolicitacaoSerializer(self.get_queryset().get(pk=pk)).data)


# ---------------------------------------------------------------------------
# Consulta pública por protocolo (sem autenticação)
# ---------------------------------------------------------------------------
class ConsultaProtocoloAPI(APIView):
    permission_classes = [permissions.AllowAny]  # liberado explicitamente
    authentication_classes = []                  # não precisa nem olhar token
    throttle_scope = "protocolo"                 # 30 consultas/min por IP

    def get(self, request, protocolo):
        s = Solicitacao.objects.select_related("categoria", "bairro").filter(protocolo=protocolo).first()
        if s is None:
            raise NotFound("Nenhuma solicitação com este protocolo.")
        return Response(ConsultaPublicaSerializer(s).data)


class ObterToken(ObtainAuthToken):
    """
    POST /api/token/ com limite próprio (10/min por IP) contra força bruta.

    Atenção: a ObtainAuthToken original do DRF declara throttle_classes = (),
    o que DESLIGA os limites globais do settings. Por isso é preciso
    declarar a classe de limite aqui, explicitamente.
    """

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "token"
