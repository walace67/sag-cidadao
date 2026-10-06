"""
URLconf raiz do projeto SAG-Cidadão.

O Django lê esta lista de cima para baixo e usa a PRIMEIRA rota que casar
com o endereço pedido. O include() delega um prefixo para o urls.py do app.
"""
from django.conf import settings
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from apps.atendimento import contas, saude

T = "atendimento/senha/"  # templates de senha no visual do sistema

urlpatterns = [
    # Endereço do admin vem do .env (ADMIN_URL); em produção, troque o padrão
    path(settings.ADMIN_URL, admin.site.urls),
    # Verificação de saúde para o monitoramento: aplicação + banco
    path("saude/", saude.saude, name="saude"),
    # Contas: rotas explícitas (em vez de include("django.contrib.auth.urls"))
    # para usar as versões com limite de tentativas e o visual do sistema.
    path("contas/login/", contas.LoginSeguro.as_view(), name="login"),
    path("contas/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("contas/senha/redefinir/", contas.RedefinirSenha.as_view(), name="password_reset"),
    path("contas/senha/redefinir/enviado/",
         auth_views.PasswordResetDoneView.as_view(template_name=T + "enviado.html"), name="password_reset_done"),
    path("contas/senha/redefinir/<uidb64>/<token>/",
         auth_views.PasswordResetConfirmView.as_view(template_name=T + "nova.html"), name="password_reset_confirm"),
    path("contas/senha/redefinir/concluido/",
         auth_views.PasswordResetCompleteView.as_view(template_name=T + "concluido.html"), name="password_reset_complete"),
    path("contas/senha/alterar/",
         auth_views.PasswordChangeView.as_view(template_name=T + "alterar.html"), name="password_change"),
    path("contas/senha/alterar/concluido/",
         auth_views.PasswordChangeDoneView.as_view(template_name=T + "concluido.html"), name="password_change_done"),
    # Área de gestão (perfil Gestor): cadastros e dashboard, sem o admin
    path("gestao/", include("apps.gestao.urls")),
    # API REST (JSON)
    path("api/", include("apps.atendimento.api_urls")),
    # Telas do atendimento (cidadão, servidor e público)
    path("", include("apps.atendimento.urls")),
]
