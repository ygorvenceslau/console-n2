from django.conf import settings
from django.db import models


class ContaCorreio(models.Model):
    """Conta de correio de teste que o console pode usar.
    A senha NÃO fica no banco: vem do .env (CONSOLE_EMAIL_SENHA_<USUARIO>)."""
    usuario_imap = models.CharField("usuário IMAP", max_length=50, unique=True)
    endereco = models.EmailField("endereço", unique=True)
    usuarios_autorizados = models.ManyToManyField(
        settings.AUTH_USER_MODEL, blank=True, related_name="contas_correio",
        verbose_name="usuários do console autorizados")

    class Meta:
        verbose_name = "conta de correio"
        verbose_name_plural = "contas de correio"
        ordering = ["endereco"]

    def __str__(self):
        return self.endereco
