"""Integração SSH com o OpenSSH usando paramiko.
- Conta técnica console-ssh, autenticada só por chave (a chave fica no backend).
- Identidade do servidor verificada pelo known_hosts (RejectPolicy: servidor desconhecido = recusa).
- Executa apenas comandos predefinidos; o nome é validado e passa por shlex.quote."""
import re
import shlex
from contextlib import contextmanager

import paramiko
from django.conf import settings

NOME_VALIDO = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")
SCRIPT = "sudo -n /usr/local/sbin/console-hostname"


class ErroSSH(Exception):
    """Erro com mensagem segura para o usuário (sem chaves ou caminhos sensíveis)."""


def validar_nome(nome):
    nome = (nome or "").strip()
    if not NOME_VALIDO.match(nome):
        raise ErroSSH("Nome inválido. Use letras minúsculas, números e hífen (1 a 63 caracteres), "
                      "sem começar ou terminar com hífen.")
    return nome


@contextmanager
def conexao():
    cliente = paramiko.SSHClient()
    try:
        cliente.load_host_keys(settings.CONSOLE_SSH_KNOWN_HOSTS)
    except OSError as e:
        raise ErroSSH("Arquivo de identidade do servidor (known_hosts) não encontrado no backend.") from e
    cliente.set_missing_host_key_policy(paramiko.RejectPolicy())
    host = settings.CONSOLE_SSH_HOST
    try:
        cliente.connect(host, port=22, username=settings.CONSOLE_SSH_USUARIO,
                        key_filename=settings.CONSOLE_SSH_CHAVE, allow_agent=False, look_for_keys=False,
                        timeout=10, banner_timeout=10, auth_timeout=10)
    except paramiko.BadHostKeyException as e:
        raise ErroSSH("A identidade do servidor NÃO confere com a registrada. Conexão recusada.") from e
    except paramiko.AuthenticationException as e:
        raise ErroSSH("O servidor recusou a autenticação da conta técnica.") from e
    except paramiko.SSHException as e:
        raise ErroSSH("Falha na negociação SSH (servidor não reconhecido ou indisponível).") from e
    except OSError as e:
        raise ErroSSH(f"Não foi possível conectar ao SSH em {host}:22.") from e
    try:
        yield cliente
    finally:
        cliente.close()


def _executar(cliente, comando):
    try:
        _, stdout, stderr = cliente.exec_command(comando, timeout=15)
        saida = stdout.read().decode(errors="replace").strip()
        erro = stderr.read().decode(errors="replace").strip()
        codigo = stdout.channel.recv_exit_status()
    except (paramiko.SSHException, OSError) as e:
        raise ErroSSH("A execução remota excedeu o tempo ou foi interrompida.") from e
    return codigo, saida, erro


def _hostname(cliente):
    codigo, saida, erro = _executar(cliente, f"{SCRIPT} get")
    if codigo != 0 or not saida:
        raise ErroSSH("Não foi possível consultar o hostname pela operação autorizada.")
    return saida.splitlines()[-1].strip()


def consultar():
    """Identifica usuário remoto e servidor por uma conexão SSH real."""
    with conexao() as c:
        chave = c.get_transport().get_remote_server_key()
        codigo, saida, _ = _executar(c, "whoami; uname -srm; uptime -p; date '+%d/%m/%Y %H:%M:%S'")
        hostname = _hostname(c)
    linhas = (saida.splitlines() + ["?"] * 4)[:4]
    return {
        "usuario_remoto": linhas[0], "kernel": linhas[1], "uptime": linhas[2], "data_servidor": linhas[3],
        "hostname": hostname, "host": settings.CONSOLE_SSH_HOST,
        "chave_tipo": chave.get_name(), "chave_fingerprint": chave.fingerprint,
    }


def definir_hostname(novo):
    """Altera o hostname pela operação predefinida e confirma lendo de volta."""
    novo = validar_nome(novo)
    with conexao() as c:
        anterior = _hostname(c)
        codigo, _, erro = _executar(c, f"{SCRIPT} set {shlex.quote(novo)}")
        if codigo != 0:
            linhas = [l for l in erro.splitlines() if "ERRO" in l]
            raise ErroSSH("O servidor recusou a alteração. " + (linhas[-1] if linhas else ""))
        atual = _hostname(c)
    return {"anterior": anterior, "atual": atual, "confirmado": atual == novo}
