"""
Testes do monitoramento: verificar_sistema e alertas de erro sem enxurrada.
"""
import io
import logging
import os
import shutil
import tempfile
from datetime import timedelta
from unittest import mock

from django.core import mail
from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.auditoria.models import RegistroAuditoria


def rodar():
    saida = io.StringIO()
    try:
        call_command("verificar_sistema", stdout=saida)
        codigo = 0
    except SystemExit as e:
        codigo = e.code
    return codigo, saida.getvalue()


@override_settings(ADMINS=["plantao@exemplo.gov.br"])
class VerificarSistemaTest(TestCase):
    def setUp(self):
        cache.clear()
        self.pasta = tempfile.mkdtemp()
        with open(os.path.join(self.pasta, "ULTIMO_OK"), "w") as f:
            f.write("ok")
        self.env = mock.patch.dict(os.environ, {"BACKUP_DIR": self.pasta})
        self.env.start()
        # O teste não pode depender do disco da máquina onde roda
        self.disco = mock.patch(
            "apps.atendimento.management.commands.verificar_sistema.shutil.disk_usage",
            return_value=shutil._ntuple_diskusage(total=100 * 2**30, used=50 * 2**30, free=50 * 2**30),
        )
        self.disco.start()

    def tearDown(self):
        self.env.stop()
        self.disco.stop()

    def test_tudo_certo(self):
        codigo, saida = rodar()
        self.assertEqual(codigo, 0, saida)
        self.assertEqual(len(mail.outbox), 0)

    def test_disco_quase_cheio(self):
        self.disco.stop()
        cheio = shutil._ntuple_diskusage(total=100 * 2**30, used=97 * 2**30, free=3 * 2**30)
        with mock.patch("apps.atendimento.management.commands.verificar_sistema.shutil.disk_usage", return_value=cheio):
            codigo, saida = rodar()
        self.disco.start()
        self.assertEqual(codigo, 1)
        self.assertIn("3% livre", saida)

    def test_backup_atrasado_gera_alerta_por_email(self):
        velho = timezone.now().timestamp() - 30 * 3600
        os.utime(os.path.join(self.pasta, "ULTIMO_OK"), (velho, velho))
        codigo, saida = rodar()
        self.assertEqual(codigo, 1)
        self.assertIn("backup", saida)
        self.assertEqual(mail.outbox[0].to, ["plantao@exemplo.gov.br"])

    def test_mesmo_alerta_nao_repete_dentro_de_uma_hora(self):
        os.remove(os.path.join(self.pasta, "ULTIMO_OK"))
        rodar()
        rodar()
        self.assertEqual(len(mail.outbox), 1)

    def test_pico_de_logins_recusados(self):
        for _ in range(101):
            RegistroAuditoria.objects.create(acao=RegistroAuditoria.Acao.LOGIN_FALHA)
        codigo, saida = rodar()
        self.assertEqual(codigo, 1)
        self.assertIn("força bruta", saida)

    @override_settings(TASKS={"default": {"BACKEND": "django_tasks_db.DatabaseBackend"}})
    def test_worker_parado(self):
        from django_tasks_db.models import DBTaskResult

        from apps.atendimento.tarefas import avisar_abertura

        avisar_abertura.enqueue(1)
        DBTaskResult.objects.update(enqueued_at=timezone.now() - timedelta(minutes=30))
        codigo, saida = rodar()
        self.assertEqual(codigo, 1)
        self.assertIn("worker", saida)


@override_settings(ADMINS=["plantao@exemplo.gov.br"], DEBUG=False)
class AlertaDeErroTest(TestCase):
    def setUp(self):
        cache.clear()

    def test_o_mesmo_erro_gera_um_so_email(self):
        from apps.atendimento.alertas import AlertaPorEmail

        logger = logging.getLogger("teste.alerta")
        logger.addHandler(AlertaPorEmail())
        logger.propagate = False
        for _ in range(50):
            try:
                1 / 0
            except ZeroDivisionError:
                logger.error("Falha ao calcular o indicador", exc_info=True)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("ZeroDivisionError", mail.outbox[0].body)
