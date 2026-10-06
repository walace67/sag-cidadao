from django.urls import path

from . import views

app_name = "doisfatores"

urlpatterns = [
    path("", views.situacao, name="situacao"),
    path("verificar/", views.verificar, name="verificar"),
    path("configurar/", views.configurar, name="configurar"),
    path("trocar/", views.trocar, name="trocar"),
    path("codigos/", views.novos_codigos, name="novos_codigos"),
    path("desativar/", views.desativar, name="desativar"),
]
