"""
Garante a segunda etapa em TODAS as rotas, não só na tela de login.

1. Conta com 2FA ativa que entrou sem passar pela segunda etapa (por
   exemplo, por outra tela de login): a sessão é encerrada.
2. Conta da equipe sem 2FA configurada: só consegue usar a tela de
   configuração (e sair) até concluir.
"""
from django.contrib import messages
from django.contrib.auth import logout
from django.shortcuts import redirect

LIVRES = ("/contas/2fa/", "/contas/logout/", "/static/", "/saude/")


class VerificacaoDuasEtapasMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        sessao = getattr(request, "session", None)
        if sessao is not None and not request.path.startswith(LIVRES) and request.user.is_authenticated:
            if sessao.get("2fa_exige") and not sessao.get("2fa_ok"):
                logout(request)
                messages.error(request, "Entre pela tela de login e informe o código do aplicativo.")
                return redirect("login")
            if sessao.get("2fa_configurar"):
                messages.info(request, "Para sua segurança, a equipe da prefeitura usa verificação em duas etapas. Configure para continuar.")
                return redirect("doisfatores:configurar")
        return self.get_response(request)
