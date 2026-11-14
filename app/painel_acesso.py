"""Quem pode o quê no painel "Coletas do BRASIL+". As contas são as mesmas do site (app/contas.py); aqui só entram o papel de painel
e as permissões por seção.

Papéis: "usuario" (conta comum do site: NÃO entra no painel), "leitor" (só olha), "editor" (olha e cadastra fontes) e "admin"
(tudo, inclusive dar acesso). Cada pessoa pode ter permissões próprias por seção (Alterar / Ver / Nenhum) por cima do padrão do papel.
Conta bloqueada não entra NO PAINEL (o login do site, para votar, continua valendo). Só administrador altera acessos: nenhum outro papel chega a "alterar" a seção `acessos`."""
from __future__ import annotations

from app import contas
from app.models import Conta

SECOES = ("painel", "bots", "dados", "ia", "noticias", "instagram", "atividade", "acessos", "correcao")
NIVEIS = ("alterar", "ver", "")
PAPEIS = ("usuario", "leitor", "editor", "admin")
NOMES_PAPEL = {"usuario": "Conta comum (sem acesso ao painel)", "leitor": "Leitor", "editor": "Editor", "admin": "Administrador"}

PADRAO = {
    "admin": {s: "alterar" for s in SECOES},
    "editor": {"painel": "ver", "bots": "alterar", "dados": "ver", "ia": "alterar", "noticias": "ver", "instagram": "ver",
               "atividade": "ver", "acessos": "", "correcao": "alterar"},
    "leitor": {"painel": "ver", "bots": "ver", "dados": "ver", "ia": "ver", "noticias": "ver", "instagram": "ver",
               "atividade": "ver", "acessos": "", "correcao": "ver"},
}


def papel_efetivo(conta: Conta) -> str:
    """"admin" também vale para e-mail em ADMIN_EMAILS (conferido a cada pedido, como no resto do site)."""
    if contas.e_admin(conta):
        return "admin"
    return conta.papel if conta.papel in PAPEIS else "usuario"


def permissoes_padrao(papel: str) -> dict:
    return dict(PADRAO.get(papel, {}))


def limpar_permissoes(entrada) -> dict | None:
    """Só chaves e níveis conhecidos; `acessos` nunca fica em "alterar" para quem não é admin (checado também em permissoes_de)."""
    if not isinstance(entrada, dict):
        return None
    return {k: v for k, v in entrada.items() if k in SECOES and v in NIVEIS}


def permissoes_de(conta: Conta | None) -> dict | None:
    """None = sem acesso ao painel (sem conta, bloqueada ou conta comum)."""
    if conta is None or conta.bloqueada:
        return None
    papel = papel_efetivo(conta)
    if papel == "admin":
        return permissoes_padrao("admin")
    if papel not in PADRAO:
        return None
    p = permissoes_padrao(papel)
    p.update(limpar_permissoes(conta.permissoes) or {})
    p["acessos"] = ""                       # só o administrador mexe nos acessos
    if not any(p.values()):
        return None                         # tudo "Nenhum": é o mesmo que sem acesso
    return p


def pode(conta: Conta | None, secao: str, nivel: str = "ver") -> bool:
    p = permissoes_de(conta)
    if p is None:
        return False
    atual = p.get(secao, "")
    return atual == "alterar" or (nivel == "ver" and atual == "ver")
