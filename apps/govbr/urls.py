from django.urls import path

from . import views

app_name = "govbr"

urlpatterns = [
    path("entrar/", views.entrar, name="entrar"),
    path("retorno/", views.retorno, name="retorno"),
    path("completar/", views.completar, name="completar"),
]
