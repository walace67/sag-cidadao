"""
SAG-Cidadão — testes da API REST
Rode com:  python manage.py test apps.atendimento
"""
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from . import services
from .models import Cidadao, Solicitacao
from .tests import BaseSAG
from django.contrib.auth.models import User


class ApiTest(BaseSAG):
    def cliente(self, usuario=None):
        c = APIClient()
        if usuario is not None:
            token, _ = Token.objects.get_or_create(user=usuario)
            c.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
        return c

    def test_obter_token_com_usuario_e_senha(self):
        resp = APIClient().post("/api/token/", {"username": "maria", "password": "Teste@2026"})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("token", resp.json())

    def test_sem_token_responde_401(self):
        self.assertEqual(self.cliente().get("/api/solicitacoes/").status_code, 401)

    def test_cidadao_lista_so_as_proprias(self):
        self.nova()
        u_joao = User.objects.create_user("joao", password="x")
        Cidadao.objects.create(usuario=u_joao, cpf="11144477735", nome_completo="João", bairro=self.centro)
        resp = self.cliente(u_joao).get("/api/solicitacoes/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["count"], 0)

    def test_cidadao_cria_com_201_e_location(self):
        resp = self.cliente(self.maria.usuario).post("/api/solicitacoes/", {
            "categoria": self.buraco.pk, "bairro": self.aponia.pk,
            "endereco_referencia": "Rua A, 10", "descricao": "Buraco grande perto da escola.",
        }, format="json")
        self.assertEqual(resp.status_code, 201)
        self.assertIn("Location", resp.headers)
        self.assertEqual(resp.json()["status_codigo"], "ABE")

    def test_validacao_responde_400_por_campo(self):
        resp = self.cliente(self.maria.usuario).post("/api/solicitacoes/", {
            "categoria": self.buraco.pk, "bairro": self.aponia.pk,
            "endereco_referencia": "Rua A", "descricao": "curta",
        }, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("descricao", resp.json())

    def test_cliente_nao_consegue_forcar_status(self):
        resp = self.cliente(self.maria.usuario).post("/api/solicitacoes/", {
            "categoria": self.buraco.pk, "bairro": self.aponia.pk, "endereco_referencia": "Rua A",
            "descricao": "Buraco grande perto da escola.", "status": "CON", "prioridade": 3,
        }, format="json")
        self.assertEqual(resp.json()["status_codigo"], "ABE")  # mass assignment ignorado

    def test_servidor_muda_status_e_transicao_invalida_da_409(self):
        s = self.nova()
        c = self.cliente(self.u_ana)
        ok = c.post(f"/api/solicitacoes/{s.pk}/status/", {"novo_status": "ANA"}, format="json")
        self.assertEqual(ok.status_code, 200)
        conflito = c.post(f"/api/solicitacoes/{s.pk}/status/", {"novo_status": "CON"}, format="json")
        self.assertEqual(conflito.status_code, 409)

    def test_servidor_de_outra_secretaria_recebe_404(self):
        s = self.nova()  # SEMOB
        resp = self.cliente(self.u_carlos).get(f"/api/solicitacoes/{s.pk}/")  # Carlos é da SEMUSB
        self.assertEqual(resp.status_code, 404)

    def test_cidadao_nao_muda_status_403(self):
        s = self.nova()
        resp = self.cliente(self.maria.usuario).post(f"/api/solicitacoes/{s.pk}/status/", {"novo_status": "ANA"}, format="json")
        self.assertEqual(resp.status_code, 403)

    def test_cancelar_pela_api(self):
        s = self.nova()
        c = self.cliente(self.maria.usuario)
        self.assertEqual(c.post(f"/api/solicitacoes/{s.pk}/cancelar/", {"motivo": "Resolvido"}, format="json").status_code, 200)
        self.assertEqual(c.post(f"/api/solicitacoes/{s.pk}/cancelar/", {}, format="json").status_code, 409)

    def test_delete_e_put_nao_existem_405(self):
        s = self.nova()
        c = self.cliente(self.u_ana)
        self.assertEqual(c.delete(f"/api/solicitacoes/{s.pk}/").status_code, 405)
        self.assertEqual(c.put(f"/api/solicitacoes/{s.pk}/", {}, format="json").status_code, 405)
        self.assertTrue(Solicitacao.objects.filter(pk=s.pk).exists())

    def test_consulta_publica_sem_dados_pessoais(self):
        s = self.nova()
        resp = APIClient().get(f"/api/protocolo/{s.protocolo}/")
        self.assertEqual(resp.status_code, 200)
        corpo = resp.content.decode()
        self.assertNotIn("Maria", corpo)
        self.assertNotIn("52998224725", corpo)

    def test_detalhe_traz_historico(self):
        s = self.nova()
        services.alterar_status(solicitacao_id=s.pk, novo_status="ANA", usuario=self.u_ana)
        resp = self.cliente(self.u_ana).get(f"/api/solicitacoes/{s.pk}/")
        self.assertEqual(len(resp.json()["historico"]), 2)
