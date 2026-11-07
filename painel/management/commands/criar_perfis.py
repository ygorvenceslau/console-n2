from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand

from painel.permissoes import ADMIN, LEITOR, OPERADOR


class Command(BaseCommand):
    help = "Cria os grupos de perfil do console (administrador, operador, leitor)"

    def handle(self, *args, **options):
        for nome in (ADMIN, OPERADOR, LEITOR):
            _, criado = Group.objects.get_or_create(name=nome)
            self.stdout.write(f"{nome}: {'criado' if criado else 'já existia'}")
