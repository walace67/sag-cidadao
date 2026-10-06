"""
SAG-Cidadão — verificação de saúde (health check)
App: atendimento/saude.py

GET /saude/ responde 200 {"status": "ok"} se a aplicação E o banco estão
respondendo, ou 503 (Service Unavailable) se o banco caiu.

Quem usa: o monitoramento (Uptime Kuma, Zabbix, Nagios), o balanceador de
carga e o script de deploy, para saber se a nova versão subiu de verdade.

Não exige login e não revela nada interno: nem versão, nem nome do banco,
nem a mensagem de erro (isso vai só para o log).
"""
import logging

from django.db import connection
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

log = logging.getLogger("sag.saude")


@never_cache
@require_GET
def saude(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:  # qualquer falha de banco = serviço indisponível
        log.exception("health check: banco indisponível")
        return JsonResponse({"status": "erro", "banco": "indisponivel"}, status=503)
    return JsonResponse({"status": "ok", "banco": "ok"})
