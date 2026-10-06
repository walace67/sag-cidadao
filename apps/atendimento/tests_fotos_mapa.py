"""
Testes das fotos (limpeza de metadados, validação, acesso) e do mapa.
    python manage.py test apps.atendimento.tests_fotos_mapa
"""
import io
import shutil
import tempfile
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import override_settings
from django.urls import reverse
from PIL import Image

from . import services
from .imagens import processar_foto
from .models import Cidadao, FotoSolicitacao, Solicitacao
from .tests import BaseSAG

PASTA = tempfile.mkdtemp(prefix="sag-media-teste-")


def jpeg_com_gps(largura=2400, altura=1800):
    """Foto de celular: grande, com GPS e modelo do aparelho no EXIF."""
    img = Image.new("RGB", (largura, altura), (120, 90, 60))
    exif = Image.Exif()
    exif[0x0110] = "Celular de Teste X"               # Model
    exif[0x0112] = 6                                   # Orientation: girada 90°
    gps = {1: "S", 2: (8.0, 45.0, 40.0), 3: "W", 4: (63.0, 54.0, 1.0)}
    exif[0x8825] = gps                                 # GPSInfo
    saida = io.BytesIO()
    img.save(saida, "JPEG", exif=exif)
    return SimpleUploadedFile("IMG_20261006_casa.jpg", saida.getvalue(), content_type="image/jpeg")


@override_settings(MEDIA_ROOT=PASTA)
class FotosTest(BaseSAG):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(PASTA, ignore_errors=True)

    # --- tratamento da imagem ---------------------------------------------
    def test_foto_sai_sem_gps_reduzida_e_na_orientacao_certa(self):
        original = jpeg_com_gps()
        self.assertIn(0x8825, Image.open(original).getexif())  # o original TEM GPS
        original.seek(0)
        limpa = Image.open(processar_foto(original))
        self.assertEqual(len(limpa.getexif()), 0)               # nenhum metadado
        self.assertEqual(limpa.format, "JPEG")
        self.assertEqual(limpa.size, (1200, 1600))              # girada (EXIF 6) e reduzida a 1600 px

    def test_arquivo_disfarcado_de_imagem_e_recusado(self):
        falso = SimpleUploadedFile("foto.jpg", b"#!/bin/sh\nrm -rf /\n", content_type="image/jpeg")
        with self.assertRaises(ValidationError):
            processar_foto(falso)

    def test_bomba_de_descompressao_e_recusada(self):
        enorme = io.BytesIO()
        Image.new("1", (12000, 12000)).save(enorme, "PNG")       # poucos KB, 144 milhões de pixels
        self.assertLess(enorme.tell(), 200_000)
        with self.assertRaises(ValidationError):
            processar_foto(SimpleUploadedFile("x.png", enorme.getvalue(), content_type="image/png"))

    # --- fluxo pela tela ------------------------------------------------------
    def abrir(self, **extra):
        self.client.force_login(self.maria.usuario)
        dados = {
            "categoria": self.buraco.pk, "bairro": self.aponia.pk, "endereco_referencia": "Rua A, 10",
            "descricao": "Buraco grande no meio da pista, perigoso à noite.",
        }
        dados.update(extra)
        return self.client.post(reverse("atendimento:nova"), dados)

    def test_cidadao_envia_foto_e_ponto_no_mapa(self):
        resp = self.abrir(fotos=[jpeg_com_gps()], latitude="-8.761200", longitude="-63.900400")
        self.assertEqual(resp.status_code, 302)
        s = Solicitacao.objects.get(cidadao=self.maria)
        self.assertEqual(s.latitude, Decimal("-8.761200"))
        foto = s.fotos.get()
        self.assertEqual(foto.etapa, FotoSolicitacao.Etapa.PROBLEMA)
        self.assertNotIn("casa", foto.arquivo.name)              # nome original descartado
        self.assertTrue(foto.arquivo.name.endswith(".jpg"))
        self.assertEqual(len(Image.open(foto.arquivo.path).getexif()), 0)

    def test_no_maximo_tres_fotos(self):
        resp = self.abrir(fotos=[jpeg_com_gps(200, 100) for _ in range(4)])
        self.assertContains(resp, "no máximo 3 fotos")
        self.assertFalse(Solicitacao.objects.exists())

    def test_ponto_fora_do_municipio_e_recusado(self):
        resp = self.abrir(latitude="-23.550500", longitude="-46.633300")  # São Paulo
        self.assertContains(resp, "fora do município")

    def test_so_latitude_e_recusado(self):
        resp = self.abrir(latitude="-8.761200")
        self.assertContains(resp, "Marque o ponto no mapa novamente")

    def test_banco_recusa_coordenada_pela_metade(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Solicitacao.objects.create(cidadao=self.maria, categoria=self.buraco, bairro=self.aponia,
                                       descricao="x" * 20, endereco_referencia="Rua", latitude=Decimal("-8.7"))

    # --- quem pode ver a foto ------------------------------------------------
    def foto_da_maria(self):
        s = services.abrir_solicitacao(cidadao=self.maria, categoria=self.buraco, bairro=self.aponia,
                                       descricao="Buraco grande na pista.", endereco_referencia="Rua A",
                                       fotos=[processar_foto(jpeg_com_gps(400, 300))])
        return s.fotos.get()

    def test_acesso_a_foto(self):
        foto = self.foto_da_maria()  # categoria da SEMOB
        url = reverse("atendimento:foto", args=[foto.pk])
        self.assertEqual(self.client.get(url).status_code, 302)          # anônimo -> login

        self.client.force_login(self.maria.usuario)
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)                          # autora
        self.assertEqual(resp["Content-Type"], "image/jpeg")
        self.assertIn("private", resp["Cache-Control"])

        self.client.force_login(self.u_ana)
        self.assertEqual(self.client.get(url).status_code, 200)          # servidora da SEMOB
        self.client.force_login(self.u_carlos)
        self.assertEqual(self.client.get(url).status_code, 404)          # servidor de outra secretaria

        u = User.objects.create_user("joao", password="x")
        Cidadao.objects.create(usuario=u, cpf="11144477735", nome_completo="João Souza", bairro=self.centro)
        self.client.force_login(u)
        self.assertEqual(self.client.get(url).status_code, 404)          # outro cidadão: IDOR bloqueado

    @override_settings(SERVIR_MIDIA_COM_NGINX=True)
    def test_em_producao_o_nginx_entrega_o_arquivo(self):
        foto = self.foto_da_maria()
        self.client.force_login(self.maria.usuario)
        resp = self.client.get(reverse("atendimento:foto", args=[foto.pk]))
        self.assertEqual(resp["X-Accel-Redirect"], "/midia-protegida/" + foto.arquivo.name)
        self.assertEqual(resp.content, b"")                              # o Python não leu o arquivo

    def test_servidor_anexa_foto_do_servico(self):
        s = self.nova()
        self.client.force_login(self.u_ana)
        self.client.post(reverse("atendimento:detalhe", args=[s.pk]),
                         {"acao": "status", "novo_status": "ANA", "observacao": "Vistoria", "foto": [jpeg_com_gps(300, 200)]})
        self.assertEqual(s.fotos.get().etapa, FotoSolicitacao.Etapa.SERVICO)

    def test_apagar_a_foto_apaga_o_arquivo(self):
        foto = self.foto_da_maria()
        caminho = foto.arquivo.path
        with self.captureOnCommitCallbacks(execute=True):
            foto.delete()
        import os
        self.assertFalse(os.path.exists(caminho))


class MapaGestaoTest(BaseSAG):
    def test_dados_do_mapa_sem_dados_pessoais(self):
        from apps.gestao.permissoes import grupo_gestor

        services.abrir_solicitacao(cidadao=self.maria, categoria=self.buraco, bairro=self.aponia,
                                   descricao="Buraco grande na pista.", endereco_referencia="Rua das Flores, 320",
                                   latitude=Decimal("-8.76"), longitude=Decimal("-63.90"))
        self.nova()  # sem ponto
        url = reverse("gestao:mapa_dados") + "?dias=30"
        self.client.force_login(self.maria.usuario)
        self.assertEqual(self.client.get(url).status_code, 403)
        gestor = User.objects.create_user("gestora", password="x")
        gestor.groups.add(grupo_gestor())
        self.client.force_login(gestor)
        dados = self.client.get(url).json()
        self.assertEqual(dados["total"], 2)
        self.assertEqual(len(dados["pontos"]), 1)
        texto = str(dados)
        for pessoal in ("Maria", "52998224725", "Flores"):
            self.assertNotIn(pessoal, texto)
