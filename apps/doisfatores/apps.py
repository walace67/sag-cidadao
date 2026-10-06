from django.apps import AppConfig


class DoisFatoresConfig(AppConfig):
    name = "apps.doisfatores"
    verbose_name = "Verificação em duas etapas"

    def ready(self):
        from . import sinais  # noqa: F401
