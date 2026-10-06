"""
Testes da trilha de auditoria.
    python manage.py test apps.auditoria
"""
from django.contrib.auth.models import User
from django.db import DatabaseError, connection, transaction
from django.urls import reverse

from apps.atendimento.tests import BaseSAG
from apps.gestao.permissoes import grupo_gestor

from .models import RegistroAuditoria, RegistroImutavel
from .registro import A, registrar


class AuditoriaTest(BaseSAG):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.gestor = User.objects.create_user("gestora", password="Teste@2026", first_name="Gina")
        cls.gestor.groups.add(grupo_gestor())

    def test_login_e_falha_ficam_registrados_sem_cpf(self):
        self.client.post(reverse("login"), {"username": "529.982.247-25", "password": "senha-errada"})
        falha = RegistroAuditoria.objects.get(acao=A.LOGIN_FALHA)
        self.assertNotIn("52998224725", str(falha.detalhes))  # o login vai como hash
        self.assertEqual(falha.ip, "127.0.0.1")
        self.client.post(reverse("login"), {"username": "ana", "password": "Teste@2026"})
        self.assertTrue(RegistroAuditoria.objects.filter(acao=A.LOGIN, usuario=self.u_ana).exists())

    def test_alteracao_de_cadastro_guarda_antes_e_depois(self):
        self.client.force_login(self.gestor)
        self.client.post(reverse("gestao:cadastro_editar", args=["categorias", self.buraco.pk]), {
            "secretaria": self.semob.pk, "nome": "Tapa-buraco", "prazo_dias": 15, "ativa": "on",
        })
        r = RegistroAuditoria.objects.get(acao=A.ALTERAR)
        self.assertEqual(r.usuario, self.gestor)
        self.assertIn(["30", "15"], r.detalhes.values())

    def test_desativar_servidor_fica_registrado(self):
        self.client.force_login(self.gestor)
        self.client.post(reverse("gestao:servidor_alternar", args=[self.ana.pk]))
        r = RegistroAuditoria.objects.get(acao=A.DESATIVAR)
        self.assertEqual(r.objeto_id, str(self.u_ana.pk))

    def test_exportacao_de_dados_pelo_titular_fica_registrada(self):
        self.client.force_login(self.maria.usuario)
        self.client.get(reverse("atendimento:exportar_dados"))
        self.assertTrue(RegistroAuditoria.objects.filter(acao=A.DADOS_EXPORTADOS, usuario=self.maria.usuario).exists())

    def test_registro_nao_pode_ser_alterado_nem_apagado_pela_aplicacao(self):
        r = registrar(A.PAPEL, detalhes={"x": 1})
        r.acao = A.LOGIN
        with self.assertRaises(RegistroImutavel):
            r.save()
        with self.assertRaises(RegistroImutavel):
            r.delete()
        with self.assertRaises(RegistroImutavel):
            RegistroAuditoria.objects.all().delete()
        with self.assertRaises(RegistroImutavel):
            RegistroAuditoria.objects.all().update(acao=A.LOGIN)

    def test_banco_recusa_update_e_delete_direto(self):
        if connection.vendor != "postgresql":
            self.skipTest("o trigger existe só no PostgreSQL")
        registrar(A.PAPEL)
        for sql in ("UPDATE registro_auditoria SET acao = 'LOGIN'", "DELETE FROM registro_auditoria"):
            with self.assertRaises(DatabaseError), transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(sql)

    def test_apagar_usuario_nao_mexe_na_trilha(self):
        u = User.objects.create_user("temporario", password="x")
        registrar(A.CRIAR, objeto=u)
        u.delete()  # com FK comum, isso tentaria um UPDATE na trilha
        self.assertTrue(RegistroAuditoria.objects.filter(objeto_nome="temporario").exists())

    def test_so_gestor_ve_a_trilha(self):
        self.client.force_login(self.maria.usuario)
        self.assertEqual(self.client.get(reverse("auditoria:lista")).status_code, 403)
        self.client.force_login(self.gestor)
        registrar(A.PAPEL, objeto=self.u_ana, detalhes={"Gestor": ["Não", "Sim"]})
        resp = self.client.get(reverse("auditoria:lista"))
        self.assertContains(resp, "Não → Sim")
