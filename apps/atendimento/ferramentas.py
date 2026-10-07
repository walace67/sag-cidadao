"""
Ferramentas de QUALIDADE (auditoria de acessibilidade e teste de carga).
Não são usadas pelas telas do sistema.

criar_sessao(): abre uma sessão autenticada direto no banco, como se o
usuário tivesse feito login (inclusive a segunda etapa). Serve para os
robôs de teste não esbarrarem no limite de tentativas de login, que é
justamente uma proteção que funciona.
"""
from django.conf import settings
from django.contrib.auth import BACKEND_SESSION_KEY, HASH_SESSION_KEY, SESSION_KEY
from django.contrib.sessions.backends.db import SessionStore


def criar_sessao(usuario):
    sessao = SessionStore()
    sessao[SESSION_KEY] = str(usuario.pk)
    sessao[BACKEND_SESSION_KEY] = "django.contrib.auth.backends.ModelBackend"
    sessao[HASH_SESSION_KEY] = usuario.get_session_auth_hash()
    sessao["2fa_exige"] = False
    sessao["2fa_ok"] = True
    sessao["2fa_configurar"] = False
    sessao.create()
    return {"name": settings.SESSION_COOKIE_NAME, "value": sessao.session_key}
