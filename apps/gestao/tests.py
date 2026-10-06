"""
SAG-Cidadão — testes do autocadastro e da área de gestão
Rode com:  python manage.py test apps
"""
from django.contrib.auth.models import User
from django.core import mail
from django.core.management import call_command
from django.urls import reverse

from apps.atendimento import services
from apps.atendimento.models import Bairro, CategoriaServico, Cidadao, Secretaria, Servidor, Solicitacao
from apps.atendimento.tests import BaseSAG
from apps.gestao.permissoes import grupo_gestor


class AutocadastroTest(BaseSAG):
    """Cadastro com confirmação por e-mail e resposta idêntica (anti-enumeração)."""

    def dados(self, **extra):
        d = {
            "nome_completo": "Paula Andrade", "cpf": "390.533.447-05", "email": "paula@exemplo.com",
            "telefone": "(69) 99999-0000", "bairro": self.centro.pk,
            "senha1": "Cidade#Limpa2026", "senha2": "Cidade#Limpa2026", "aceite": "on",
        }
        d.update(extra)
        return d

    def link_do_email(self):
        import re
        return re.search(r"https?://\S+", mail.outbox[-1].body).group(0)

    def test_cadastro_cria_conta_inativa_e_envia_link(self):
        resp = self.client.post(reverse("atendimento:cadastro"), self.dados())
        self.assertContains(resp, "Confira seu e-mail")
        c = Cidadao.objects.get(cpf="39053344705")
        self.assertFalse(c.usuario.is_active)       # só ativa após confirmar
        self.assertTrue(c.pendente)
        # Senha guardada como hash, nunca em texto puro (nos testes o
        # algoritmo é MD5 só por velocidade; em produção é PBKDF2)
        self.assertNotIn(self.dados()["senha1"], c.usuario.password)
        self.assertTrue(c.usuario.check_password(self.dados()["senha1"]))
        self.assertEqual(mail.outbox[-1].to, ["paula@exemplo.com"])
        self.assertNotIn("_auth_user_id", self.client.session)  # não entrou ainda

    def test_link_ativa_loga_e_so_vale_uma_vez(self):
        self.client.post(reverse("atendimento:cadastro"), self.dados())
        link = self.link_do_email()
        resp = self.client.get(link)
        self.assertRedirects(resp, reverse("atendimento:minhas"))
        c = Cidadao.objects.get(cpf="39053344705")
        self.assertTrue(c.usuario.is_active)
        self.assertIsNotNone(c.email_confirmado_em)
        self.client.logout()
        self.assertEqual(self.client.get(link).status_code, 400)  # uso único

    def test_cpf_existente_recebe_a_mesma_resposta(self):
        """Anti-enumeração: CPF da Maria (já cadastrado) gera a MESMA tela."""
        self.maria.usuario.email = "maria@exemplo.com"
        self.maria.usuario.save()
        novo = self.client.post(reverse("atendimento:cadastro"), self.dados())
        mail.outbox.clear()
        repetido = self.client.post(reverse("atendimento:cadastro"), self.dados(
            cpf="529.982.247-25", email="atacante@exemplo.com"))
        self.assertEqual(novo.status_code, repetido.status_code)
        self.assertContains(repetido, "Confira seu e-mail")
        self.assertEqual(Cidadao.objects.filter(cpf="52998224725").count(), 1)  # nada criado
        # O aviso vai para o e-mail JÁ cadastrado, nunca para quem tentou
        self.assertEqual(mail.outbox[-1].to, ["maria@exemplo.com"])
        self.assertIn("Tentativa de cadastro", mail.outbox[-1].subject)

    def test_pendente_e_substituido_e_nao_sequestra_cpf(self):
        self.client.post(reverse("atendimento:cadastro"), self.dados(email="intruso@exemplo.com"))
        self.client.post(reverse("atendimento:cadastro"), self.dados(email="dona@exemplo.com"))
        c = Cidadao.objects.get(cpf="39053344705")
        self.assertEqual(c.usuario.email, "dona@exemplo.com")
        self.assertEqual(User.objects.filter(username="39053344705").count(), 1)

    def test_validacoes_que_nao_revelam_nada(self):
        r1 = self.client.post(reverse("atendimento:cadastro"), self.dados(cpf="123.456.789-00"))
        self.assertContains(r1, "CPF inválido")  # regra matemática, vale para qualquer um
        r2 = self.client.post(reverse("atendimento:cadastro"), self.dados(senha1="12345678", senha2="12345678"))
        self.assertContains(r2, "inteiramente numérica")
        d = self.dados()
        d.pop("aceite")
        self.assertContains(self.client.post(reverse("atendimento:cadastro"), d), "aviso de privacidade")

    def test_limpeza_de_pendentes(self):
        from datetime import timedelta
        from django.utils import timezone
        self.client.post(reverse("atendimento:cadastro"), self.dados())
        User.objects.filter(username="39053344705").update(date_joined=timezone.now() - timedelta(hours=30))
        call_command("limpar_cadastros_pendentes", verbosity=0)
        self.assertFalse(Cidadao.objects.filter(cpf="39053344705").exists())
        self.assertTrue(Cidadao.objects.filter(pk=self.maria.pk).exists())  # cadastro antigo intacto

    def test_login_com_cpf_formatado_apos_ativar(self):
        self.client.post(reverse("atendimento:cadastro"), self.dados())
        self.client.get(self.link_do_email())
        self.client.logout()
        resp = self.client.post(reverse("login"), {"username": "390.533.447-05", "password": "Cidade#Limpa2026"})
        self.assertEqual(resp.status_code, 302)


class ProtecoesTest(BaseSAG):
    """Limite de tentativas, bloqueio de login, recuperação de senha e LGPD."""

    def test_limite_de_cadastros_por_ip(self):
        for _ in range(5):
            self.client.post(reverse("atendimento:cadastro"), {})
        resp = self.client.post(reverse("atendimento:cadastro"), {})
        self.assertEqual(resp.status_code, 429)
        self.assertIn("Retry-After", resp.headers)

    def test_bloqueio_apos_cinco_senhas_erradas(self):
        for _ in range(5):
            self.client.post(reverse("login"), {"username": "maria", "password": "errada"})
        # Mesmo com a senha CERTA, fica bloqueado por 15 minutos
        resp = self.client.post(reverse("login"), {"username": "maria", "password": "Teste@2026"})
        self.assertEqual(resp.status_code, 429)
        self.assertContains(resp, "Muitas tentativas", status_code=429)

    def test_bloqueio_vale_para_login_inexistente(self):
        """Senão, o bloqueio revelaria quais logins existem."""
        for _ in range(5):
            self.client.post(reverse("login"), {"username": "naoexiste", "password": "x"})
        resp = self.client.post(reverse("login"), {"username": "naoexiste", "password": "x"})
        self.assertEqual(resp.status_code, 429)

    def test_redefinir_senha_responde_igual(self):
        r1 = self.client.post(reverse("password_reset"), {"email": "naoexiste@exemplo.com"})
        self.maria.usuario.email = "maria@exemplo.com"
        self.maria.usuario.save()
        r2 = self.client.post(reverse("password_reset"), {"email": "maria@exemplo.com"})
        self.assertEqual(r1.status_code, r2.status_code)
        self.assertEqual(r1.url, r2.url)
        self.assertEqual(len(mail.outbox), 1)  # só quem existe recebe

    def test_api_token_limitado(self):
        from rest_framework.test import APIClient
        c = APIClient()
        codigos = [c.post("/api/token/", {"username": "maria", "password": "x"}).status_code for _ in range(11)]
        self.assertEqual(codigos[-1], 429)

    def test_meus_dados_corrige_e_exporta(self):
        self.client.force_login(self.maria.usuario)
        self.assertContains(self.client.get(reverse("atendimento:meus_dados")), "***.982.247-**")
        self.client.post(reverse("atendimento:meus_dados"), {"telefone": "(69) 98888-7777", "bairro": self.centro.pk})
        self.maria.refresh_from_db()
        self.assertEqual(self.maria.telefone, "69988887777")
        self.nova()
        resp = self.client.get(reverse("atendimento:exportar_dados"))
        self.assertEqual(resp["Content-Type"], "application/json; charset=utf-8")
        dados = resp.json()
        self.assertEqual(dados["titular"]["cpf"], "52998224725")
        self.assertEqual(len(dados["solicitacoes"]), 1)


class GestaoTest(BaseSAG):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.u_gestor = User.objects.create_user("gestora", password="Teste@2026", first_name="Gina")
        cls.u_gestor.groups.add(grupo_gestor())

    def entrar(self, usuario):
        self.client.force_login(usuario)

    def test_so_gestor_acessa_a_gestao(self):
        url = reverse("gestao:dashboard")
        self.assertEqual(self.client.get(url).status_code, 302)  # anônimo -> login
        self.entrar(self.u_ana)
        self.assertEqual(self.client.get(url).status_code, 403)  # servidor
        self.entrar(self.maria.usuario)
        self.assertEqual(self.client.get(url).status_code, 403)  # cidadão
        self.entrar(self.u_gestor)
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_dashboard_com_consultas_constantes(self):
        self.entrar(self.u_gestor)
        for _ in range(3):
            self.nova()
        self.client.get(reverse("gestao:dashboard"))
        with self.assertNumQueries(11):
            self.client.get(reverse("gestao:dashboard"))
        for _ in range(10):
            self.nova()
        with self.assertNumQueries(11):  # não cresce com o volume de dados
            resp = self.client.get(reverse("gestao:dashboard"))
        self.assertEqual(resp.context["k"]["total"], 13)

    def test_crud_generico_e_exclusao_protegida(self):
        self.entrar(self.u_gestor)
        self.client.post(reverse("gestao:cadastro_novo", args=["bairros"]), {"nome": "Embratel", "zona": "SUL"})
        self.assertTrue(Bairro.objects.filter(nome="Embratel").exists())
        # Bairro Aponiã tem moradora (Maria): PROTECT impede a exclusão
        resp = self.client.post(reverse("gestao:cadastro_excluir", args=["bairros", self.aponia.pk]), follow=True)
        self.assertContains(resp, "Não foi possível excluir")
        self.assertTrue(Bairro.objects.filter(pk=self.aponia.pk).exists())
        self.assertEqual(self.client.get("/gestao/cadastros/inexistente/").status_code, 404)

    def test_cria_servidor_com_login_e_papel_gestor(self):
        self.entrar(self.u_gestor)
        resp = self.client.post(reverse("gestao:servidor_novo"), {
            "first_name": "Rui", "last_name": "Matos", "email": "rui@pvh.gov.br", "username": "rui.matos",
            "matricula": "2026099", "secretaria": self.semusb.pk, "senha": "Prefeitura#2026", "gestor": "on",
        })
        self.assertRedirects(resp, reverse("gestao:servidores"))
        s = Servidor.objects.get(matricula="2026099")
        self.assertTrue(s.usuario.check_password("Prefeitura#2026"))
        self.assertTrue(s.usuario.groups.filter(name="Gestor").exists())

    def test_desativar_servidor_bloqueia_login(self):
        self.entrar(self.u_gestor)
        self.client.post(reverse("gestao:servidor_alternar", args=[self.ana.pk]))
        self.u_ana.refresh_from_db()
        self.assertFalse(self.u_ana.is_active)
        self.client.logout()
        self.assertFalse(self.client.login(username="ana", password="Teste@2026"))

    def test_gestor_ve_todas_altera_prioridade_mas_nao_status(self):
        s = self.nova(categoria=self.luz)  # SEMUSB
        self.entrar(self.u_gestor)
        self.assertContains(self.client.get(reverse("atendimento:painel")), "SEMUSB")
        url = reverse("atendimento:detalhe", args=[s.pk])
        self.client.post(url, {"acao": "prioridade", "prioridade": 3})
        s.refresh_from_db()
        self.assertEqual(s.prioridade, 3)
        self.assertIn("Prioridade alterada", s.historico.last().observacao)
        self.assertEqual(self.client.post(url, {"acao": "status", "novo_status": "ANA"}).status_code, 403)

    def test_popular_demo_e_limpar(self):
        call_command("popular_demo", quantidade=20, verbosity=0)
        self.assertEqual(Solicitacao.objects.filter(cidadao__usuario__email__endswith="@demo.sag").count(), 20)
        call_command("popular_demo", limpar=True, verbosity=0)
        self.assertFalse(User.objects.filter(email__endswith="@demo.sag").exists())
        self.assertTrue(Cidadao.objects.filter(pk=self.maria.pk).exists())  # dados reais intactos
