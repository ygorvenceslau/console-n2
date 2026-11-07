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


# ---------- Etapa 5: e-mail (SMTP + IMAP) ----------
import base64
from email import policy as email_policy
from email.utils import parseaddr

from django.core.exceptions import PermissionDenied
from django.urls import reverse

from .integracoes import correio
from .models import ContaCorreio
from .permissoes import ADMIN


def _contas_permitidas(user):
    if perfil_do_usuario(user) == ADMIN:
        return ContaCorreio.objects.all()
    return user.contas_correio.all()


def _conta_selecionada(request, conta_id):
    """Só devolve contas autorizadas ao usuário. Outra conta = 403 (verificação no backend)."""
    contas = _contas_permitidas(request.user)
    if conta_id in (None, ""):
        return contas.first()
    if not str(conta_id).isdigit():
        raise PermissionDenied
    try:
        return contas.get(pk=int(conta_id))
    except ContaCorreio.DoesNotExist:
        raise PermissionDenied


def _url_email(conta, pasta="INBOX"):
    return f"{reverse('email')}?conta={conta.pk}&pasta={pasta}"


@perfil_requerido(*TODOS)
def email(request):
    conta = _conta_selecionada(request, request.GET.get("conta"))
    pasta = request.GET.get("pasta", "INBOX")
    if pasta not in settings.CONSOLE_EMAIL_PASTAS:
        pasta = "INBOX"
    pode_enviar = perfil_do_usuario(request.user) in ESCRITA
    ctx = {"pagina": "email", "contas": _contas_permitidas(request.user), "conta": conta,
           "pasta": pasta, "pastas": settings.CONSOLE_EMAIL_PASTAS.items(),
           "pode_enviar": pode_enviar, "mensagens": [], "aberta": None, "erro": None, "pendentes": []}
    if conta is None:
        ctx["erro"] = "Nenhuma conta de correio está autorizada para o seu usuário."
        return render(request, "painel/email.html", ctx)
    ctx["pendentes"] = [
        {"id": chave, "assunto": p["assunto"], "para": p["para"]}
        for chave, p in request.session.get("copias_pendentes", {}).items() if p["conta_id"] == conta.pk
    ]
    try:
        ctx["mensagens"] = correio.listar(conta, pasta)
        uid = request.GET.get("uid")
        if uid:
            ctx["aberta"] = correio.ler(conta, pasta, uid, marcar_lida=pode_enviar)
            operacoes.registrar(request, "IMAP", f"Leitura em {conta.endereco} ({pasta})", "concluída",
                                ctx["aberta"]["assunto"])
    except correio.ErroCorreio as e:
        ctx["erro"] = str(e)
        operacoes.registrar(request, "IMAP", f"Consulta a {conta.endereco} ({pasta})", "falha", e)
    return render(request, "painel/email.html", ctx)


@perfil_requerido(*ESCRITA)
def email_nova(request):
    conta = _conta_selecionada(request, request.GET.get("conta") or request.POST.get("conta"))
    if conta is None:
        raise PermissionDenied
    dados = {"para": "", "assunto": "", "corpo": "", "em_resposta_a": "", "referencias": ""}
    erros = {}

    if request.method == "POST":
        for campo in dados:
            dados[campo] = request.POST.get(campo, "")
        try:
            correio.validar_destinatario(dados["para"])
        except correio.ErroCorreio as e:
            erros["para"] = str(e)
        try:
            correio.validar_texto(dados["assunto"], "x")
        except correio.ErroCorreio as e:
            erros["assunto"] = str(e)
        try:
            correio.validar_texto("x", dados["corpo"])
        except correio.ErroCorreio as e:
            erros["corpo"] = str(e)
        for campo in ("em_resposta_a", "referencias"):
            if "\r" in dados[campo] or "\n" in dados[campo] or len(dados[campo]) > 1000:
                erros["geral"] = "Dados da resposta inválidos."

        if not erros:
            msg = correio.montar(conta, dados["para"], dados["assunto"], dados["corpo"],
                                 dados["em_resposta_a"].strip(), dados["referencias"].strip())
            descricao = f"Envio de {conta.endereco} para {msg['To']}: {msg['Subject']}"
            # 1) SMTP
            try:
                resposta_smtp = correio.enviar_smtp(conta, msg)
            except correio.ErroCorreio as e:
                operacoes.registrar(request, "SMTP", descricao, "falha", e)
                erros["geral"] = f"Mensagem NÃO enviada. {e}"
            else:
                operacoes.registrar(request, "SMTP", descricao, "concluída", resposta_smtp)
                bruto = msg.as_bytes(policy=email_policy.SMTP)
                # 2) Cópia em Enviados (IMAP APPEND). Se falhar, NÃO reenvia.
                try:
                    resposta_imap = correio.salvar_enviados(conta, bruto)
                except correio.ErroCorreio as e:
                    pendentes = request.session.get("copias_pendentes", {})
                    pendentes[str(msg["Message-ID"])] = {
                        "conta_id": conta.pk, "assunto": str(msg["Subject"]), "para": str(msg["To"]),
                        "bruto": base64.b64encode(bruto).decode()}
                    request.session["copias_pendentes"] = pendentes
                    operacoes.registrar(request, "IMAP", "Cópia em Enviados", "falha", e)
                    messages.warning(request, f"✔ Mensagem ENVIADA (SMTP: {resposta_smtp}), mas a cópia em "
                                              f"Enviados falhou: {e} Não reenvie: use o botão abaixo.")
                    return redirect(_url_email(conta))
                operacoes.registrar(request, "IMAP", "Cópia em Enviados", "concluída", resposta_imap)
                messages.success(request, f"✔ Mensagem enviada (SMTP: {resposta_smtp}) e cópia salva em Enviados.")
                return redirect(_url_email(conta, settings.CONSOLE_EMAIL_PASTA_ENVIADOS))
    else:
        uid = request.GET.get("responder")
        if uid:
            try:
                original = correio.ler(conta, "INBOX", uid, marcar_lida=True)
            except correio.ErroCorreio as e:
                messages.error(request, str(e))
                return redirect(_url_email(conta))
            assunto = original["assunto"]
            dados["para"] = parseaddr(original["de"])[1]
            dados["assunto"] = assunto if assunto.lower().startswith("re:") else "Re: " + assunto
            citacao = "\n".join("> " + linha for linha in original["corpo"].splitlines())
            dados["corpo"] = f"\n\nEm {original['data']}, {original['de']} escreveu:\n{citacao}"
            dados["em_resposta_a"] = original["message_id"]
            dados["referencias"] = original["references"]

    return render(request, "painel/email_nova.html",
                  {"pagina": "email", "conta": conta, "dados": dados, "erros": erros})


@require_POST
@perfil_requerido(*ESCRITA)
def email_salvar_copia(request):
    """Tenta de novo SOMENTE a gravação em Enviados. A mensagem não é reenviada."""
    pendentes = request.session.get("copias_pendentes", {})
    chave = request.POST.get("id", "")
    item = pendentes.get(chave)
    if not item:
        messages.error(request, "Cópia pendente não encontrada.")
        return redirect("email")
    conta = _conta_selecionada(request, str(item["conta_id"]))
    try:
        resposta = correio.salvar_enviados(conta, base64.b64decode(item["bruto"]))
    except correio.ErroCorreio as e:
        messages.error(request, f"A cópia ainda não pôde ser salva: {e} A mensagem já foi enviada; não reenvie.")
        return redirect(_url_email(conta))
    del pendentes[chave]
    request.session["copias_pendentes"] = pendentes
    operacoes.registrar(request, "IMAP", "Cópia em Enviados (nova tentativa)", "concluída", resposta)
    messages.success(request, "✔ Cópia salva em Enviados. A mensagem não foi reenviada.")
    return redirect(_url_email(conta, settings.CONSOLE_EMAIL_PASTA_ENVIADOS))


# ---------- Etapa 6: SSH e hostname reversível ----------
from django.utils import timezone as dj_timezone

from .integracoes import ssh as ssh_int
from .models import EstadoHostname


@perfil_requerido(*TODOS)
def ssh(request):
    ctx = {"pagina": "ssh", "info": None, "erro": None, "estado": EstadoHostname.atual(),
           "pode_alterar": perfil_do_usuario(request.user) == ADMIN,
           "nome_digitado": "", "erro_nome": None}
    try:
        ctx["info"] = ssh_int.consultar()
        operacoes.registrar(request, "SSH", "Consulta ao servidor", "concluída",
                            f"{ctx['info']['usuario_remoto']}@{ctx['info']['hostname']}")
    except ssh_int.ErroSSH as e:
        ctx["erro"] = str(e)
        operacoes.registrar(request, "SSH", "Consulta ao servidor", "falha", e)
    return render(request, "painel/ssh.html", ctx)


@require_POST
@perfil_requerido(ADMIN)
def ssh_alterar(request):
    estado = EstadoHostname.atual()
    nome = request.POST.get("novo_nome", "").strip()
    try:
        ssh_int.validar_nome(nome)
    except ssh_int.ErroSSH as e:
        ctx = {"pagina": "ssh", "info": None, "erro": None, "estado": estado, "pode_alterar": True,
               "nome_digitado": nome, "erro_nome": str(e)}
        try:
            ctx["info"] = ssh_int.consultar()
        except ssh_int.ErroSSH as e2:
            ctx["erro"] = str(e2)
        return render(request, "painel/ssh.html", ctx)
    try:
        r = ssh_int.definir_hostname(nome)
    except ssh_int.ErroSSH as e:
        operacoes.registrar(request, "SSH", f"Alterar hostname para {nome}", "falha", e)
        messages.error(request, f"✖ {e}")
        return redirect("ssh")
    if not estado.original:                  # guarda o original só na primeira alteração
        estado.original = r["anterior"]
    estado.valor_teste = r["atual"]
    estado.alterado_por = request.user
    estado.alterado_em = dj_timezone.now()
    estado.save()
    situacao = "concluída" if r["confirmado"] else "falha"
    operacoes.registrar(request, "SSH", f"Hostname {r['anterior']} → {r['atual']}", situacao,
                        f"original registrado: {estado.original}")
    if r["confirmado"]:
        messages.success(request, f"✔ Hostname alterado de '{r['anterior']}' para '{r['atual']}' "
                                  f"(confirmado no servidor). Valor original guardado: '{estado.original}'.")
    else:
        messages.error(request, f"✖ O servidor informou '{r['atual']}', diferente do solicitado.")
    return redirect("ssh")


@require_POST
@perfil_requerido(ADMIN)
def ssh_restaurar(request):
    estado = EstadoHostname.atual()
    if not estado.original:
        messages.warning(request, "Não há alteração pendente para restaurar.")
        return redirect("ssh")
    try:
        r = ssh_int.definir_hostname(estado.original)
    except ssh_int.ErroSSH as e:
        operacoes.registrar(request, "SSH", f"Restaurar hostname para {estado.original}", "falha", e)
        messages.error(request, f"✖ {e} O valor original continua guardado: '{estado.original}'.")
        return redirect("ssh")
    if r["confirmado"]:
        operacoes.registrar(request, "SSH", f"Hostname restaurado: {r['anterior']} → {r['atual']}", "concluída")
        messages.success(request, f"✔ Hostname restaurado para '{r['atual']}' (confirmado no servidor).")
        estado.original = ""
        estado.valor_teste = ""
        estado.save()
    else:
        messages.error(request, f"✖ O servidor informou '{r['atual']}'. O original continua guardado.")
    return redirect("ssh")
