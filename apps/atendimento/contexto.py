"""Variáveis disponíveis em todos os templates."""
from django.conf import settings


def mapa(request):
    # Endereço dos "azulejos" do mapa; trocável no .env por um servidor próprio
    return {"tiles": settings.MAPA_TILES}
