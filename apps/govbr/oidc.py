"""
SAG-Cidadão — login com a conta gov.br (OpenID Connect)
App: govbr/oidc.py

OAuth 2.0 é um protocolo de AUTORIZAÇÃO (dar a um sistema acesso a algo
em seu nome). O OpenID Connect (OIDC) é uma camada de AUTENTICAÇÃO sobre
ele: além do access_token, o provedor entrega um id_token, um JWT
ASSINADO que diz QUEM é o usuário. O gov.br é o provedor de identidade
(IdP); o SAG-Cidadão é o cliente (Relying Party).

Fluxo "authorization code" com PKCE:

  1. SAG gera state, nonce e code_verifier; manda o navegador para o gov.br
     com o code_challenge = SHA-256(code_verifier).
  2. A pessoa entra no gov.br (senha, app, certificado...). O SAG nunca vê
     a senha.
  3. O gov.br devolve o navegador para o SAG com um "code" de uso único.
  4. O SAG troca o code pelos tokens, servidor a servidor, enviando o
     client_secret e o code_verifier.
  5. O SAG confere a assinatura do id_token com a chave pública do gov.br
     (JWKS), o emissor, o destinatário, a validade e o nonce.

Para que serve cada peça:
  state         ->  contra CSRF no retorno (o retorno foi pedido por ESTA sessão)
  nonce         ->  contra replay do id_token (o token foi emitido para ESTE login)
  PKCE          ->  um code interceptado não serve sem o code_verifier
  assinatura    ->  ninguém forja um id_token sem a chave privada do gov.br
"""
import base64
import hashlib
import json
import secrets
import time
import urllib.parse
import urllib.request

import jwt
from django.conf import settings
from django.core.cache import cache

ESCOPOS = "openid email profile govbr_confiabilidades"
BASES = {
    "homologacao": "https://sso.staging.acesso.gov.br",
    "producao": "https://sso.acesso.gov.br",
}


class ErroGovbr(Exception):
    """Falha na conversa com o gov.br ou token inválido."""


def habilitado():
    return bool(settings.GOVBR_CLIENT_ID and settings.GOVBR_CLIENT_SECRET)


def base():
    return BASES.get(settings.GOVBR_AMBIENTE, BASES["homologacao"])


def novo_pedido():
    """state, nonce e o par PKCE (verifier fica na sessão; challenge vai na URL)."""
    verifier = secrets.token_urlsafe(64)[:96]  # 43 a 128 caracteres (RFC 7636)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return {
        "state": secrets.token_urlsafe(32), "nonce": secrets.token_urlsafe(32),
        "verifier": verifier, "challenge": challenge, "criado": time.time(),
    }


def url_de_autorizacao(pedido, redirect_uri):
    parametros = {
        "response_type": "code", "client_id": settings.GOVBR_CLIENT_ID, "scope": ESCOPOS,
        "redirect_uri": redirect_uri, "state": pedido["state"], "nonce": pedido["nonce"],
        "code_challenge": pedido["challenge"], "code_challenge_method": "S256",
    }
    return f"{base()}/authorize?{urllib.parse.urlencode(parametros, quote_via=urllib.parse.quote)}"


def _http(url, dados=None, cabecalhos=None):
    corpo = urllib.parse.urlencode(dados).encode() if dados is not None else None
    req = urllib.request.Request(url, data=corpo, headers=cabecalhos or {})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except Exception as erro:  # rede, HTTP 4xx/5xx, JSON inválido
        raise ErroGovbr(f"falha ao falar com o gov.br ({url}): {erro}")


def trocar_code(code, verifier, redirect_uri):
    """Passo 4: servidor a servidor, com autenticação Basic (client_id:secret)."""
    credencial = base64.b64encode(f"{settings.GOVBR_CLIENT_ID}:{settings.GOVBR_CLIENT_SECRET}".encode()).decode()
    return _http(f"{base()}/token", {
        "grant_type": "authorization_code", "code": code,
        "redirect_uri": redirect_uri, "code_verifier": verifier,
    }, {"Authorization": f"Basic {credencial}", "Content-Type": "application/x-www-form-urlencoded"})


def chaves_publicas():
    """JWKS do gov.br, guardado em cache por 1 hora."""
    jwks = cache.get("govbr:jwks")
    if jwks is None:
        jwks = _http(f"{base()}/jwk")
        cache.set("govbr:jwks", jwks, 3600)
    return jwks


def validar_id_token(id_token, nonce_esperado):
    """Passo 5. Devolve as informações (claims) do usuário, já conferidas."""
    try:
        cabecalho = jwt.get_unverified_header(id_token)
        chave = next((k for k in chaves_publicas().get("keys", []) if k.get("kid") == cabecalho.get("kid")), None)
        if chave is None:
            cache.delete("govbr:jwks")  # o gov.br pode ter trocado as chaves
            raise ErroGovbr("chave de assinatura desconhecida")
        claims = jwt.decode(
            id_token, key=jwt.PyJWK(chave).key,
            algorithms=["RS256"],               # NUNCA aceitar "none" nem HS256 aqui
            audience=settings.GOVBR_CLIENT_ID,  # o token foi emitido para o SAG
            issuer=base() + "/",                # e pelo gov.br
            leeway=60,                          # tolera 1 min de diferença de relógio
            options={"require": ["exp", "iat", "sub", "nonce"]},
        )
    except jwt.PyJWTError as erro:
        raise ErroGovbr(f"id_token inválido: {erro}")
    if not secrets.compare_digest(str(claims.get("nonce", "")), nonce_esperado):
        raise ErroGovbr("nonce não confere (possível reaproveitamento de token)")
    return claims
