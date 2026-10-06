from django.apps import AppConfig


class AuditoriaConfig(AppConfig):
    name = "apps.auditoria"
    verbose_name = "Auditoria"

    def ready(self):
        from . import sinais  # noqa: F401  (liga os sinais de login/logout)
