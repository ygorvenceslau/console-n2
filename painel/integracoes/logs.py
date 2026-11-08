"""Consulta de logs técnicos do Debian, somente leitura.
Comandos e caminhos são fixos; a entrada do usuário só escolhe opções de listas fechadas."""
import re
import subprocess
from collections import deque
from pathlib import Path

from django.utils import timezone

POSTFIX = ["-t", "postfix/smtpd", "-t", "postfix/smtp", "-t", "postfix/qmgr",
           "-t", "postfix/local", "-t", "postfix/cleanup", "-t", "postfix/pickup"]

FONTES = {
    "apache-acesso": {"nome": "Apache · acessos HTTP", "arquivo": "/var/log/apache2/access.log"},
    "apache-erros": {"nome": "Apache · erros", "arquivo": "/var/log/apache2/error.log"},
    "vsftpd": {"nome": "vsftpd · serviço", "journal": ["-u", "vsftpd"]},
    "vsftpd-transf": {"nome": "vsftpd · transferências", "arquivo": "/var/log/vsftpd.log"},
    "postfix": {"nome": "Postfix · SMTP", "journal": POSTFIX},
    "dovecot": {"nome": "Dovecot · IMAP", "journal": ["-u", "dovecot"]},
    "ssh": {"nome": "OpenSSH · SSH", "journal": ["-u", "ssh"]},
}
LINHAS = [20, 50, 100, 200]
PERIODOS = {
    "10min": ("últimos 10 minutos", "10 minutes ago"),
    "1h": ("última hora", "1 hour ago"),
    "24h": ("últimas 24 horas", "24 hours ago"),
    "tudo": ("sem limite de tempo", None),
}
LIMITE_LEITURA = 2000
PALAVRAS_ALERTA = re.compile(r"(?i)\b(error|erro|fail\w*|denied|refused|reject\w*|warn\w*|invalid|not allowed)\b")
MASCARA = re.compile(r"(?i)\b(pass(?:word)?|senha|pwd|secret|token)(\s*[=:]\s*)\S+")


class ErroLogs(Exception):
    """Erro com mensagem segura para o usuário."""


def _mascarar(linha):
    return MASCARA.sub(lambda m: m.group(1) + m.group(2) + "***", linha)


def _ler_arquivo(caminho):
    p = Path(caminho)
    if not p.exists():
        raise ErroLogs(f"O arquivo {caminho} não existe nesta instalação.")
    try:
        with p.open("r", encoding="utf-8", errors="replace") as f:
            return list(deque(f, maxlen=LIMITE_LEITURA))
    except PermissionError as e:
        raise ErroLogs(f"Sem permissão de leitura em {caminho} (o usuário do console precisa do grupo adm).") from e


def _ler_journal(seletor, desde):
    comando = ["journalctl", *seletor, "-n", str(LIMITE_LEITURA), "--no-pager", "-o", "short-iso"]
    if desde:
        comando += ["--since", desde]
    try:
        r = subprocess.run(comando, capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise ErroLogs("Falha ao consultar o journal do sistema (tempo esgotado ou comando indisponível).") from e
    if "insufficient permissions" in r.stderr or "not seeing messages" in r.stderr:
        raise ErroLogs("Sem permissão para ler o journal (o usuário do console precisa do grupo systemd-journal).")
    if r.returncode != 0:
        raise ErroLogs("O journalctl retornou erro ao consultar os registros.")
    return r.stdout.splitlines()


def consultar(fonte, linhas, periodo, busca):
    if fonte not in FONTES:
        raise ErroLogs("Serviço inválido.")
    if linhas not in LINHAS:
        linhas = 50
    if periodo not in PERIODOS:
        periodo = "1h"
    busca = (busca or "").strip()[:50]
    f = FONTES[fonte]

    if "arquivo" in f:
        brutas = _ler_arquivo(f["arquivo"])
        origem, periodo_aplicado = f["arquivo"], False
    else:
        brutas = _ler_journal(f["journal"], PERIODOS[periodo][1])
        origem, periodo_aplicado = "journalctl " + " ".join(f["journal"]), True

    brutas = [l.rstrip("\n") for l in brutas if l.strip() and not l.startswith("-- ")]
    if busca:
        brutas = [l for l in brutas if busca.lower() in l.lower()]
    selecionadas = brutas[-linhas:]
    return {
        "linhas": [{"texto": _mascarar(l), "alerta": bool(PALAVRAS_ALERTA.search(l))} for l in selecionadas],
        "total": len(brutas),
        "exibidas": len(selecionadas),
        "origem": origem,
        "periodo_aplicado": periodo_aplicado,
        "instante": timezone.localtime().strftime("%d/%m/%Y %H:%M:%S"),
    }
