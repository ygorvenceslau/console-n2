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


# ---------- Etapa 4: arquivos (FTP) ----------
from django.conf import settings
from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import redirect
from django.views.decorators.http import require_POST

from . import operacoes
from .integracoes import ftp as ftp_int
from .permissoes import ESCRITA, perfil_do_usuario


def _contexto_arquivos(request):
    ext = sorted(settings.CONSOLE_FTP_EXTENSOES)
    return {
        "pagina": "arquivos",
        "pode_enviar": perfil_do_usuario(request.user) in ESCRITA,
        "extensoes": ", ".join(ext),
        "extensoes_lista": ext,
        "extensoes_accept": ",".join(ext),
        "max_mb": settings.CONSOLE_FTP_MAX_MB,
        "url_site": settings.CONSOLE_SITE_ARQUIVOS_URL,
    }


@perfil_requerido(*TODOS)
def arquivos(request):
    ctx = _contexto_arquivos(request)
    try:
        ctx["arquivos"], ctx["erro"] = ftp_int.listar(), None
    except ftp_int.ErroFTP as e:
        ctx["arquivos"], ctx["erro"] = [], str(e)
    return render(request, "painel/arquivos.html", ctx)


@require_POST
@perfil_requerido(*ESCRITA)          # leitor recebe 403 mesmo acessando a rota direto
def arquivos_enviar(request):
    arquivo = request.FILES.get("arquivo")
    if not arquivo:
        return JsonResponse({"ok": False, "erro": "Selecione um arquivo."}, status=400)
    try:
        r = ftp_int.enviar(arquivo)
    except ftp_int.ErroFTP as e:
        operacoes.registrar(request, "FTP", f"Envio de {arquivo.name[:80]}", "falha", e)
        return JsonResponse({"ok": False, "erro": str(e)}, status=400)
    try:
        v = ftp_int.verificar(r["nome"], r["sha256_local"])
    except ftp_int.ErroFTP as e:
        v = {"integro": False, "erro_http": str(e), "url_http": ftp_int.url_publica(r["nome"])}
    situacao = "concluída" if v["integro"] else "concluída com alerta"
    operacoes.registrar(request, "FTP", f"Envio de {r['nome']} ({r['tamanho']} bytes)", situacao, r["resposta_ftp"])
    return JsonResponse({"ok": True, **r, "verificacao": v})


@perfil_requerido(*TODOS)
def arquivos_baixar(request):
    nome = request.GET.get("nome", "")
    try:
        nome = ftp_int.validar_nome(nome)
        dados = ftp_int.baixar(nome)
    except ftp_int.ErroFTP as e:
        operacoes.registrar(request, "FTP", f"Download de {nome[:80]}", "falha", e)
        messages.error(request, str(e))
        return redirect("arquivos")
    operacoes.registrar(request, "FTP", f"Download de {nome}", "concluída", f"{len(dados)} bytes via FTP")
    resposta = HttpResponse(dados, content_type="application/octet-stream")
    resposta["Content-Disposition"] = f'attachment; filename="{nome}"'
    return resposta


@perfil_requerido(*TODOS)
def arquivos_verificar(request):
    nome = request.GET.get("nome", "")
    try:
        v = ftp_int.verificar(nome)
    except ftp_int.ErroFTP as e:
        return JsonResponse({"ok": False, "erro": str(e)}, status=400)
    operacoes.registrar(request, "FTP", f"Verificação de {v['nome']}",
                        "concluída" if v["integro"] else "falha",
                        "hashes FTP e HTTP coincidem" if v["integro"] else "hashes divergentes ou HTTP indisponível")
    return JsonResponse({"ok": True, **v})
