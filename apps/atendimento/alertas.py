"""
Alertas por e-mail para a equipe técnica (variável ADMINS no .env).

AlertaPorEmail: quando acontece um erro 500, o Django manda um e-mail com
os detalhes técnicos para os administradores. O problema: se uma página
quebrada recebe 1.000 acessos, chegariam 1.000 e-mails iguais e ninguém
leria mais nenhum. Aqui o MESMO erro (tipo + local) gera no máximo um
e-mail a cada 15 minutos: é o "antiflood".
"""
import hashlib

from django.core.cache import cache
from django.utils.log import AdminEmailHandler

JANELA_ALERTA = 15 * 60


def chave_do_erro(registro):
    if registro.exc_info and registro.exc_info[0]:
        tipo = registro.exc_info[0].__name__
        tb = registro.exc_info[2]
        while tb and tb.tb_next:
            tb = tb.tb_next
        onde = f"{tb.tb_frame.f_code.co_filename}:{tb.tb_lineno}" if tb else ""
    else:
        tipo, onde = registro.levelname, f"{registro.pathname}:{registro.lineno}"
    return "alerta:" + hashlib.sha256(f"{tipo}|{onde}|{registro.getMessage()[:80]}".encode()).hexdigest()[:24]


class AlertaPorEmail(AdminEmailHandler):
    def emit(self, registro):
        # cache.add só grava se a chave NÃO existir: o primeiro passa, os
        # repetidos dentro da janela são descartados (continuam no log).
        if cache.add(chave_do_erro(registro), 1, timeout=JANELA_ALERTA):
            super().emit(registro)
