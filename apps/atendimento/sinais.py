"""
Apagar o registro da foto no banco NÃO apaga o arquivo no disco.
Este sinal remove o arquivo, mas só depois do COMMIT: se a exclusão for
desfeita (ROLLBACK), o arquivo continua lá, coerente com o banco.
"""
from django.db import transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import FotoSolicitacao


@receiver(post_delete, sender=FotoSolicitacao)
def apagar_arquivo(sender, instance, **kwargs):
    if instance.arquivo:
        armazenamento, nome = instance.arquivo.storage, instance.arquivo.name
        transaction.on_commit(lambda: armazenamento.delete(nome))
