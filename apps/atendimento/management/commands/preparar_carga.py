"""
Prepara o teste de carga: abre sessões autenticadas para cidadãos,
servidores e gestor de DEMONSTRAÇÃO e grava num arquivo para o Locust.

    python manage.py popular_demo
    python manage.py preparar_carga --saida deploy/qa/carga.json

As sessões são criadas direto no banco porque 200 robôs entrando pela
tela de login seriam, corretamente, barrados pelo limite de tentativas.
Use SOMENTE em ambiente de teste: o arquivo contém sessões válidas.
"""
import json

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.atendimento.ferramentas import criar_sessao
from apps.atendimento.models import Cidadao, Servidor, Solicitacao
from apps.gestao.permissoes import GRUPO_GESTOR

User = get_user_model()


class Command(BaseCommand):
    help = "Cria sessões de teste (dados de demonstração) para o teste de carga com Locust."

    def add_arguments(self, parser):
        parser.add_argument("--saida", default="carga.json")

    def handle(self, saida, **opcoes):
        cidadaos = list(Cidadao.objects.filter(usuario__email__endswith="@demo.sag", usuario__is_active=True).select_related("usuario"))
        servidores = list(Servidor.objects.filter(usuario__email__endswith="@demo.sag").select_related("usuario"))
        gestor = (User.objects.filter(groups__name=GRUPO_GESTOR, is_active=True).first()
                  or User.objects.filter(is_superuser=True, is_active=True).first())
        if not cidadaos or not servidores or not gestor:
            raise CommandError("Rode 'python manage.py popular_demo' e tenha um gestor.")
        dados = {
            "cidadaos": [criar_sessao(c.usuario) | {"bairro": c.bairro_id} for c in cidadaos],
            "servidores": [criar_sessao(s.usuario) | {"solicitacoes": list(
                Solicitacao.objects.filter(categoria__secretaria=s.secretaria).values_list("pk", flat=True)[:50])} for s in servidores],
            "gestores": [criar_sessao(gestor)],
            "categorias": list(Solicitacao.objects.values_list("categoria_id", flat=True).distinct()),
        }
        with open(saida, "w", encoding="utf-8") as f:
            json.dump(dados, f)
        self.stdout.write(self.style.SUCCESS(
            f"Sessões criadas: {len(cidadaos)} cidadãos, {len(servidores)} servidores, 1 gestor -> {saida}"))
