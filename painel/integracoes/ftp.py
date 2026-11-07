"""Integração com o vsftpd usando ftplib.
O console NUNCA copia arquivos direto no disco: tudo passa pelo protocolo FTP."""
import hashlib
import io
import re
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from ftplib import FTP, all_errors, error_perm

from django.conf import settings

# Só letras, números, ponto, hífen e sublinhado. Sem barras, espaços ou "..".
NOME_VALIDO = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")


class ErroFTP(Exception):
    """Erro com mensagem segura para mostrar ao usuário (sem senhas)."""


def sha256(dados):
    return hashlib.sha256(dados).hexdigest()


def validar_nome(nome):
    nome = (nome or "").strip()
    if not NOME_VALIDO.match(nome) or ".." in nome:
        raise ErroFTP("Nome de arquivo inválido. Use apenas letras, números, ponto, hífen ou "
                      "sublinhado (sem espaços, acentos ou barras).")
    extensao = "." + nome.rsplit(".", 1)[-1].lower() if "." in nome else ""
    if extensao not in settings.CONSOLE_FTP_EXTENSOES:
        raise ErroFTP("Tipo de arquivo não permitido. Permitidos: "
                      + ", ".join(sorted(settings.CONSOLE_FTP_EXTENSOES)))
    return nome


def url_publica(nome):
    return settings.CONSOLE_SITE_ARQUIVOS_URL + urllib.parse.quote(nome)


@contextmanager
def conexao():
    host = settings.CONSOLE_FTP_HOST
    try:
        ftp = FTP(host, timeout=15)
        ftp.login(settings.CONSOLE_FTP_USUARIO, settings.CONSOLE_FTP_SENHA)
        ftp.cwd(settings.CONSOLE_FTP_DIR)
    except error_perm as e:
        raise ErroFTP(f"O vsftpd recusou o acesso (código {str(e)[:3]}).") from e
    except all_errors as e:
        raise ErroFTP(f"Não foi possível conectar ao vsftpd em {host}:21.") from e
    try:
        yield ftp
    finally:
        try:
            ftp.quit()
        except all_errors:
            ftp.close()


def _nomes(ftp):
    try:
        return [n.rsplit("/", 1)[-1] for n in ftp.nlst()]
    except error_perm:          # alguns servidores respondem 550 para pasta vazia
        return []


def listar():
    try:
        with conexao() as ftp:
            ftp.voidcmd("TYPE I")
            arquivos = []
            for nome in sorted(_nomes(ftp)):
                if nome in (".", ".."):
                    continue
                try:
                    tamanho = ftp.size(nome)
                except error_perm:      # é diretório
                    continue
                try:
                    t = ftp.voidcmd(f"MDTM {nome}")[4:].strip()
                    modificado = f"{t[6:8]}/{t[4:6]}/{t[0:4]} {t[8:10]}:{t[10:12]} UTC"
                except all_errors:
                    modificado = "—"
                arquivos.append({"nome": nome, "tamanho": tamanho,
                                 "modificado": modificado, "url_http": url_publica(nome)})
            return arquivos
    except ErroFTP:
        raise
    except all_errors as e:
        raise ErroFTP("Falha ao listar os arquivos pelo FTP.") from e


def enviar(arquivo):
    """Recebe o arquivo do formulário e transfere ao vsftpd com STOR."""
    nome = validar_nome(arquivo.name)
    if arquivo.size == 0:
        raise ErroFTP("O arquivo está vazio.")
    if arquivo.size > settings.CONSOLE_FTP_MAX_MB * 1024 * 1024:
        raise ErroFTP(f"Arquivo maior que o limite de {settings.CONSOLE_FTP_MAX_MB} MB.")

    h = hashlib.sha256()
    for parte in arquivo.chunks():
        h.update(parte)
    arquivo.seek(0)

    try:
        with conexao() as ftp:
            if nome in _nomes(ftp):
                raise ErroFTP(f"Já existe um arquivo chamado {nome}. Renomeie antes de enviar.")
            resposta = ftp.storbinary(f"STOR {nome}", arquivo)
            tamanho_remoto = ftp.size(nome)
    except ErroFTP:
        raise
    except all_errors as e:
        raise ErroFTP("Falha durante a transferência FTP.") from e

    return {"nome": nome, "tamanho": arquivo.size, "tamanho_remoto": tamanho_remoto,
            "sha256_local": h.hexdigest(), "resposta_ftp": resposta}


def baixar(nome):
    """Recupera o arquivo pelo FTP (RETR) e devolve os bytes."""
    nome = validar_nome(nome)
    buffer = io.BytesIO()
    try:
        with conexao() as ftp:
            ftp.retrbinary(f"RETR {nome}", buffer.write)
    except ErroFTP:
        raise
    except error_perm as e:
        raise ErroFTP(f"Arquivo {nome} não encontrado no FTP.") from e
    except all_errors as e:
        raise ErroFTP("Falha ao baixar o arquivo pelo FTP.") from e
    return buffer.getvalue()


def verificar(nome, sha_local=None):
    """Compara o hash do arquivo: enviado (local) x recuperado por FTP x publicado por HTTP."""
    nome = validar_nome(nome)
    dados_ftp = baixar(nome)
    r = {"nome": nome, "url_http": url_publica(nome), "sha256_local": sha_local,
         "sha256_ftp": sha256(dados_ftp), "tamanho_ftp": len(dados_ftp),
         "http_codigo": None, "sha256_http": None}
    try:
        with urllib.request.urlopen(url_publica(nome), timeout=10) as resp:
            dados_http = resp.read()
            r.update(http_codigo=resp.status, sha256_http=sha256(dados_http),
                     tamanho_http=len(dados_http))
    except urllib.error.HTTPError as e:
        r["http_codigo"] = e.code
    except (urllib.error.URLError, OSError) as e:
        r["erro_http"] = str(getattr(e, "reason", e))
    hashes = {h for h in (sha_local, r["sha256_ftp"], r["sha256_http"]) if h}
    r["integro"] = r["sha256_http"] is not None and len(hashes) == 1
    return r
