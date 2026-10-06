"""
Apaga autocadastros que não confirmaram o e-mail no prazo (LGPD: necessidade).

    python manage.py limpar_cadastros_pendentes            # mais antigos que 24 h
    python manage.py limpar_cadastros_pendentes --horas 48

Em produção, agende no cron do servidor, por exemplo a cada hora:
    0 * * * *  cd /srv/sag && .venv/bin/python manage.py limpar_cadastros_pendentes
"""
from django.core.management.base import BaseCommand

from apps.atendimento.services import apagar_cadastros_pendentes


class Command(BaseCommand):
    help = "Apaga cadastros de cidadãos não confirmados por e-mail dentro do prazo."

    def add_arguments(self, parser):
        parser.add_argument("--horas", type=int, default=24)

    def handle(self, horas, **_):
        total = apagar_cadastros_pendentes(horas=horas)
        self.stdout.write(self.style.SUCCESS(f"{total} cadastro(s) pendente(s) removido(s)."))
