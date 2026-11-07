"""Integração de correio: SMTP (Postfix) para enviar e IMAP (Dovecot) para consultar.
O console nunca lê os Maildirs no disco: tudo passa pelos protocolos."""
import imaplib
import os
import re
import smtplib
import time
from contextlib import contextmanager
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import formatdate, make_msgid

from django.conf import settings


class ErroCorreio(Exception):
    """Erro com mensagem segura para o usuário (sem senhas)."""


class ErroEnvio(ErroCorreio):
    """O SMTP não aceitou a mensagem: ela NÃO foi enviada."""


def _senha(conta):
    senha = os.environ.get(f"CONSOLE_EMAIL_SENHA_{conta.usuario_imap.upper()}")
    if not senha:
        raise ErroCorreio(f"Senha da conta {conta.endereco} não configurada no servidor.")
    return senha


def _pasta_valida(pasta):
    if pasta not in settings.CONSOLE_EMAIL_PASTAS:
        raise ErroCorreio("Pasta inválida.")
    return pasta


def validar_destinatario(endereco):
    endereco = (endereco or "").strip().lower()
    dominio = re.escape(settings.CONSOLE_EMAIL_DOMINIO)
    if not re.fullmatch(rf"[a-z0-9][a-z0-9._+-]{{0,63}}@{dominio}", endereco):
        raise ErroCorreio(f"Destinatário inválido. Use um endereço @{settings.CONSOLE_EMAIL_DOMINIO}.")
    return endereco


def validar_texto(assunto, corpo):
    assunto = (assunto or "").strip()
    corpo = (corpo or "").strip()
    if not assunto:
        raise ErroCorreio("Informe o assunto.")
    if len(assunto) > 150 or "\r" in assunto or "\n" in assunto:
        raise ErroCorreio("Assunto inválido (máximo de 150 caracteres, sem quebras de linha).")
    if not corpo:
        raise ErroCorreio("Escreva a mensagem.")
    if len(corpo) > 10000:
        raise ErroCorreio("Mensagem longa demais (máximo de 10.000 caracteres).")
    return assunto, corpo


@contextmanager
def imap(conta):
    host = settings.CONSOLE_EMAIL_HOST
    try:
        M = imaplib.IMAP4(host, 143, timeout=10)
    except OSError as e:
        raise ErroCorreio(f"Não foi possível conectar ao IMAP em {host}:143.") from e
    try:
        try:
            M.login(conta.usuario_imap, _senha(conta))
        except imaplib.IMAP4.error as e:
            raise ErroCorreio(f"O Dovecot recusou o login da conta {conta.endereco}.") from e
        yield M
    finally:
        try:
            M.logout()
        except (imaplib.IMAP4.error, OSError):
            pass


def _cabecalhos(bruto):
    return BytesParser(policy=policy.default).parsebytes(bruto, headersonly=True)


def listar(conta, pasta, limite=30):
    pasta = _pasta_valida(pasta)
    try:
        with imap(conta) as M:
            tipo, _ = M.select(pasta, readonly=True)
            if tipo != "OK":
                raise ErroCorreio(f"Pasta {pasta} não encontrada no servidor.")
            tipo, dados = M.uid("SEARCH", None, "ALL")
            uids = dados[0].split()[-limite:][::-1]
            if not uids:
                return []
            tipo, dados = M.uid("FETCH", b",".join(uids),
                                "(UID FLAGS BODY.PEEK[HEADER.FIELDS (FROM TO SUBJECT DATE)])")
    except ErroCorreio:
        raise
    except (imaplib.IMAP4.error, OSError) as e:
        raise ErroCorreio("Falha ao consultar as mensagens por IMAP.") from e

    mensagens = []
    for item in dados:
        if not isinstance(item, tuple):
            continue
        info, bruto = item
        uid = re.search(rb"UID (\d+)", info)
        flags = re.search(rb"FLAGS \(([^)]*)\)", info)
        h = _cabecalhos(bruto)
        mensagens.append({
            "uid": uid.group(1).decode() if uid else "",
            "lida": bool(flags and b"\\Seen" in flags.group(1)),
            "de": str(h.get("From", "")),
            "para": str(h.get("To", "")),
            "assunto": str(h.get("Subject", "(sem assunto)")),
            "data": str(h.get("Date", "")),
        })
    mensagens.sort(key=lambda m: int(m["uid"] or 0), reverse=True)
    return mensagens


def ler(conta, pasta, uid, marcar_lida=True):
    pasta = _pasta_valida(pasta)
    if not str(uid).isdigit():
        raise ErroCorreio("Mensagem inválida.")
    try:
        with imap(conta) as M:
            M.select(pasta, readonly=not marcar_lida)   # leitor apenas consulta
            tipo, dados = M.uid("FETCH", str(uid), "(RFC822)")
    except ErroCorreio:
        raise
    except (imaplib.IMAP4.error, OSError) as e:
        raise ErroCorreio("Falha ao abrir a mensagem por IMAP.") from e
    brutos = [d for d in dados if isinstance(d, tuple)]
    if tipo != "OK" or not brutos:
        raise ErroCorreio("Mensagem não encontrada.")
    msg = BytesParser(policy=policy.default).parsebytes(brutos[0][1])
    parte = msg.get_body(preferencelist=("plain",))
    corpo = parte.get_content() if parte else "(mensagem sem parte de texto simples)"
    return {
        "uid": str(uid), "pasta": pasta,
        "de": str(msg.get("From", "")), "para": str(msg.get("To", "")),
        "assunto": str(msg.get("Subject", "(sem assunto)")), "data": str(msg.get("Date", "")),
        "message_id": str(msg.get("Message-ID", "")),
        "references": str(msg.get("References", "")),
        "corpo": corpo,
    }


def montar(conta, para, assunto, corpo, em_resposta_a="", referencias=""):
    """Monta a mensagem. O remetente é SEMPRE a conta selecionada (sem falsificação)."""
    para = validar_destinatario(para)
    assunto, corpo = validar_texto(assunto, corpo)
    msg = EmailMessage()
    msg["From"] = conta.endereco
    msg["To"] = para
    msg["Subject"] = assunto
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=settings.CONSOLE_EMAIL_DOMINIO)
    if em_resposta_a:
        msg["In-Reply-To"] = em_resposta_a
        msg["References"] = (referencias + " " + em_resposta_a).strip()
    msg.set_content(corpo, cte="quoted-printable")
    return msg


def enviar_smtp(conta, msg):
    """Etapa 1: entrega ao Postfix. Retorna a resposta do servidor (ex.: '250 2.0.0 Ok: queued as ...')."""
    bruto = msg.as_bytes(policy=policy.SMTP)
    try:
        with smtplib.SMTP(settings.CONSOLE_EMAIL_HOST, 25, timeout=15) as s:
            s.ehlo()
            codigo, resp = s.mail(conta.endereco)
            if codigo != 250:
                raise ErroEnvio(f"Remetente recusado pelo SMTP ({codigo}).")
            codigo, resp = s.rcpt(msg["To"])
            if codigo not in (250, 251):
                raise ErroEnvio(f"Destinatário recusado pelo SMTP ({codigo} {resp.decode(errors='replace')}).")
            codigo, resp = s.data(bruto)
            if codigo != 250:
                raise ErroEnvio(f"Mensagem recusada pelo SMTP ({codigo}).")
            return f"{codigo} {resp.decode(errors='replace')}"
    except ErroEnvio:
        raise
    except (smtplib.SMTPException, OSError) as e:
        raise ErroEnvio(f"Falha de comunicação com o SMTP em {settings.CONSOLE_EMAIL_HOST}:25.") from e


def salvar_enviados(conta, bruto):
    """Etapa 2: grava a cópia na pasta Enviados por IMAP APPEND. Não reenvia nada."""
    pasta = settings.CONSOLE_EMAIL_PASTA_ENVIADOS
    try:
        with imap(conta) as M:
            tipo, resp = M.append(pasta, r"(\Seen)", imaplib.Time2Internaldate(time.time()), bruto)
            if tipo != "OK":
                raise ErroCorreio(f"O IMAP recusou a gravação em {pasta}.")
            return resp[0].decode(errors="replace") if resp and resp[0] else "OK"
    except ErroCorreio:
        raise
    except (imaplib.IMAP4.error, OSError) as e:
        raise ErroCorreio(f"Falha ao gravar a cópia em {pasta} por IMAP.") from e
