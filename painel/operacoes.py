"""Operações recentes da sessão (Parte 1). A auditoria persistente fica para a Parte 2."""
from django.utils import timezone

MAXIMO = 20


def registrar(request, modulo, descricao, situacao, detalhe=""):
    ops = request.session.get("operacoes", [])
    ops.insert(0, {
        "instante": timezone.localtime().strftime("%H:%M:%S"),
        "modulo": modulo,
        "descricao": descricao,
        "situacao": situacao,       # em andamento | concluída | falha
        "detalhe": str(detalhe)[:200],
    })
    request.session["operacoes"] = ops[:MAXIMO]


def listar(request):
    return request.session.get("operacoes", [])
