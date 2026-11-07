from django.conf import settings

from .permissoes import perfil_do_usuario

MENU = [
    ("visao_geral", "Visão geral"),
    ("servicos", "Serviços"),
    ("arquivos", "Arquivos (FTP)"),
    ("email", "E-mail"),
    ("ssh", "Acesso SSH"),
    ("logs", "Logs técnicos"),
]


def console(request):
    return {
        "perfil": perfil_do_usuario(request.user),
        "menu": MENU,
        "servidor_nome": settings.CONSOLE_SERVIDOR_NOME,
        "servidor_ip": settings.CONSOLE_SERVIDOR_IP,
    }
