from django.urls import path

from . import views

app_name = "gestao"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("cadastros/<slug:tipo>/", views.cadastro_lista, name="cadastro_lista"),
    path("cadastros/<slug:tipo>/novo/", views.cadastro_form, name="cadastro_novo"),
    path("cadastros/<slug:tipo>/<int:pk>/editar/", views.cadastro_form, name="cadastro_editar"),
    path("cadastros/<slug:tipo>/<int:pk>/excluir/", views.cadastro_excluir, name="cadastro_excluir"),
    path("servidores/", views.servidores, name="servidores"),
    path("servidores/novo/", views.servidor_form, name="servidor_novo"),
    path("servidores/<int:pk>/editar/", views.servidor_form, name="servidor_editar"),
    path("servidores/<int:pk>/ativo/", views.servidor_alternar, name="servidor_alternar"),
    path("cidadaos/", views.cidadaos, name="cidadaos"),
    path("cidadaos/<int:pk>/ativo/", views.cidadao_alternar, name="cidadao_alternar"),
]
