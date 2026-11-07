from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied

ADMIN = "administrador"
OPERADOR = "operador"
LEITOR = "leitor"

TODOS = (ADMIN, OPERADOR, LEITOR)
ESCRITA = (ADMIN, OPERADOR)


def perfil_do_usuario(user):
    """Retorna o perfil do usuário ou None se não tiver nenhum."""
    if not user.is_authenticated:
        return None
    if user.is_superuser:
        return ADMIN
    grupos = set(user.groups.values_list("name", flat=True))
    for perfil in (ADMIN, OPERADOR, LEITOR):
        if perfil in grupos:
            return perfil
    return None


def perfil_requerido(*perfis):
    """Bloqueia a view no backend se o perfil não for permitido (HTTP 403)."""
    def decorator(view):
        @login_required
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if perfil_do_usuario(request.user) not in perfis:
                raise PermissionDenied
            return view(request, *args, **kwargs)
        return wrapper
    return decorator
