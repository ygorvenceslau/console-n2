from django.contrib import admin

from .models import ContaCorreio


@admin.register(ContaCorreio)
class ContaCorreioAdmin(admin.ModelAdmin):
    list_display = ("endereco", "usuario_imap")
    filter_horizontal = ("usuarios_autorizados",)
