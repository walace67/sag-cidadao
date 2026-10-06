"""
Ao entrar no sistema (por QUALQUER tela de login), a sessão anota:
    2fa_exige     -> a conta tem verificação em duas etapas ativa
    2fa_configurar-> a conta é da equipe e ainda não configurou
O middleware lê só a sessão: nenhuma consulta extra por requisição.
"""
from django.conf import settings
from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver

from .models import DispositivoTOTP
from .servicos import precisa_2fa


@receiver(user_logged_in)
def marcar_sessao(sender, request, user, **kwargs):
    if request is None or not hasattr(request, "session"):
        return
    ativo = DispositivoTOTP.objects.filter(usuario=user, confirmado_em__isnull=False).exists()
    request.session["2fa_exige"] = ativo
    request.session["2fa_ok"] = False
    request.session["2fa_configurar"] = (not ativo) and settings.EXIGIR_2FA_EQUIPE and precisa_2fa(user)
