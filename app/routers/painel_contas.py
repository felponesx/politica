"""Acessos ao painel "Coletas do BRASIL+": quem entra e o que pode (ver app/painel_acesso.py). Só administrador altera; leitura da lista
exige a permissão de ver `acessos`. Tudo por sessão de conta (cookie), nunca por chave."""
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app import contas, painel_acesso
from app.db import get_db
from app.models import Conta

router = APIRouter(tags=["Painel"])


class AlteraIn(BaseModel):
    papel: str | None = None
    bloqueada: bool | None = None
    permissoes: dict | None = None
    redefinir: bool = False          # volta ao padrão do papel (apaga as permissões próprias)


def _quem(request: Request, db: Session, nivel: str) -> Conta:
    conta = contas.conta_da_sessao(db, request.cookies.get(contas.COOKIE))
    if conta is None:
        raise HTTPException(401, "Entre no painel.")
    if not painel_acesso.pode(conta, "acessos", nivel):
        raise HTTPException(403, "Sem permissão para esta área.")
    return conta


def _item(c: Conta) -> dict:
    papel = painel_acesso.papel_efetivo(c)
    efetivas = painel_acesso.permissoes_de(c)
    return {"id": c.id, "nome": c.nome, "email": c.email, "papel": papel, "papel_salvo": c.papel,
            "bloqueada": bool(c.bloqueada), "entra_com": "google" if c.google_sub else "senha",
            "criada_em": c.criada_em.isoformat() if c.criada_em else None,
            "permissoes": efetivas or {s: "" for s in painel_acesso.SECOES},
            "personalizada": bool(painel_acesso.limpar_permissoes(c.permissoes)),
            "padrao_do_papel": painel_acesso.permissoes_padrao(papel),
            "fixo_por_email": c.email in contas.admins_configurados(),
            "conta_teste": c.cpf_codigo == contas.CODIGO_TESTE}


@router.get("/painel/contas")
def listar(request: Request, q: str = Query("", max_length=80), db: Session = Depends(get_db)):
    """Sem `q`: quem já tem papel no painel. Com `q`: procura por e-mail ou nome entre TODAS as contas (para dar acesso a alguém)."""
    _quem(request, db, "ver")
    consulta = select(Conta).order_by(Conta.criada_em.desc())
    if q.strip():
        t = f"%{q.strip().lower()}%"
        consulta = consulta.where(or_(Conta.email.ilike(t), Conta.nome.ilike(t))).limit(20)
    else:
        extra = contas.admins_configurados()
        filtro = Conta.papel.in_(("leitor", "editor", "admin"))
        consulta = consulta.where(or_(filtro, Conta.email.in_(extra)) if extra else filtro).limit(200)
    return {"contas": [_item(c) for c in db.scalars(consulta).all()],
            "papeis": [{"id": p, "nome": painel_acesso.NOMES_PAPEL[p]} for p in painel_acesso.PAPEIS],
            "secoes": list(painel_acesso.SECOES)}


@router.post("/painel/contas/{conta_id}")
def alterar(conta_id: int, corpo: AlteraIn, request: Request, db: Session = Depends(get_db)):
    if not request.headers.get("content-type", "").startswith("application/json"):
        raise HTTPException(415, "Envie os dados em JSON.")
    eu = _quem(request, db, "alterar")
    alvo = db.get(Conta, conta_id)
    if alvo is None:
        raise HTTPException(404, "Conta não encontrada.")
    if alvo.id == eu.id and (corpo.papel not in (None, "admin") or corpo.bloqueada):
        raise HTTPException(409, "Você não pode tirar o seu próprio acesso. Peça a outro administrador.")
    if alvo.email in contas.admins_configurados() and (corpo.papel not in (None, "admin") or corpo.bloqueada):
        raise HTTPException(409, "Este e-mail está em ADMIN_EMAILS: o acesso de administrador vem do arquivo de configuração.")
    if corpo.papel is not None:
        if corpo.papel not in painel_acesso.PAPEIS:
            raise HTTPException(422, "Papel inválido.")
        alvo.papel = corpo.papel
        if corpo.papel in ("usuario", "admin"):
            alvo.permissoes = None        # conta comum não tem permissão própria; admin sempre pode tudo
    if corpo.bloqueada is not None:
        alvo.bloqueada = corpo.bloqueada
    if corpo.redefinir:
        alvo.permissoes = None
    elif corpo.permissoes is not None:
        alvo.permissoes = painel_acesso.limpar_permissoes(corpo.permissoes) or None
    db.commit()
    return _item(alvo)
