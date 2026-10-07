"""
SAG-Cidadão — limite de tentativas (rate limiting)
App: atendimento/seguranca.py

Defesa contra força bruta (adivinhar senhas) e enumeração (descobrir
quais CPFs estão cadastrados): mesmo que cada resposta revele pouco,
um atacante precisa de MILHARES de tentativas. Limitando as tentativas
por IP e por login, o ataque fica lento demais para valer a pena.

Os contadores ficam no CACHE do Django (memória). Em produção, com
vários processos/servidores, o cache deve ser compartilhado (Redis ou
Memcached); senão cada processo conta separado.

Algoritmo: JANELA FIXA. A primeira tentativa cria um contador que expira
após `janela` segundos; cada tentativa seguinte soma 1. Passou do limite,
responde HTTP 429 (Too Many Requests) com o cabeçalho Retry-After.
"""
import hashlib
import logging
from functools import wraps

from django.conf import settings
from django.core.cache import cache
from django.shortcuts import render

log = logging.getLogger("sag.seguranca")


def ip_do_cliente(request):
    """
    REMOTE_ADDR é o IP de quem abriu a conexão. Atrás de um proxy reverso
    (Nginx), ele vira o IP do proxy; aí se usa o X-Forwarded-For, mas SÓ
    se o proxy for confiável, pois o cliente pode falsificar esse cabeçalho.
    """
    remoto = request.META.get("REMOTE_ADDR", "desconhecido")
    proxies = getattr(settings, "PROXIES_CONFIAVEIS", 0) or (1 if getattr(settings, "CONFIAR_PROXY", False) else 0)
    if proxies:
        # Cada proxy nosso ACRESCENTA um endereço ao final da lista; o que
        # vier antes pode ter sido escrito pelo próprio cliente. Com N
        # proxies, o IP real é o N-ésimo a contar do fim.
        encaminhado = [e.strip() for e in request.headers.get("x-forwarded-for", "").split(",") if e.strip()]
        if encaminhado:
            return encaminhado[-min(proxies, len(encaminhado))]
    return remoto


def anonimizar(valor):
    """
    Identificador para logs sem expor o dado pessoal (LGPD: minimização).
    Hash com a SECRET_KEY: o mesmo login gera sempre o mesmo código (dá
    para correlacionar ataques), mas não dá para voltar ao CPF.
    """
    bruto = f"{settings.SECRET_KEY}:{valor}".encode()
    return hashlib.sha256(bruto).hexdigest()[:12]


def registrar_tentativa(chave, janela):
    """Soma 1 ao contador e devolve o total na janela atual."""
    if cache.add(chave, 1, timeout=janela):  # add só grava se não existir
        return 1
    try:
        return cache.incr(chave)
    except ValueError:  # expirou entre o add e o incr
        cache.set(chave, 1, timeout=janela)
        return 1


def contagem(chave):
    return cache.get(chave, 0)


def zerar(chave):
    cache.delete(chave)


def resposta_429(request, janela, motivo="limite"):
    log.warning("429 %s ip=%s caminho=%s", motivo, ip_do_cliente(request), request.path)
    resp = render(request, "atendimento/429.html", {"minutos": max(1, janela // 60)}, status=429)
    resp["Retry-After"] = str(janela)
    return resp


def limitar(escopo, limite, janela, metodos=("POST",)):
    """
    Decorator: no máximo `limite` requisições por IP a cada `janela` segundos.
        @limitar("cadastro", limite=5, janela=3600)
    """

    def decorador(view):
        @wraps(view)
        def _view(request, *args, **kwargs):
            if request.method in metodos:
                chave = f"limite:{escopo}:{ip_do_cliente(request)}"
                if registrar_tentativa(chave, janela) > limite:
                    return resposta_429(request, janela, motivo=escopo)
            return view(request, *args, **kwargs)

        return _view

    return decorador
