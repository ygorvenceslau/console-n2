from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

urlpatterns = [
    path("login/", auth_views.LoginView.as_view(
        template_name="painel/login.html",
        redirect_authenticated_user=True), name="login"),
    path("sair/", auth_views.LogoutView.as_view(), name="sair"),
    path("", views.visao_geral, name="visao_geral"),
    path("servicos/", views.servicos, name="servicos"),
    path("arquivos/", views.arquivos, name="arquivos"),
    path("email/", views.email, name="email"),
    path("ssh/", views.ssh, name="ssh"),
    path("logs/", views.logs, name="logs"),
]
