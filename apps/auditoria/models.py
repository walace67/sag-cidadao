"""
SAG-Cidadão — trilha de auditoria
App: auditoria/models.py

Registra QUEM fez O QUÊ, QUANDO e DE ONDE nas ações sensíveis: entradas
no sistema, tentativas recusadas, alterações de cadastros, mudanças de
papel, bloqueios, exportação de dados pessoais, verificação em duas etapas.

A trilha é IMUTÁVEL (append-only): só se acrescenta, nunca se altera.
    1. Na aplicação: save() de um registro existente e delete() levantam erro;
       update() e delete() em lote também.
    2. No banco: um TRIGGER do PostgreSQL recusa UPDATE e DELETE, mesmo
       que alguém tente direto pelo psql (migração 0002).

Conceitos de prova: não repúdio, rastreabilidade, responsabilização
(LGPD art. 6º, X), registro das operações de tratamento (LGPD art. 37).
"""
from django.conf import settings
from django.db import models


class RegistroImutavel(Exception):
    """Tentativa de alterar ou apagar um registro de auditoria."""


class RegistroQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise RegistroImutavel("A trilha de auditoria não pode ser alterada.")

    def delete(self):
        raise RegistroImutavel("A trilha de auditoria não pode ser apagada.")


class RegistroAuditoria(models.Model):
    class Acao(models.TextChoices):
        LOGIN = "LOGIN", "Entrada no sistema"
        LOGIN_FALHA = "LOGIN_FALHA", "Login recusado"
        LOGOUT = "LOGOUT", "Saída do sistema"
        CRIAR = "CRIAR", "Cadastro criado"
        ALTERAR = "ALTERAR", "Cadastro alterado"
        EXCLUIR = "EXCLUIR", "Cadastro excluído"
        ATIVAR = "ATIVAR", "Acesso reativado"
        DESATIVAR = "DESATIVAR", "Acesso desativado"
        PAPEL = "PAPEL", "Papel alterado"
        SENHA = "SENHA", "Senha alterada"
        DOIS_FATORES = "2FA", "Verificação em duas etapas"
        DADOS_CORRIGIDOS = "CORRIGIR", "Dados pessoais corrigidos"
        DADOS_EXPORTADOS = "EXPORTAR", "Dados pessoais exportados"

    registrado_em = models.DateTimeField(auto_now_add=True, db_index=True)
    # DO_NOTHING + db_constraint=False: apagar um usuário (ex.: cadastro
    # pendente expirado) NÃO pode gerar UPDATE aqui, que o trigger recusaria.
    # O nome fica guardado em usuario_nome, como um retrato do momento.
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.DO_NOTHING, db_constraint=False,
        null=True, blank=True, related_name="+",
    )
    usuario_nome = models.CharField(max_length=150, blank=True)
    acao = models.CharField(max_length=12, choices=Acao.choices)
    objeto_tipo = models.CharField(max_length=60, blank=True)
    objeto_id = models.CharField(max_length=40, blank=True)
    objeto_nome = models.CharField(max_length=200, blank=True)
    detalhes = models.JSONField(default=dict, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)

    objects = RegistroQuerySet.as_manager()

    class Meta:
        db_table = "registro_auditoria"
        ordering = ["-registrado_em", "-id"]
        indexes = [models.Index(fields=["acao", "registrado_em"], name="ix_audit_acao_data")]
        verbose_name = "registro de auditoria"
        verbose_name_plural = "registros de auditoria"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise RegistroImutavel("A trilha de auditoria não pode ser alterada.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise RegistroImutavel("A trilha de auditoria não pode ser apagada.")

    def __str__(self):
        from django.utils import timezone

        return f"{timezone.localtime(self.registrado_em):%d/%m/%Y %H:%M} {self.usuario_nome or 'anônimo'}: {self.get_acao_display()}"
