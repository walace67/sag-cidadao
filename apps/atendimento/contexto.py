"""Variáveis disponíveis em todos os templates."""
from django.conf import settings


def mapa(request):
    # Endereço dos "azulejos" do mapa; trocável no .env por um servidor próprio
    from apps.govbr.oidc import habilitado

    return {"tiles": settings.MAPA_TILES, "govbr_habilitado": habilitado()}
