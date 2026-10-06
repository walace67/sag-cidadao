"""
Testes dos avisos por e-mail ao cidadão (tarefas em segundo plano).
    python manage.py test apps.atendimento.tests_avisos
"""
from django.core import mail

from . import services
from .tests import BaseSAG


class AvisosTest(BaseSAG):
    def setUp(self):
        super().setUp()
        u = self.maria.usuario
        u.email = "maria@exemplo.com"
        u.save()

    def test_abertura_avisa_com_protocolo(self):
        with self.captureOnCommitCallbacks(execute=True):
            s = self.nova()
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(str(s.protocolo), mail.outbox[0].body)
        self.assertNotIn(self.maria.cpf, mail.outbox[0].body)  # nada de CPF no e-mail

    def test_mudanca_de_status_avisa_com_observacao(self):
        s = self.nova()
        with self.captureOnCommitCallbacks(execute=True):
            services.alterar_status(solicitacao_id=s.pk, novo_status="ANA", usuario=self.u_ana,
                                    observacao="Vistoria na quinta-feira.")
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Em análise", mail.outbox[0].subject)
        self.assertIn("Vistoria na quinta-feira.", mail.outbox[0].body)

    def test_quem_desativou_os_avisos_nao_recebe(self):
        self.maria.receber_avisos = False
        self.maria.save()
        s = self.nova()
        with self.captureOnCommitCallbacks(execute=True):
            services.alterar_status(solicitacao_id=s.pk, novo_status="ANA", usuario=self.u_ana)
        self.assertEqual(len(mail.outbox), 0)

    def test_transicao_invalida_nao_avisa(self):
        s = self.nova()
        with self.captureOnCommitCallbacks(execute=True):
            with self.assertRaises(services.TransicaoInvalida):
                services.alterar_status(solicitacao_id=s.pk, novo_status="CON", usuario=self.u_ana)
        self.assertEqual(len(mail.outbox), 0)  # ROLLBACK: nenhum on_commit dispara

    def test_aviso_espera_o_commit(self):
        s = self.nova()
        with self.captureOnCommitCallbacks(execute=False) as pendentes:
            services.alterar_status(solicitacao_id=s.pk, novo_status="ANA", usuario=self.u_ana)
        self.assertEqual(len(mail.outbox), 0)   # ainda não saiu: está esperando o COMMIT
        self.assertEqual(len(pendentes), 1)
