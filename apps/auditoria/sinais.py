"""
Sinais do Django ligados à trilha de auditoria: o próprio sistema de
autenticação avisa quando alguém entra, sai ou erra a senha.
"""
from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.dispatch import receiver

from .registro import A, registrar


@receiver(user_logged_in)
def ao_entrar(sender, request, user, **kwargs):
    registrar(A.LOGIN, request=request, usuario=user)


@receiver(user_logged_out)
def ao_sair(sender, request, user, **kwargs):
    if user is not None:
        registrar(A.LOGOUT, request=request, usuario=user)


@receiver(user_login_failed)
def ao_falhar(sender, credentials, request=None, **kwargs):
    from apps.atendimento.seguranca import anonimizar

    # O login digitado pode ser um CPF: vai para o registro como hash
    login = (credentials or {}).get("username", "")
    registrar(A.LOGIN_FALHA, request=request, detalhes={"login": anonimizar(login.strip().lower())})
