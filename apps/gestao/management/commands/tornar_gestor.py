"""
Uso:  python manage.py tornar_gestor <usuario>
      python manage.py tornar_gestor <usuario> --remover
"""
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError

from apps.gestao.permissoes import grupo_gestor


class Command(BaseCommand):
    help = "Adiciona (ou remove) um usuário do papel Gestor."

    def add_arguments(self, parser):
        parser.add_argument("usuario")
        parser.add_argument("--remover", action="store_true")

    def handle(self, usuario, remover, **opcoes):
        try:
            user = User.objects.get(username=usuario)
        except User.DoesNotExist:
            raise CommandError(f"Usuário '{usuario}' não existe.")
        from apps.auditoria.registro import A, registrar

        era = user.groups.filter(pk=grupo_gestor().pk).exists()
        registrar(A.PAPEL, objeto=user, detalhes={
            "Gestor": ["Sim" if era else "Não", "Não" if remover else "Sim"],
            "origem": "linha de comando (tornar_gestor)",
        })
        if remover:
            user.groups.remove(grupo_gestor())
            self.stdout.write(self.style.SUCCESS(f"{usuario} deixou de ser gestor."))
        else:
            user.groups.add(grupo_gestor())
            self.stdout.write(self.style.SUCCESS(f"{usuario} agora é gestor."))
