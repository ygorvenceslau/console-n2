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


class EstadoHostname(models.Model):
    """Guarda o hostname original antes de uma alteração temporária pelo console."""
    original = models.CharField(max_length=63, blank=True)
    valor_teste = models.CharField(max_length=63, blank=True)
    alterado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                     on_delete=models.SET_NULL, related_name="+")
    alterado_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "estado do hostname"
        verbose_name_plural = "estado do hostname"

    @classmethod
    def atual(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    @property
    def pendente(self):
        """True quando há uma alteração ainda não restaurada."""
        return bool(self.original)
