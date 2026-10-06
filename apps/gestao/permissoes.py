"""
SAG-Cidadão — controle de acesso por papel (RBAC)
App: gestao/permissoes.py

RBAC (Role-Based Access Control): a permissão é dada ao PAPEL, e o usuário
recebe papéis. Aqui o papel "Gestor" é um Group do Django. Para trocar quem
é gestor, muda-se o vínculo usuário-grupo, sem mexer no código.

Papéis do sistema:
    Cidadão  -> tem perfil Cidadao
    Servidor -> tem perfil Servidor (escopo: a própria secretaria)
    Gestor   -> pertence ao grupo "Gestor" ou é superusuário (escopo: tudo)
"""
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied

GRUPO_GESTOR = "Gestor"


def grupo_gestor():
    grupo, _ = Group.objects.get_or_create(name=GRUPO_GESTOR)
    return grupo


def eh_gestor(user):
    if not getattr(user, "is_authenticated", False):
        return False
    if user.is_superuser:
        return True
    # Guarda o resultado no objeto para não consultar o banco a cada uso
    if not hasattr(user, "_eh_gestor"):
        user._eh_gestor = user.groups.filter(name=GRUPO_GESTOR).exists()
    return user._eh_gestor


def gestor_required(view):
    """Decorator: autenticação (login_required) + autorização (papel Gestor)."""

    @login_required
    @wraps(view)
    def _view(request, *args, **kwargs):
        if not eh_gestor(request.user):
            raise PermissionDenied("Área restrita a gestores.")  # 403
        return view(request, *args, **kwargs)

    return _view
