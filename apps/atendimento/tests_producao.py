"""
SAG-Cidadão — testes da preparação para produção (Etapa 3)
App: atendimento/tests_producao.py

    python manage.py test apps.atendimento.tests_producao
"""
import re
import uuid
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.core.cache import cache
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from . import seguranca


class SaudeTest(TestCase):
    def test_ok_quando_banco_responde(self):
        resp = self.client.get(reverse("saude"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"status": "ok", "banco": "ok"})
        self.assertIn("no-cache", resp["Cache-Control"])  # monitor nunca vê resposta velha

    def test_503_quando_banco_cai_sem_vazar_detalhes(self):
        with mock.patch("apps.atendimento.saude.connection.cursor", side_effect=Exception("senha errada p/ sag")):
            resp = self.client.get(reverse("saude"))
        self.assertEqual(resp.status_code, 503)
        self.assertNotIn("senha", resp.content.decode())  # o detalhe vai só para o log

    def test_so_aceita_get(self):
        self.assertEqual(self.client.post(reverse("saude")).status_code, 405)


class CabecalhosTest(TestCase):
    def test_cabecalhos_de_seguranca(self):
        resp = self.client.get(reverse("login"))
        self.assertEqual(resp["X-Frame-Options"], "DENY")
        self.assertEqual(resp["X-Content-Type-Options"], "nosniff")
        self.assertEqual(resp["Referrer-Policy"], "same-origin")

    def test_csp_com_nonce_igual_ao_do_script(self):
        resp = self.client.get(reverse("login"))
        politica = resp["Content-Security-Policy"]
        self.assertIn("object-src 'none'", politica)
        self.assertIn("frame-ancestors 'none'", politica)
        nonce = re.search(r"'nonce-([^']+)'", politica).group(1)
        # O script legítimo da página carrega o mesmo nonce do cabeçalho
        self.assertContains(resp, f'<script nonce="{nonce}">')

    def test_nonce_muda_a_cada_resposta(self):
        n1 = re.search(r"nonce-([^']+)", self.client.get(reverse("login"))["Content-Security-Policy"]).group(1)
        n2 = re.search(r"nonce-([^']+)", self.client.get(reverse("login"))["Content-Security-Policy"]).group(1)
        self.assertNotEqual(n1, n2)

    def test_templates_sem_javascript_inline(self):
        """onclick/onsubmit/onchange e <script> sem nonce seriam bloqueados pela CSP."""
        raiz = Path(settings.BASE_DIR) / "apps"
        proibidos = re.compile(r"\son(click|submit|change|load|input|keyup|keydown)=|<script>", re.I)
        problemas = [
            str(arq.relative_to(raiz)) for arq in raiz.rglob("templates/**/*.html")
            if proibidos.search(arq.read_text(encoding="utf-8"))
        ]
        self.assertEqual(problemas, [])

    def test_pagina_404_propria(self):
        resp = self.client.get("/nao-existe/")
        self.assertEqual(resp.status_code, 404)
        self.assertContains(resp, "Página não encontrada", status_code=404)


class ProxyTest(TestCase):
    def setUp(self):
        cache.clear()
        self.rf = RequestFactory()

    def test_sem_proxy_confiavel_ignora_x_forwarded_for(self):
        req = self.rf.get("/", REMOTE_ADDR="203.0.113.9", HTTP_X_FORWARDED_FOR="1.2.3.4")
        self.assertEqual(seguranca.ip_do_cliente(req), "203.0.113.9")

    @override_settings(CONFIAR_PROXY=True)
    def test_com_proxy_usa_o_ultimo_endereco(self):
        # O cliente forjou "1.2.3.4"; o Nginx acrescentou o IP real no final
        req = self.rf.get("/", REMOTE_ADDR="127.0.0.1", HTTP_X_FORWARDED_FOR="1.2.3.4, 203.0.113.9")
        self.assertEqual(seguranca.ip_do_cliente(req), "203.0.113.9")

    def test_api_nao_se_engana_com_x_forwarded_for_forjado(self):
        """Com o padrão do DRF (NUM_PROXIES=None), trocar o cabeçalho a cada
        requisição furaria o limite. Configurado, o limite vale por IP real."""
        url = reverse("api-protocolo", args=[uuid.uuid4()])
        codigos = [
            self.client.get(url, HTTP_X_FORWARDED_FOR=f"10.0.0.{i}").status_code for i in range(31)
        ]
        self.assertEqual(codigos[-1], 429)


class LogSegurancaTest(TestCase):
    def setUp(self):
        cache.clear()

    def test_bloqueio_vai_para_o_log_sem_cpf(self):
        with self.assertLogs("sag.seguranca", level="WARNING") as registro:
            for _ in range(6):
                self.client.post(reverse("login"), {"username": "529.982.247-25", "password": "SenhaSecreta#987"})
        texto = "\n".join(registro.output)
        self.assertIn("bloquead", texto)
        self.assertNotIn("52998224725", texto)  # LGPD: CPF não vai para o log
        self.assertNotIn("SenhaSecreta#987", texto)       # senha jamais
