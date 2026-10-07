"""
Testes do login gov.br com um provedor SIMULADO: uma chave RSA gerada
aqui assina os id_tokens, exatamente como o gov.br faria. Nenhum acesso
à internet.
"""
import base64
import hashlib
import json
import time
import urllib.parse
from unittest import mock

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import override_settings
from django.urls import reverse

from apps.atendimento.models import Cidadao
from apps.atendimento.tests import BaseSAG
from apps.auditoria.models import RegistroAuditoria

from . import oidc

CHAVE = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OUTRA_CHAVE = rsa.generate_private_key(public_exponent=65537, key_size=2048)
JWK = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(CHAVE.public_key()))
JWK.update({"kid": "chave-teste", "alg": "RS256", "use": "sig"})
EMISSOR = "https://sso.staging.acesso.gov.br/"
CPF_NOVO = "39053344705"


def id_token(nonce, cpf=CPF_NOVO, chave=CHAVE, aud="sag-teste", iss=EMISSOR, expira_em=300, **extra):
    agora = int(time.time())
    claims = {"sub": cpf, "aud": aud, "iss": iss, "iat": agora, "exp": agora + expira_em, "nonce": nonce,
              "name": "Paula Andrade", "email": "paula@exemplo.com", "email_verified": True, **extra}
    return jwt.encode(claims, chave, algorithm="RS256", headers={"kid": "chave-teste"})


@override_settings(GOVBR_CLIENT_ID="sag-teste", GOVBR_CLIENT_SECRET="segredo", GOVBR_AMBIENTE="homologacao")
class LoginGovbrTest(BaseSAG):
    def setUp(self):
        super().setUp()
        cache.set("govbr:jwks", {"keys": [JWK]}, 3600)

    def iniciar(self):
        resp = self.client.get(reverse("govbr:entrar"))
        url = urllib.parse.urlparse(resp["Location"])
        return resp, dict(urllib.parse.parse_qsl(url.query)), self.client.session["govbr_pedido"]

    def voltar(self, pedido, token, state=None):
        with mock.patch.object(oidc, "trocar_code", return_value={"id_token": token}) as troca:
            resp = self.client.get(reverse("govbr:retorno"), {"code": "abc", "state": state or pedido["state"]})
        return resp, troca

    def test_redireciona_para_o_gov_br_com_pkce(self):
        resp, params, pedido = self.iniciar()
        self.assertTrue(resp["Location"].startswith("https://sso.staging.acesso.gov.br/authorize?"))
        self.assertEqual(params["code_challenge_method"], "S256")
        esperado = base64.urlsafe_b64encode(hashlib.sha256(pedido["verifier"].encode()).digest()).rstrip(b"=").decode()
        self.assertEqual(params["code_challenge"], esperado)       # o verifier NUNCA vai na URL
        self.assertNotIn(pedido["verifier"], resp["Location"])
        self.assertIn("openid", params["scope"])

    def test_primeiro_acesso_cria_conta_confirmada(self):
        _, _, pedido = self.iniciar()
        resp, troca = self.voltar(pedido, id_token(pedido["nonce"]))
        self.assertRedirects(resp, reverse("govbr:completar"), fetch_redirect_response=False)
        self.assertEqual(troca.call_args.args[1], pedido["verifier"])  # PKCE: o verifier vai na troca
        resp = self.client.post(reverse("govbr:completar"), {"bairro": self.centro.pk, "aceite": "on"})
        c = Cidadao.objects.get(cpf=CPF_NOVO)
        self.assertTrue(c.usuario.is_active)
        self.assertIsNotNone(c.email_confirmado_em)
        self.assertFalse(c.usuario.has_usable_password())          # sem senha local
        self.assertEqual(int(self.client.session["_auth_user_id"]), c.usuario.pk)
        self.assertTrue(RegistroAuditoria.objects.filter(acao="CRIAR", detalhes__origem="conta gov.br").exists())

    def test_cidadao_existente_entra_direto(self):
        _, _, pedido = self.iniciar()
        resp, _ = self.voltar(pedido, id_token(pedido["nonce"], cpf=self.maria.cpf))
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.maria.usuario.pk)

    def test_state_diferente_e_recusado(self):
        _, _, pedido = self.iniciar()
        resp, troca = self.voltar(pedido, id_token(pedido["nonce"]), state="forjado")
        self.assertRedirects(resp, reverse("login"), fetch_redirect_response=False)
        troca.assert_not_called()                                  # nem chegou a falar com o gov.br
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_tokens_invalidos_sao_recusados(self):
        casos = {
            "assinado por outra chave": lambda n: id_token(n, chave=OUTRA_CHAVE),
            "nonce de outro login": lambda n: id_token("outro-nonce"),
            "emitido para outro sistema": lambda n: id_token(n, aud="outro-sistema"),
            "emissor falso": lambda n: id_token(n, iss="https://falso.example/"),
            "vencido": lambda n: id_token(n, expira_em=-600),
            "sub que não é CPF": lambda n: id_token(n, cpf="12345678900"),
        }
        for nome, gerar in casos.items():
            with self.subTest(nome):
                self.client.logout()
                _, _, pedido = self.iniciar()
                self.voltar(pedido, gerar(pedido["nonce"]))
                self.assertNotIn("_auth_user_id", self.client.session)
                self.assertFalse(Cidadao.objects.filter(cpf=CPF_NOVO).exists())

    def test_algoritmo_none_e_recusado(self):
        _, _, pedido = self.iniciar()
        sem_assinatura = jwt.encode({"sub": CPF_NOVO, "aud": "sag-teste", "iss": EMISSOR, "nonce": pedido["nonce"],
                                     "iat": int(time.time()), "exp": int(time.time()) + 300}, None, algorithm="none",
                                    headers={"kid": "chave-teste"})
        self.voltar(pedido, sem_assinatura)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_retorno_nao_pode_ser_reaproveitado(self):
        _, _, pedido = self.iniciar()
        token = id_token(pedido["nonce"], cpf=self.maria.cpf)
        self.voltar(pedido, token)
        self.client.logout()
        self.voltar(pedido, token)                                  # mesmo state/nonce de novo
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_cpf_bloqueado_nao_entra(self):
        u = self.maria.usuario
        u.is_active = False
        u.save()
        _, _, pedido = self.iniciar()
        self.voltar(pedido, id_token(pedido["nonce"], cpf=self.maria.cpf))
        self.assertNotIn("_auth_user_id", self.client.session)


class DesligadoTest(BaseSAG):
    def test_sem_credenciais_o_botao_nao_aparece(self):
        self.assertNotContains(self.client.get(reverse("login")), "Entrar com gov.br")
        self.assertEqual(self.client.get(reverse("govbr:entrar")).status_code, 404)
