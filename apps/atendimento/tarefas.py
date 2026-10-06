"""
SAG-Cidadão — tarefas em segundo plano
App: atendimento/tarefas.py

    Tela (servidor muda o status)          Worker (outro processo)
    ─────────────────────────────          ───────────────────────
    UPDATE solicitacao + INSERT histórico
    COMMIT
    on_commit → enfileira a tarefa  ──►    pega a tarefa da fila
    responde ao servidor na hora           monta e envia o e-mail

Por que em segundo plano: o SMTP pode demorar segundos ou estar fora do
ar. A mudança de status não pode esperar nem falhar por causa do e-mail.

Por que on_commit: se a transação for desfeita (ROLLBACK), o e-mail não
pode sair contando algo que não aconteceu.

Argumentos de tarefa precisam ser serializáveis (JSON): por isso a tarefa
recebe IDs, e não objetos, e busca os dados atualizados no banco.
"""
import logging

from django.conf import settings
from django.core.mail import send_mail
from django.tasks import task
from django.template.loader import render_to_string
from django.urls import reverse

from .models import HistoricoSolicitacao, Solicitacao

log = logging.getLogger("sag.tarefas")


def _destinatario(solicitacao):
    """E-mail do cidadão, se ele tiver e-mail, estiver ativo e quiser avisos."""
    cidadao = solicitacao.cidadao
    usuario = cidadao.usuario
    if not (usuario.email and usuario.is_active and cidadao.receber_avisos):
        return None
    return usuario.email


@task()
def avisar_abertura(solicitacao_id: int) -> str:
    s = Solicitacao.objects.select_related("cidadao__usuario", "categoria", "bairro").get(pk=solicitacao_id)
    email = _destinatario(s)
    if not email:
        return "sem destinatário"
    corpo = render_to_string("atendimento/email/aviso_abertura.txt", {
        "s": s, "nome": s.cidadao.usuario.first_name or s.cidadao.nome_completo.split()[0],
        "link": settings.SITE_URL + reverse("atendimento:minhas"),
        "consulta": settings.SITE_URL + reverse("atendimento:consulta") + f"?protocolo={s.protocolo}",
    })
    send_mail(f"Recebemos sua solicitação: {s.categoria.nome}", corpo, settings.DEFAULT_FROM_EMAIL, [email])
    log.info("aviso de abertura enviado solicitacao=%s", s.pk)
    return "enviado"


@task()
def avisar_mudanca_status(historico_id: int) -> str:
    h = HistoricoSolicitacao.objects.select_related(
        "solicitacao__cidadao__usuario", "solicitacao__categoria", "solicitacao__bairro"
    ).get(pk=historico_id)
    s = h.solicitacao
    email = _destinatario(s)
    if not email:
        return "sem destinatário"
    corpo = render_to_string("atendimento/email/aviso_status.txt", {
        "s": s, "h": h, "nome": s.cidadao.usuario.first_name or s.cidadao.nome_completo.split()[0],
        "link": settings.SITE_URL + reverse("atendimento:minhas"),
    })
    send_mail(f"Sua solicitação mudou: {h.get_status_novo_display()}", corpo, settings.DEFAULT_FROM_EMAIL, [email])
    log.info("aviso de status enviado solicitacao=%s status=%s", s.pk, h.status_novo)
    return "enviado"
