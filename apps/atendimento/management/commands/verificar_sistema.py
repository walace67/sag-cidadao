"""
Monitoramento ATIVO: confere a saúde do sistema por dentro e avisa a
equipe por e-mail (ADMINS) quando algo sai do normal.

    python manage.py verificar_sistema            # mostra e alerta
    python manage.py verificar_sistema --sem-email

Agendado a cada 10 minutos (deploy/systemd/sag-monitor.timer). O /saude/
responde "está no ar?" para quem olha de fora; este comando responde
"está tudo funcionando como deveria?" olhando por dentro.

Verificações:
    banco        o PostgreSQL responde
    fila         tarefas esperando há mais de 10 min = worker parado
    falhas       tarefas que falharam nas últimas 24 h (ex.: SMTP fora)
    backup       o último backup bom tem menos de 26 horas
    disco        pelo menos 10% livre onde ficam as fotos
    acessos      pico de logins recusados na última hora = possível ataque

Código de saída 0 = tudo certo; 1 = há alerta (o systemd registra a falha).
"""
import hashlib
import os
import shutil
import time
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.cache import cache
from django.core.mail import mail_admins
from django.core.management.base import BaseCommand
from django.db import connection
from django.utils import timezone

LIMITE_FILA_MIN = 10
LIMITE_BACKUP_H = 26
LIMITE_DISCO_LIVRE = 0.10
LIMITE_LOGINS_RECUSADOS_HORA = 100
REPETIR_ALERTA_A_CADA = 60 * 60  # o mesmo conjunto de problemas: 1 e-mail por hora


def checar_banco():
    with connection.cursor() as c:
        c.execute("SELECT 1")
    return None


def checar_fila():
    from django_tasks_db.models import DBTaskResult

    limite = timezone.now() - timedelta(minutes=LIMITE_FILA_MIN)
    paradas = DBTaskResult.objects.filter(status="READY", enqueued_at__lt=limite).count()
    if paradas:
        return f"{paradas} tarefa(s) esperando há mais de {LIMITE_FILA_MIN} min: o worker (sag-worker) está parado?"
    return None


def checar_falhas():
    from django_tasks_db.models import DBTaskResult

    falhas = DBTaskResult.objects.filter(status="FAILED", finished_at__gte=timezone.now() - timedelta(hours=24)).count()
    if falhas:
        return f"{falhas} tarefa(s) falharam nas últimas 24 h (e-mails não enviados?). Veja: journalctl -u sag-worker"
    return None


def checar_backup():
    from decouple import config  # mesma fonte dos scripts de backup: o .env

    pasta = Path(os.path.expanduser(config("BACKUP_DIR", default="~/backups_sag/postgres")))
    marca = pasta / "ULTIMO_OK"
    if not marca.exists():
        return f"Nenhum backup registrado em {pasta} (deploy/backup/backup.sh já rodou?)"
    idade_h = (time.time() - marca.stat().st_mtime) / 3600
    if idade_h > LIMITE_BACKUP_H:
        return f"O último backup tem {idade_h:.0f} horas (limite: {LIMITE_BACKUP_H} h). O agendamento está rodando?"
    return None


def checar_disco():
    pasta = Path(settings.MEDIA_ROOT)
    alvo = pasta if pasta.exists() else Path(settings.BASE_DIR)
    uso = shutil.disk_usage(alvo)
    livre = uso.free / uso.total
    if livre < LIMITE_DISCO_LIVRE:
        return f"Disco com só {livre:.0%} livre em {alvo} ({uso.free // 2**30} GB)."
    return None


def checar_acessos():
    from apps.auditoria.models import RegistroAuditoria

    recusados = RegistroAuditoria.objects.filter(
        acao=RegistroAuditoria.Acao.LOGIN_FALHA, registrado_em__gte=timezone.now() - timedelta(hours=1)
    ).count()
    if recusados > LIMITE_LOGINS_RECUSADOS_HORA:
        return (f"{recusados} logins recusados na última hora (limite: {LIMITE_LOGINS_RECUSADOS_HORA}). "
                "Possível ataque de força bruta: veja a trilha de auditoria.")
    return None


VERIFICACOES = [
    ("banco", checar_banco), ("fila", checar_fila), ("falhas", checar_falhas),
    ("backup", checar_backup), ("disco", checar_disco), ("acessos", checar_acessos),
]


class Command(BaseCommand):
    help = "Confere banco, fila de tarefas, backup, disco e acessos; avisa os ADMINS por e-mail."

    def add_arguments(self, parser):
        parser.add_argument("--sem-email", action="store_true")

    def handle(self, sem_email, **opcoes):
        problemas = []
        for nome, verificar in VERIFICACOES:
            try:
                problema = verificar()
            except Exception as erro:  # a própria verificação falhar já é um problema
                problema = f"falha ao verificar: {erro}"
            if problema:
                problemas.append(f"[{nome}] {problema}")
                self.stdout.write(self.style.ERROR(f"ALERTA  {nome}: {problema}"))
            else:
                self.stdout.write(self.style.SUCCESS(f"OK      {nome}"))

        if not problemas:
            return
        texto = "\n".join(problemas)
        # hashlib, e não hash(): o hash() do Python muda a cada execução
        chave = "monitor:" + hashlib.sha256(texto.encode()).hexdigest()[:24]
        if not sem_email and settings.ADMINS and cache.add(chave, 1, timeout=REPETIR_ALERTA_A_CADA):
            mail_admins(f"Alerta do monitoramento ({len(problemas)})",
                        texto + "\n\nVerificado em " + timezone.localtime().strftime("%d/%m/%Y %H:%M"))
            self.stdout.write("Alerta enviado por e-mail aos administradores.")
        raise SystemExit(1)
