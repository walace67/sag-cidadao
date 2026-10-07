"""
SAG-Cidadão — rotas do app
App: atendimento/urls.py

app_name cria um "namespace": nos templates e views usamos
{% url 'atendimento:painel' %} em vez de escrever "/painel/" na mão.
Se a URL mudar aqui, todos os links continuam funcionando.

<int:pk> é um conversor: só aceita números e entrega um int à view.
"""
from django.urls import path

from . import contas, views

app_name = "atendimento"

urlpatterns = [
    path("", views.inicio, name="inicio"),
    path("cadastro/", contas.cadastro, name="cadastro"),
    path("cadastro/ativar/<uidb64>/<token>/", contas.ativar, name="ativar"),
    path("meus-dados/", contas.meus_dados, name="meus_dados"),
    path("meus-dados/exportar/", contas.exportar_dados, name="exportar_dados"),
    path("privacidade/", views.privacidade, name="privacidade"),
    path("acessibilidade/", views.acessibilidade, name="acessibilidade"),
    # Servidor
    path("painel/", views.painel, name="painel"),
    path("solicitacao/<int:pk>/", views.detalhe, name="detalhe"),
    path("relatorio/", views.relatorio, name="relatorio"),
    # Cidadão
    path("nova/", views.nova_solicitacao, name="nova"),
    path("minhas/", views.minhas_solicitacoes, name="minhas"),
    path("minhas/<int:pk>/cancelar/", views.cancelar_solicitacao, name="cancelar"),
    # Público
    path("consulta/", views.consulta_protocolo, name="consulta"),
    # Fotos (acesso autorizado, nunca público)
    path("foto/<int:pk>/", views.foto, name="foto"),
]
