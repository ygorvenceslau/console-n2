from django.shortcuts import render

from .permissoes import TODOS, perfil_requerido


@perfil_requerido(*TODOS)
def visao_geral(request):
    return render(request, "painel/visao_geral.html", {"pagina": "visao_geral"})


def _em_construcao(nome, titulo, etapa):
    @perfil_requerido(*TODOS)
    def view(request):
        return render(request, "painel/em_construcao.html",
                      {"pagina": nome, "titulo": titulo, "etapa": etapa})
    view.__name__ = nome
    return view


servicos = _em_construcao("servicos", "Serviços", 3)
arquivos = _em_construcao("arquivos", "Arquivos (FTP)", 4)
email = _em_construcao("email", "E-mail", 5)
ssh = _em_construcao("ssh", "Acesso SSH", 6)
logs = _em_construcao("logs", "Logs técnicos", 7)


# ---------- Etapa 3: métricas ----------
import logging

from django.http import JsonResponse

from .integracoes.metricas import coletar_tudo

logger = logging.getLogger(__name__)


@perfil_requerido(*TODOS)
def api_metricas(request):
    try:
        return JsonResponse({"ok": True, **coletar_tudo()})
    except Exception:
        logger.exception("Falha na coleta de métricas")
        return JsonResponse({"ok": False, "erro": "Falha ao coletar dados do servidor."}, status=503)
