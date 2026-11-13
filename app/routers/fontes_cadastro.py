"""Cadastro de fontes pela tela. Leitura é pública (sem segredo); escrita exige o X-Admin-Token e usa a conexão de
escrita (DATABASE_URL_ESCRITA). Sem essa conexão, a API continua só de leitura e estas rotas recusam."""
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import fontes_cadastro, limites
from app.config import settings
from app.db import SessionEscrita, get_db
from app.models import FonteCadastrada
from app.seguranca import ip_cliente

router = APIRouter(tags=["Fontes cadastradas"])


class FonteIn(BaseModel):
    nome: str = Field(max_length=64)
    produto: str = Field(default="BRASIL+", max_length=60)
    url: str = Field(max_length=500)
    intervalo_min: int = 1440
    formato: str = Field(max_length=10)
    campos: dict
    permitir_pessoas: bool = False


class FonteAtualiza(BaseModel):
    intervalo_min: int | None = None
    ativa: bool | None = None
    permitir_pessoas: bool | None = None


def _ver(f: FonteCadastrada) -> dict:
    return {"id": f.id, "nome": f.nome, "produto": f.produto, "url": f.url, "intervalo_min": f.intervalo_min,
            "formato": f.formato, "campos": f.campos, "permitir_pessoas": f.permitir_pessoas, "ativa": f.ativa,
            "atualizada_em": f.atualizada_em.isoformat() if f.atualizada_em else None}


def _exige_admin(request: Request, token: str) -> None:
    """Mesmo critério das coletas pela API: token de 24+ caracteres e no máximo 10 tentativas por minuto por IP."""
    if settings.admin_token in ("", "troque-este-token") or len(settings.admin_token) < 24:
        raise HTTPException(403, "Defina um ADMIN_TOKEN forte (24+ caracteres) no .env para cadastrar fontes.")
    try:
        if not limites.consumir(f"admin:{ip_cliente(request)}", 10, 60).ok:
            raise HTTPException(429, "Muitas tentativas. Espere um minuto.", headers={"Retry-After": "60"})
    except limites.LimiteIndisponivel:
        raise HTTPException(503, "Controle de acesso indisponível.")
    if not secrets.compare_digest(token.encode(), settings.admin_token.encode()):
        raise HTTPException(401, "Token inválido")


def _sessao_escrita():
    """Sessão de escrita. Sem DATABASE_URL_ESCRITA: se a API for só de leitura, recusa; em testes (sem essa restrição), usa a padrão."""
    if SessionEscrita is not None:
        return SessionEscrita()
    if settings.somente_leitura:
        raise HTTPException(403, "Cadastro de fontes desligado: a API está só de leitura (falta DATABASE_URL_ESCRITA).")
    from app.db import SessionLocal
    return SessionLocal()


@router.get("/fontes-cadastradas", tags=["Fontes cadastradas"])
def listar(ativa: bool | None = None, db: Session = Depends(get_db)):
    q = select(FonteCadastrada).order_by(FonteCadastrada.nome)
    if ativa is not None:
        q = q.where(FonteCadastrada.ativa == ativa)
    return [_ver(f) for f in db.scalars(q).all()]


@router.get("/fontes-novas", tags=["Fontes cadastradas"])
def fontes_novas(db: Session = Depends(get_db)):
    """Quadro genérico das fontes que entraram sem código novo (cadastro pela tela ou adaptador `linhas` do coletor do celular)."""
    from app import fontes_novas as fn
    return fn.listar(db)


@router.post("/fontes-cadastradas", status_code=201, tags=["Fontes cadastradas"])
def cadastrar(corpo: FonteIn, request: Request, x_admin_token: str = Header(...)):
    _exige_admin(request, x_admin_token)
    try:
        limpa = fontes_cadastro.validar(corpo.model_dump())
    except ValueError as e:
        raise HTTPException(422, str(e))
    db = _sessao_escrita()
    try:
        if db.scalar(select(FonteCadastrada.id).where(FonteCadastrada.nome == limpa["nome"])):
            raise HTTPException(409, f"já existe uma fonte chamada {limpa['nome']!r}")
        agora = datetime.now(timezone.utc)
        f = FonteCadastrada(**limpa, ativa=True, criada_em=agora, atualizada_em=agora)
        db.add(f)
        db.commit()
        return _ver(f)
    finally:
        db.close()


@router.post("/fontes-cadastradas/{fonte_id}", tags=["Fontes cadastradas"])
def atualizar(fonte_id: int, corpo: FonteAtualiza, request: Request, x_admin_token: str = Header(...)):
    _exige_admin(request, x_admin_token)
    db = _sessao_escrita()
    try:
        f = db.get(FonteCadastrada, fonte_id)
        if f is None:
            raise HTTPException(404, "fonte não encontrada")
        if corpo.intervalo_min is not None:
            if not fontes_cadastro.INTERVALO[0] <= corpo.intervalo_min <= fontes_cadastro.INTERVALO[1]:
                raise HTTPException(422, "intervalo_min fora do permitido")
            f.intervalo_min = corpo.intervalo_min
        if corpo.ativa is not None:
            f.ativa = corpo.ativa
        if corpo.permitir_pessoas is not None:
            f.permitir_pessoas = corpo.permitir_pessoas
        f.atualizada_em = datetime.now(timezone.utc)
        db.commit()
        return _ver(f)
    finally:
        db.close()
