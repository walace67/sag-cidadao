"""
Regras da verificação em duas etapas: segredo cifrado, verificação do
código com anti-repetição, códigos de recuperação e quem é obrigado a usar.
"""
import base64
import hashlib
import hmac
import secrets
import time

import pyotp
import segno
from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import CodigoRecuperacao, DispositivoTOTP

PERIODO = 30          # segundos de cada código
TOLERANCIA = 1        # aceita 1 passo antes/depois (relógio do celular adiantado ou atrasado)
EMISSOR = "SAG-Cidadão"
QTD_CODIGOS = 10


# --- Cifra do segredo ------------------------------------------------------
def _fernet():
    # Chave derivada da SECRET_KEY. Trocar a SECRET_KEY obriga todos a
    # configurarem o aplicativo de novo (o segredo antigo não decifra mais).
    chave = hashlib.sha256(b"sag-2fa:" + settings.SECRET_KEY.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(chave))


def cifrar(segredo):
    return _fernet().encrypt(segredo.encode()).decode()


def decifrar(texto):
    return _fernet().decrypt(texto.encode()).decode()


# --- Quem precisa ----------------------------------------------------------
def precisa_2fa(usuario):
    """Equipe da prefeitura: servidores, gestores e administradores."""
    from apps.gestao.permissoes import eh_gestor

    return bool(usuario.is_authenticated and (
        usuario.is_staff or usuario.is_superuser or hasattr(usuario, "servidor") or eh_gestor(usuario)
    ))


def dispositivo_ativo(usuario):
    if not usuario.is_authenticated:
        return None
    if not hasattr(usuario, "_totp_cache"):
        usuario._totp_cache = DispositivoTOTP.objects.filter(usuario=usuario, confirmado_em__isnull=False).first()
    return usuario._totp_cache


# --- Configuração ----------------------------------------------------------
def iniciar_configuracao(usuario):
    """Cria (ou recria) um dispositivo ainda não confirmado com segredo novo."""
    DispositivoTOTP.objects.filter(usuario=usuario, confirmado_em__isnull=True).delete()
    segredo = pyotp.random_base32()  # 160 bits aleatórios em base32
    return DispositivoTOTP.objects.create(usuario=usuario, segredo_cifrado=cifrar(segredo)), segredo


def segredo_de(dispositivo):
    return decifrar(dispositivo.segredo_cifrado)


def uri_para_aplicativo(dispositivo):
    """otpauth://totp/...: é o conteúdo do QR code lido pelo aplicativo."""
    return pyotp.TOTP(segredo_de(dispositivo)).provisioning_uri(
        name=dispositivo.usuario.get_username(), issuer_name=EMISSOR
    )


def qr_svg(dispositivo):
    # omitsize=True gera o atributo viewBox: o SVG passa a ESCALAR quando o
    # CSS define o tamanho. Sem ele, o navegador cortava as bordas do código.
    # Fundo branco explícito e margem de 4 módulos ("zona de silêncio"),
    # exigida pelos leitores de QR.
    return segno.make(uri_para_aplicativo(dispositivo), error="m").svg_inline(
        scale=1, border=4, omitsize=True, dark="#000000", light="#ffffff",
    )


def segredo_formatado(dispositivo):
    s = segredo_de(dispositivo)
    return " ".join(s[i:i + 4] for i in range(0, len(s), 4))


# --- Verificação -----------------------------------------------------------
def _so_digitos(codigo):
    return "".join(c for c in str(codigo or "") if c.isdigit())


def verificar_totp(dispositivo, codigo, agora=None):
    codigo = _so_digitos(codigo)
    if len(codigo) != 6 or dispositivo is None:
        return False
    try:
        totp = pyotp.TOTP(segredo_de(dispositivo))
    except InvalidToken:
        return False
    passo_atual = int((agora or time.time()) // PERIODO)
    for passo in range(passo_atual - TOLERANCIA, passo_atual + TOLERANCIA + 1):
        if passo <= dispositivo.ultimo_passo:
            continue  # código já usado (ou anterior a um já usado): replay
        if hmac.compare_digest(totp.at(passo * PERIODO), codigo):
            # UPDATE condicional: se duas requisições chegarem juntas com o
            # mesmo código, só uma consegue "gastar" o passo.
            gastou = DispositivoTOTP.objects.filter(pk=dispositivo.pk, ultimo_passo__lt=passo).update(ultimo_passo=passo)
            if gastou:
                dispositivo.ultimo_passo = passo
                return True
            return False
    return False


def confirmar(dispositivo, codigo):
    if not verificar_totp(dispositivo, codigo):
        return None
    with transaction.atomic():
        DispositivoTOTP.objects.filter(usuario=dispositivo.usuario, confirmado_em__isnull=False).exclude(pk=dispositivo.pk).delete()
        dispositivo.confirmado_em = timezone.now()
        dispositivo.save(update_fields=["confirmado_em"])
        return gerar_codigos_recuperacao(dispositivo.usuario)


# --- Códigos de recuperação --------------------------------------------------
def _hash(codigo):
    return hashlib.sha256(codigo.replace("-", "").strip().lower().encode()).hexdigest()


def gerar_codigos_recuperacao(usuario):
    """Gera 10 códigos novos (os antigos deixam de valer). Mostrados UMA vez."""
    alfabeto = "abcdefghjkmnpqrstuvwxyz23456789"  # sem 0/o, 1/l/i: menos erro de digitação
    codigos = ["-".join("".join(secrets.choice(alfabeto) for _ in range(4)) for _ in range(3)) for _ in range(QTD_CODIGOS)]
    CodigoRecuperacao.objects.filter(usuario=usuario).delete()
    CodigoRecuperacao.objects.bulk_create([CodigoRecuperacao(usuario=usuario, hash=_hash(c)) for c in codigos])
    return codigos


def usar_codigo_recuperacao(usuario, codigo):
    if not codigo or len(codigo.replace("-", "").strip()) != 12:
        return False
    return bool(CodigoRecuperacao.objects.filter(
        usuario=usuario, hash=_hash(codigo), usado_em__isnull=True
    ).update(usado_em=timezone.now()))


def codigos_restantes(usuario):
    return CodigoRecuperacao.objects.filter(usuario=usuario, usado_em__isnull=True).count()


def remover(usuario):
    DispositivoTOTP.objects.filter(usuario=usuario).delete()
    CodigoRecuperacao.objects.filter(usuario=usuario).delete()
