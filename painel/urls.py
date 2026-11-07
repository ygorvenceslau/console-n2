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
    path("api/metricas/", views.api_metricas, name="api_metricas"),
    path("ssh/alterar/", views.ssh_alterar, name="ssh_alterar"),
    path("ssh/restaurar/", views.ssh_restaurar, name="ssh_restaurar"),
    path("email/nova/", views.email_nova, name="email_nova"),
    path("email/salvar-copia/", views.email_salvar_copia, name="email_salvar_copia"),
    path("arquivos/enviar/", views.arquivos_enviar, name="arquivos_enviar"),
    path("arquivos/baixar/", views.arquivos_baixar, name="arquivos_baixar"),
    path("arquivos/verificar/", views.arquivos_verificar, name="arquivos_verificar"),
]
