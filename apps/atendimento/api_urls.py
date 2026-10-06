"""
SAG-Cidadão — rotas da API
App: atendimento/api_urls.py

O DefaultRouter gera as URLs do ViewSet automaticamente:
    solicitacoes/                -> list (GET) e create (POST)
    solicitacoes/{id}/           -> retrieve (GET)
    solicitacoes/{id}/status/    -> ação alterar_status (POST)
    solicitacoes/{id}/cancelar/  -> ação cancelar (POST)
e uma página-raiz (/api/) com links para os recursos.
"""
from django.urls import path
from rest_framework.routers import DefaultRouter

from .api import ConsultaProtocoloAPI, ObterToken, SolicitacaoViewSet

router = DefaultRouter()
router.register("solicitacoes", SolicitacaoViewSet, basename="api-solicitacao")

urlpatterns = [
    path("token/", ObterToken.as_view(), name="api-token"),
    path("protocolo/<uuid:protocolo>/", ConsultaProtocoloAPI.as_view(), name="api-protocolo"),
] + router.urls
