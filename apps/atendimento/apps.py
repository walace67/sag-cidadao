from django.apps import AppConfig


class AtendimentoConfig(AppConfig):
    name = "apps.atendimento"

    def ready(self):
        from . import sinais  # noqa: F401
