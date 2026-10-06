"""
Testes da verificação em duas etapas.
    python manage.py test apps.doisfatores
"""
import time

import pyotp
from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from apps.atendimento.tests import BaseSAG
from apps.auditoria.models import RegistroAuditoria
from apps.gestao.permissoes import grupo_gestor

from . import servicos
from .models import DispositivoTOTP


def ativar_2fa(usuario):
    """Configura o aplicativo como o usuário faria; devolve (segredo, códigos)."""
    dispositivo, segredo = servicos.iniciar_configuracao(usuario)
    codigos = servicos.confirmar(dispositivo, pyotp.TOTP(segredo).now())
    return segredo, codigos


def proximo_codigo(segredo):
    # O código atual já foi "gasto" na confirmação (anti-repetição);
    # o do próximo intervalo de 30 s ainda vale (tolerância de 1 passo).
    return pyotp.TOTP(segredo).at(time.time() + 30)


class LoginDuasEtapasTest(BaseSAG):
    def setUp(self):
        super().setUp()
        self.segredo, self.codigos = ativar_2fa(self.u_ana)

    def entrar_com_senha(self):
        return self.client.post(reverse("login"), {"username": "ana", "password": "Teste@2026"})

    def test_senha_certa_ainda_nao_autentica(self):
        resp = self.entrar_com_senha()
        self.assertRedirects(resp, reverse("doisfatores:verificar"), fetch_redirect_response=False)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_codigo_certo_completa_o_login(self):
        self.entrar_com_senha()
        resp = self.client.post(reverse("doisfatores:verificar"), {"codigo": proximo_codigo(self.segredo)})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.u_ana.pk)
        self.assertEqual(self.client.get(reverse("atendimento:painel")).status_code, 200)

    def test_codigo_nao_vale_duas_vezes(self):
        dispositivo = servicos.dispositivo_ativo(self.u_ana)
        codigo = proximo_codigo(self.segredo)
        self.assertTrue(servicos.verificar_totp(dispositivo, codigo))
        dispositivo.refresh_from_db()
        self.assertFalse(servicos.verificar_totp(dispositivo, codigo))  # replay

    def test_codigo_de_recuperacao_funciona_uma_vez(self):
        self.entrar_com_senha()
        self.client.post(reverse("doisfatores:verificar"), {"codigo": self.codigos[0]})
        self.assertIn("_auth_user_id", self.client.session)
        self.assertEqual(servicos.codigos_restantes(self.u_ana), 9)
        self.assertFalse(servicos.usar_codigo_recuperacao(self.u_ana, self.codigos[0]))

    def test_cinco_codigos_errados_voltam_para_a_senha(self):
        self.entrar_com_senha()
        for _ in range(5):
            resp = self.client.post(reverse("doisfatores:verificar"), {"codigo": "000000"})
        self.assertRedirects(resp, reverse("login"), fetch_redirect_response=False)
        self.assertNotIn("2fa_pendente", self.client.session)
        self.assertEqual(RegistroAuditoria.objects.filter(acao="2FA", detalhes__evento="código recusado").count(), 5)

    def test_entrar_por_outro_caminho_nao_pula_a_segunda_etapa(self):
        self.client.login(username="ana", password="Teste@2026")  # login sem a tela do sistema
        resp = self.client.get(reverse("atendimento:painel"))
        self.assertRedirects(resp, reverse("login"), fetch_redirect_response=False)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_admin_usa_a_tela_de_login_do_sistema(self):
        resp = self.client.get("/admin/login/?next=/admin/")
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp["Location"].startswith(reverse("login")))

    def test_qr_code_escala_sem_cortar(self):
        """Sem viewBox, o CSS cortava as bordas do QR e o celular não lia."""
        svg = servicos.qr_svg(servicos.dispositivo_ativo(self.u_ana))
        self.assertIn("viewBox", svg)

    def test_segredo_fica_cifrado_no_banco(self):
        d = DispositivoTOTP.objects.get(usuario=self.u_ana, confirmado_em__isnull=False)
        self.assertNotIn(self.segredo, d.segredo_cifrado)
        self.assertEqual(servicos.segredo_de(d), self.segredo)

    def test_banco_aceita_um_so_dispositivo_confirmado(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            DispositivoTOTP.objects.create(usuario=self.u_ana, segredo_cifrado="x", confirmado_em=timezone.now())

    def test_token_da_api_exige_o_codigo(self):
        url = reverse("api-token")
        sem = self.client.post(url, {"username": "ana", "password": "Teste@2026"})
        self.assertEqual(sem.status_code, 400)
        self.assertIn("codigo", sem.json())
        com = self.client.post(url, {"username": "ana", "password": "Teste@2026", "codigo": proximo_codigo(self.segredo)})
        self.assertEqual(com.status_code, 200)
        self.assertIn("token", com.json())


@override_settings(EXIGIR_2FA_EQUIPE=True)
class ObrigatoriedadeTest(BaseSAG):
    def test_servidor_sem_2fa_so_acessa_a_configuracao(self):
        self.client.post(reverse("login"), {"username": "ana", "password": "Teste@2026"})
        resp = self.client.get(reverse("atendimento:painel"))
        self.assertRedirects(resp, reverse("doisfatores:configurar"), fetch_redirect_response=False)

        # Configura: a tela mostra o QR; o código do aplicativo ativa
        self.client.get(reverse("doisfatores:configurar"))
        d = DispositivoTOTP.objects.get(usuario=self.u_ana, confirmado_em__isnull=True)
        resp = self.client.post(reverse("doisfatores:configurar"), {"codigo": pyotp.TOTP(servicos.segredo_de(d)).now()})
        self.assertContains(resp, "Guarde estes códigos")
        self.assertEqual(self.client.get(reverse("atendimento:painel")).status_code, 200)
        self.assertTrue(RegistroAuditoria.objects.filter(acao="2FA", detalhes__evento="verificação ativada").exists())

    def test_cidadao_nao_e_obrigado(self):
        self.maria.usuario.set_password("Teste@2026")
        self.client.post(reverse("login"), {"username": "maria", "password": "Teste@2026"})
        self.assertEqual(self.client.get(reverse("atendimento:minhas")).status_code, 200)

    def test_gestor_redefine_2fa_de_servidor_e_fica_registrado(self):
        gestor = User.objects.create_user("gestora", password="Teste@2026")
        gestor.groups.add(grupo_gestor())
        ativar_2fa(self.u_ana)
        self.client.force_login(gestor)
        sessao = self.client.session
        sessao["2fa_configurar"] = False
        sessao.save()
        resp = self.client.post(reverse("gestao:servidor_redefinir_2fa", args=[self.ana.pk]))
        self.assertEqual(resp.status_code, 302)
        self.assertIsNone(servicos.dispositivo_ativo(User.objects.get(pk=self.u_ana.pk)))
        self.assertTrue(RegistroAuditoria.objects.filter(acao="2FA", objeto_id=str(self.u_ana.pk),
                                                         detalhes__evento="redefinida pelo gestor").exists())
