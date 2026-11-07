"""Coleta de métricas e estados dos serviços do Debian."""
import socket
import subprocess
import time
import urllib.error
import urllib.request

import psutil
from django.conf import settings
from django.utils import timezone

# (unidade systemd, nome exibido, porta)
SERVICOS = [
    ("apache2", "Apache · HTTP", 80),
    ("vsftpd", "vsftpd · FTP", 21),
    ("postfix", "Postfix · SMTP", 25),
    ("dovecot", "Dovecot · IMAP", 143),
    ("ssh", "OpenSSH · SSH", 22),
]
ESTADOS = {"active": "ativo", "inactive": "inativo", "failed": "falha"}


def agora():
    return timezone.localtime().strftime("%d/%m/%Y %H:%M:%S")


def coletar_sistema():
    """CPU: % de uso médio de todos os núcleos numa janela de 0,5 s.
    Memória usada = total - disponível (o que realmente está ocupado)."""
    mem = psutil.virtual_memory()
    discos = []
    for ponto in settings.CONSOLE_DISCOS:
        try:
            d = psutil.disk_usage(ponto)
            discos.append({
                "ponto": ponto,
                "total_gb": round(d.total / 1024**3, 1),
                "usado_gb": round(d.used / 1024**3, 1),
                "percentual": d.percent,
            })
        except OSError:
            discos.append({"ponto": ponto, "erro": "caminho não encontrado"})
    return {
        "cpu_percentual": psutil.cpu_percent(interval=0.5),
        "memoria": {
            "total_mb": mem.total // 1024**2,
            "disponivel_mb": mem.available // 1024**2,
            "usada_mb": (mem.total - mem.available) // 1024**2,
            "percentual": mem.percent,
        },
        "discos": discos,
        "uptime_s": int(time.time() - psutil.boot_time()),
    }


def estado_servico(unidade):
    """Lê o estado pelo systemd. Se a consulta falhar: 'desconhecido' (não 'parado')."""
    try:
        r = subprocess.run(
            ["systemctl", "show", unidade, "-p", "LoadState", "-p", "ActiveState", "-p", "SubState"],
            capture_output=True, text=True, timeout=5, check=False,
        )
        dados = dict(linha.split("=", 1) for linha in r.stdout.splitlines() if "=" in linha)
    except (OSError, subprocess.TimeoutExpired):
        return {"estado": "desconhecido", "detalhe": "falha na consulta"}
    if dados.get("LoadState") != "loaded":
        return {"estado": "desconhecido", "detalhe": f"unidade {dados.get('LoadState', '?')}"}
    ativo = dados.get("ActiveState", "?")
    return {"estado": ESTADOS.get(ativo, "desconhecido"),
            "detalhe": f"{ativo} ({dados.get('SubState', '?')})"}


def porta_aberta(ip, porta):
    """Testa se a porta aceita conexão TCP, com a duração do teste."""
    inicio = time.perf_counter()
    try:
        with socket.create_connection((ip, porta), timeout=3):
            ok = True
    except OSError:
        ok = False
    return {"aberta": ok, "duracao_ms": round((time.perf_counter() - inicio) * 1000, 1),
            "instante": agora()}


def testar_http():
    """Requisição HTTP ao site, medida a partir do backend (Debian)."""
    url = settings.CONSOLE_SITE_URL
    instante = agora()
    inicio = time.perf_counter()
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            resp.read()
            codigo = resp.status
    except urllib.error.HTTPError as e:
        codigo = e.code
    except (urllib.error.URLError, OSError) as e:
        return {"url": url, "ok": False, "codigo": None, "duracao_ms": None,
                "instante": instante, "ponto_medicao": "backend no Debian",
                "erro": str(getattr(e, "reason", e))}
    return {"url": url, "ok": 200 <= codigo < 400, "codigo": codigo,
            "duracao_ms": round((time.perf_counter() - inicio) * 1000, 1),
            "instante": instante, "ponto_medicao": "backend no Debian"}


def coletar_tudo():
    ip = settings.CONSOLE_SERVIDOR_IP
    servicos = []
    for unidade, nome, porta in SERVICOS:
        item = {"unidade": unidade, "nome": nome, "porta": porta}
        item.update(estado_servico(unidade))
        item["teste_porta"] = porta_aberta(ip, porta)
        servicos.append(item)
    return {
        "servidor": {"hostname": socket.gethostname(), "ip": ip},
        "coletado_em": agora(),
        "sistema": coletar_sistema(),
        "servicos": servicos,
        "http": testar_http(),
    }
