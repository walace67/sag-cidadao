"""
SAG-Cidadão — verificação em duas etapas (2FA) com TOTP
App: doisfatores/models.py

Autenticação MULTIFATOR = provar a identidade com fatores de tipos diferentes:
    algo que você SABE (senha) + algo que você TEM (o celular com o aplicativo)
    (+ algo que você É: biometria)
Duas senhas NÃO são dois fatores: são dois itens do mesmo tipo.

TOTP (RFC 6238): o servidor e o aplicativo (Google Authenticator, Microsoft
Authenticator, FreeOTP, 2FAS) compartilham um SEGREDO. A cada 30 segundos,
os dois calculam HMAC(segredo, relógio) e mostram 6 dígitos. Sem rede e
sem SMS: só o segredo e o relógio.
"""
from django.conf import settings
from django.db import models


class DispositivoTOTP(models.Model):
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="dispositivos_totp")
    # O segredo fica CIFRADO no banco (AES, via Fernet): quem copiar a
    # tabela não consegue gerar códigos sem a chave da aplicação.
    segredo_cifrado = models.TextField()
    confirmado_em = models.DateTimeField(null=True, blank=True)
    # Anti-repetição (replay): um código já aceito não vale de novo,
    # nem dentro dos mesmos 30 segundos.
    ultimo_passo = models.BigIntegerField(default=0)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "dispositivo_totp"
        verbose_name = "dispositivo de verificação"
        constraints = [
            # Índice ÚNICO PARCIAL: no máximo UM dispositivo CONFIRMADO por
            # usuário. Os não confirmados (configuração em andamento) não contam.
            models.UniqueConstraint(
                fields=["usuario"], condition=models.Q(confirmado_em__isnull=False),
                name="uq_totp_um_ativo_por_usuario",
            ),
        ]

    def __str__(self):
        return f"TOTP de {self.usuario}"


class CodigoRecuperacao(models.Model):
    """Códigos de uso único para quando o celular for perdido."""

    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="codigos_recuperacao")
    # Só o hash SHA-256: como o código é aleatório e longo, não precisa do
    # PBKDF2 lento das senhas (não há dicionário para testar).
    hash = models.CharField(max_length=64)
    usado_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "codigo_recuperacao"
        indexes = [models.Index(fields=["usuario", "hash"], name="ix_codrec_usuario_hash")]
