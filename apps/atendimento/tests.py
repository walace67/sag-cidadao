"""
SAG-Cidadão — testes automatizados
App: atendimento/tests.py

Rode com:  python manage.py test apps.atendimento

O Django cria um banco de TESTE vazio, roda cada teste dentro de uma
transação e desfaz tudo ao final (ROLLBACK). Seus dados reais não são tocados.
"""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from . import services
from .models import (
    AreaAtuacao, Bairro, CategoriaServico, Cidadao, HistoricoSolicitacao,
    Secretaria, Servidor, Solicitacao,
)


class BaseSAG(TestCase):
    """Cria o mesmo cenário que você montou no admin."""

    def setUp(self):
        # Os contadores de tentativas ficam no cache: zera entre os testes
        from django.core.cache import cache
        cache.clear()

    @classmethod
    def setUpTestData(cls):
        cls.semob = Secretaria.objects.create(sigla="SEMOB", nome="Obras")
        cls.semusb = Secretaria.objects.create(sigla="SEMUSB", nome="Serviços Básicos")
        cls.aponia = Bairro.objects.create(nome="Aponiã", zona=Bairro.Zona.NORTE)
        cls.centro = Bairro.objects.create(nome="Centro", zona=Bairro.Zona.CENTRO)
        AreaAtuacao.objects.create(secretaria=cls.semob, bairro=cls.aponia, data_inicio="2026-01-01")
        cls.buraco = CategoriaServico.objects.create(secretaria=cls.semob, nome="Tapa-buraco", prazo_dias=30)
        cls.luz = CategoriaServico.objects.create(secretaria=cls.semusb, nome="Iluminação", prazo_dias=10)

        u_maria = User.objects.create_user("maria", password="Teste@2026", first_name="Maria")
        cls.maria = Cidadao.objects.create(
            usuario=u_maria, cpf="52998224725", nome_completo="Maria da Silva", bairro=cls.aponia
        )
        cls.u_ana = User.objects.create_user("ana", password="Teste@2026", first_name="Ana")
        cls.ana = Servidor.objects.create(usuario=cls.u_ana, matricula="2026001", secretaria=cls.semob)
        cls.u_carlos = User.objects.create_user("carlos", password="Teste@2026", first_name="Carlos")
        cls.carlos = Servidor.objects.create(usuario=cls.u_carlos, matricula="2026002", secretaria=cls.semusb)

    def nova(self, categoria=None):
        return services.abrir_solicitacao(
            cidadao=self.maria,
            categoria=categoria or self.buraco,
            bairro=self.aponia,
            descricao="Buraco grande no meio da pista.",
            endereco_referencia="Rua das Flores, 320",
        )


class ServicosTest(BaseSAG):
    def test_abrir_cria_historico(self):
        s = self.nova()
        self.assertEqual(s.status, "ABE")
        self.assertEqual(s.historico.count(), 1)

    def test_fluxo_completo_ate_conclusao(self):
        s = self.nova()
        for novo in ["ANA", "EXE", "CON"]:
            s = services.alterar_status(solicitacao_id=s.pk, novo_status=novo, usuario=self.u_ana)
        self.assertEqual(s.status, "CON")
        self.assertIsNotNone(s.concluida_em)  # coerente com o CHECK do banco
        self.assertEqual(s.historico.count(), 4)

    def test_transicao_invalida_nao_grava_nada(self):
        s = self.nova()
        with self.assertRaises(services.TransicaoInvalida):
            services.alterar_status(solicitacao_id=s.pk, novo_status="CON", usuario=self.u_ana)
        s.refresh_from_db()
        self.assertEqual(s.status, "ABE")
        self.assertEqual(s.historico.count(), 1)  # nenhum histórico extra

    def test_relatorio_agrupa_por_zona(self):
        self.nova()
        self.nova()
        linhas, totais, total = services.relatorio_por_zona(self.semob)
        norte = next(l for l in linhas if l["zona"] == "Zona Norte")
        self.assertEqual(norte["total"], 2)
        self.assertEqual(total, 2)


class ViewsTest(BaseSAG):
    def test_painel_exige_login(self):
        resp = self.client.get(reverse("atendimento:painel"))
        self.assertEqual(resp.status_code, 302)  # redireciona para o login

    def test_cidadao_nao_entra_no_painel(self):
        self.client.login(username="maria", password="Teste@2026")
        resp = self.client.get(reverse("atendimento:painel"))
        self.assertEqual(resp.status_code, 403)  # autenticado, mas sem autorização

    def test_servidor_so_ve_a_propria_secretaria(self):
        da_semusb = self.nova(categoria=self.luz)
        self.client.login(username="ana", password="Teste@2026")  # Ana é da SEMOB
        resp = self.client.get(reverse("atendimento:detalhe", args=[da_semusb.pk]))
        self.assertEqual(resp.status_code, 404)  # IDOR bloqueado

    def test_painel_sem_n_mais_1(self):
        for _ in range(5):
            self.nova()
        self.client.login(username="ana", password="Teste@2026")
        self.client.get(reverse("atendimento:painel"))  # aquece a sessão
        # Com select_related, o número de consultas NÃO cresce com a lista.
        # As 8 consultas: sessão, usuário, papel Gestor (RBAC), servidor,
        # secretaria, COUNT da paginação, a lista (um único SELECT com 6 JOINs)
        # e os bairros do filtro. Sem select_related seriam 8 + 4 por linha.
        with self.assertNumQueries(8):
            self.client.get(reverse("atendimento:painel"))
        for _ in range(10):
            self.nova()
        with self.assertNumQueries(8):
            self.client.get(reverse("atendimento:painel"))

    def test_alterar_status_pela_tela(self):
        s = self.nova()
        self.client.login(username="ana", password="Teste@2026")
        resp = self.client.post(
            reverse("atendimento:detalhe", args=[s.pk]), {"acao": "status", "novo_status": "ANA", "observacao": "Vistoria"}
        )
        self.assertEqual(resp.status_code, 302)  # PRG
        s.refresh_from_db()
        self.assertEqual(s.status, "ANA")
        self.assertEqual(s.responsavel, self.ana)

    def test_cidadao_abre_solicitacao(self):
        self.client.login(username="maria", password="Teste@2026")
        resp = self.client.post(reverse("atendimento:nova"), {
            "categoria": self.buraco.pk, "bairro": self.aponia.pk,
            "endereco_referencia": "Rua A, 10", "descricao": "Poste caído atravessando a calçada.",
        })
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(Solicitacao.objects.filter(cidadao=self.maria).count(), 1)

    def test_consulta_publica_nao_expoe_dados_pessoais(self):
        s = self.nova()
        resp = self.client.get(reverse("atendimento:consulta"), {"protocolo": str(s.protocolo)})
        self.assertContains(resp, "Tapa-buraco")
        self.assertNotContains(resp, "Maria da Silva")
        self.assertNotContains(resp, "52998224725")

    def test_paginas_renderizam(self):
        s = self.nova()
        self.client.login(username="ana", password="Teste@2026")
        for nome, args in [("painel", []), ("detalhe", [s.pk]), ("relatorio", [])]:
            self.assertEqual(self.client.get(reverse(f"atendimento:{nome}", args=args)).status_code, 200)
        self.client.logout()
        self.client.login(username="maria", password="Teste@2026")
        for nome in ["minhas", "nova"]:
            self.assertEqual(self.client.get(reverse(f"atendimento:{nome}")).status_code, 200)


class CancelamentoTest(BaseSAG):
    """Passo 1: cancelamento pelo cidadão."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        u_joao = User.objects.create_user("joao", password="Teste@2026")
        cls.joao = Cidadao.objects.create(
            usuario=u_joao, cpf="11144477735", nome_completo="João Souza", bairro=cls.centro
        )

    def url(self, s):
        return reverse("atendimento:cancelar", args=[s.pk])

    def test_dono_cancela_solicitacao_aberta(self):
        s = self.nova()
        self.client.login(username="maria", password="Teste@2026")
        resp = self.client.post(self.url(s))
        self.assertEqual(resp.status_code, 302)  # PRG
        s.refresh_from_db()
        self.assertEqual(s.status, "CAN")
        self.assertEqual(s.historico.last().status_novo, "CAN")

    def test_nao_cancela_depois_da_analise(self):
        s = self.nova()
        services.alterar_status(solicitacao_id=s.pk, novo_status="ANA", usuario=self.u_ana)
        self.client.login(username="maria", password="Teste@2026")
        self.client.post(self.url(s))
        s.refresh_from_db()
        self.assertEqual(s.status, "ANA")  # regra de negócio barrou
        self.assertEqual(s.historico.count(), 2)  # nada foi gravado

    def test_outro_cidadao_recebe_404(self):
        s = self.nova()  # da Maria
        self.client.login(username="joao", password="Teste@2026")
        resp = self.client.post(self.url(s))
        self.assertEqual(resp.status_code, 404)  # IDOR bloqueado
        s.refresh_from_db()
        self.assertEqual(s.status, "ABE")

    def test_get_nao_cancela(self):
        s = self.nova()
        self.client.login(username="maria", password="Teste@2026")
        resp = self.client.get(self.url(s))
        self.assertEqual(resp.status_code, 405)  # Method Not Allowed
        s.refresh_from_db()
        self.assertEqual(s.status, "ABE")

    def test_servidor_nao_ve_opcao_cancelar(self):
        opcoes = [codigo for codigo, _ in services.proximos_status("ABE")]
        self.assertNotIn("CAN", opcoes)

    def test_cancelada_e_estado_final(self):
        s = self.nova()
        services.cancelar_pelo_cidadao(solicitacao_id=s.pk, cidadao=self.maria)
        with self.assertRaises(services.TransicaoInvalida):
            services.alterar_status(solicitacao_id=s.pk, novo_status="ANA", usuario=self.u_ana)

    def test_lista_mostra_data_de_encerramento(self):
        aberta = self.nova()
        cancelada = self.nova()
        services.cancelar_pelo_cidadao(solicitacao_id=cancelada.pk, cidadao=self.maria)
        concluida = self.nova()
        for novo in ["ANA", "EXE", "CON"]:
            services.alterar_status(solicitacao_id=concluida.pk, novo_status=novo, usuario=self.u_ana)

        por_id = {s.pk: s for s in services.solicitacoes_do_cidadao(self.maria)}
        self.assertIsNone(por_id[aberta.pk].encerrada_em)          # ainda aberta
        self.assertIsNotNone(por_id[cancelada.pk].encerrada_em)    # veio do histórico
        self.assertIsNone(por_id[cancelada.pk].concluida_em)       # o CHECK exige vazio
        self.assertIsNotNone(por_id[concluida.pk].concluida_em)

        self.client.login(username="maria", password="Teste@2026")
        resp = self.client.get(reverse("atendimento:minhas"))
        self.assertContains(resp, "Encerrada em")
