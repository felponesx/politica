"""Login de pessoas e voto nas leis (uma conta = um voto por lei). Ver app/contas.py para as regras de senha, CPF e sessão."""
from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import contas, limites
from app.config import settings
from app.db import get_db
from app.models import Conta, Proposicao, VotoLei
from app.seguranca import _https, ip_cliente

router = APIRouter(tags=["Contas e votos nas leis"])


class CadastroIn(BaseModel):
    email: str = Field(max_length=254)
    senha: str = Field(max_length=128)
    nome: str = Field(max_length=120)
    cpf: str = Field(max_length=20)
    aceito_termos: bool = False


class EntrarIn(BaseModel):
    email: str = Field(max_length=254)
    senha: str = Field(max_length=128)


class GoogleIn(BaseModel):
    credential: str = Field(max_length=4096)      # ID token devolvido pelo botão "Entrar com o Google"
    cpf: str | None = Field(default=None, max_length=20)   # só no primeiro acesso (conta nova)
    nome: str | None = Field(default=None, max_length=120)
    aceito_termos: bool = False


class PerfilIn(BaseModel):
    nome: str | None = Field(default=None, max_length=120)
    data_nascimento: date | None = None
    uf: str | None = Field(default=None, max_length=2)
    cidade: str | None = Field(default=None, max_length=80)
    interesses: list[str] | None = Field(default=None, max_length=10)


class VotoIn(BaseModel):
    opcao: Literal["aprovo", "nao_aprovo", "indeferido"]


def _exige_json(request: Request) -> None:
    if not request.headers.get("content-type", "").startswith("application/json"):
        raise HTTPException(415, "Envie os dados em JSON.")


def _limita(chave: str, limite: int, janela_s: int) -> None:
    try:
        r = limites.consumir(chave, limite, janela_s)
    except limites.LimiteIndisponivel:
        raise HTTPException(503, "Serviço temporariamente indisponível. Tente de novo em instantes.")
    if not r.ok:
        raise HTTPException(429, "Muitas tentativas. Espere alguns minutos.", headers={"Retry-After": str(r.reinicia)})


def _cookie(resp: JSONResponse, request: Request, token: str | None) -> None:
    if token is None:
        resp.delete_cookie(contas.COOKIE, path="/", samesite="lax")
        return
    resp.set_cookie(contas.COOKIE, token, max_age=settings.sessao_dias * 86400, httponly=True,
                    samesite="lax", secure=_https(request), path="/")


def _erro(e: contas.ErroConta) -> HTTPException:
    return HTTPException(e.status, e.mensagem)


def _resumo_conta(conta) -> dict:
    return {"nome": conta.nome, "email": contas.email_mascarado(conta.email), "papel": conta.papel}


def _sessao_de(request: Request, db: Session) -> object | None:
    return contas.conta_da_sessao(db, request.cookies.get(contas.COOKIE))


def _exige_admin(request: Request, db: Session):
    conta = _sessao_de(request, db)
    if conta is None:
        raise HTTPException(401, "Entre na sua conta.")
    if not contas.e_admin(conta):
        raise HTTPException(403, "Esta área é só para administradores.")
    return conta


@router.post("/contas", status_code=201)
def criar_conta(dados: CadastroIn, request: Request, db: Session = Depends(get_db)):
    _exige_json(request)
    _limita(f"cadastro:{limites.hash_cliente(ip_cliente(request))}", 5, 900)
    try:
        conta = contas.cadastrar(db, dados.email, dados.senha, dados.nome, dados.cpf, dados.aceito_termos)
        token = contas.criar_sessao(db, conta)
        db.commit()
    except contas.ErroConta as e:
        db.rollback()
        raise _erro(e)
    resp = JSONResponse({"conta": _resumo_conta(conta)}, status_code=201)
    _cookie(resp, request, token)
    return resp


@router.post("/contas/entrar")
def entrar(dados: EntrarIn, request: Request, db: Session = Depends(get_db)):
    _exige_json(request)
    _limita(f"login-ip:{limites.hash_cliente(ip_cliente(request))}", 10, 900)
    _limita(f"login-email:{limites.hash_cliente(contas.normalizar_email(dados.email))}", 5, 900)
    try:
        conta = contas.entrar(db, dados.email, dados.senha)
        contas.apagar_sessoes_vencidas(db)
        token = contas.criar_sessao(db, conta)
        db.commit()
    except contas.ErroConta as e:
        db.rollback()
        raise _erro(e)
    resp = JSONResponse({"conta": _resumo_conta(conta)})
    _cookie(resp, request, token)
    return resp


@router.post("/contas/sair")
def sair(request: Request, db: Session = Depends(get_db)):
    _exige_json(request)
    contas.encerrar_sessao(db, request.cookies.get(contas.COOKIE))
    db.commit()
    resp = JSONResponse({"ok": True})
    _cookie(resp, request, None)
    return resp


@router.get("/contas/google-config")
def google_config():
    """Id público do cliente Google (vai para o navegador). Sem ele, o botão do Google não aparece."""
    return {"client_id": settings.google_client_id or None}


@router.post("/contas/google")
def entrar_google(dados: GoogleIn, request: Request, db: Session = Depends(get_db)):
    _exige_json(request)
    _limita(f"google-ip:{limites.hash_cliente(ip_cliente(request))}", 20, 900)
    try:
        claims = contas.verificar_google(dados.credential)
        conta = contas.conta_do_google(db, claims)
        if conta is None:
            if not dados.cpf:
                # primeiro acesso: o site pede CPF e o aceite dos termos e manda de novo com o mesmo token
                db.rollback()
                return JSONResponse({"precisa_cadastro": True, "nome": claims["nome"], "email": contas.email_mascarado(claims["email"])}, status_code=409)
            conta = contas.cadastrar_google(db, claims, dados.cpf, dados.aceito_termos)
            status = 201
        else:
            contas.apagar_sessoes_vencidas(db)
            status = 200
        token = contas.criar_sessao(db, conta)
        db.commit()
    except contas.ErroConta as e:
        db.rollback()
        raise _erro(e)
    resp = JSONResponse({"conta": _resumo_conta(conta)}, status_code=status)
    _cookie(resp, request, token)
    return resp


# ---------- área do administrador (só contas com papel "admin") ----------

@router.get("/admin/resumo")
def admin_resumo(request: Request, db: Session = Depends(get_db)):
    _exige_admin(request, db)
    total = db.scalar(select(func.count()).select_from(Conta))
    admins = db.scalar(select(func.count()).select_from(Conta).where(Conta.papel == "admin"))
    google = db.scalar(select(func.count()).select_from(Conta).where(Conta.google_sub.is_not(None)))
    senha = db.scalar(select(func.count()).select_from(Conta).where(Conta.senha_hash.is_not(None)))
    votos = db.execute(select(VotoLei.opcao, func.count()).group_by(VotoLei.opcao)).all()
    return {
        "contas": total, "administradores": admins, "com_google": google, "com_senha": senha,
        "votos_por_opcao": {o: n for o, n in votos}, "votos_total": sum(n for _, n in votos),
        "ultimas_contas": [{"nome": c.nome, "email": c.email, "papel": c.papel,
                            "entra_com": "google" if c.google_sub else "senha",
                            "criada_em": c.criada_em.isoformat() if c.criada_em else None}
                           for c in db.scalars(select(Conta).order_by(Conta.criada_em.desc()).limit(30)).all()],
    }


@router.get("/contas/termos")
def termos_vigentes():
    return {"versao": contas.TERMOS_VERSAO}


@router.get("/contas/eu")
def eu(request: Request, db: Session = Depends(get_db)):
    conta = contas.conta_da_sessao(db, request.cookies.get(contas.COOKIE))
    if conta is None:
        return {"conta": None}
    return {"conta": _resumo_conta(conta), "perfil": contas.perfil_de(conta), "admin": contas.e_admin(conta)}


@router.post("/contas/perfil")
def salvar_perfil(dados: PerfilIn, request: Request, db: Session = Depends(get_db)):
    """Completa ou muda os dados da própria conta. Só campos enviados são alterados."""
    _exige_json(request)
    conta = contas.conta_da_sessao(db, request.cookies.get(contas.COOKIE))
    if conta is None:
        raise HTTPException(401, "Entre na sua conta.")
    _limita(f"perfil:{conta.id}", 30, 3600)
    try:
        contas.salva_perfil(conta, dados.nome, dados.data_nascimento, dados.uf, dados.cidade, dados.interesses)
        db.commit()
    except contas.ErroConta as e:
        db.rollback()
        raise _erro(e)
    return {"conta": _resumo_conta(conta), "perfil": contas.perfil_de(conta)}


@router.get("/votos-leis")
def votos_das_leis(request: Request, ids: str = Query(..., max_length=2000), db: Session = Depends(get_db)):
    """Contagem dos votos de cada lei pedida (até 100) e o voto de quem está logado. Sem login, a contagem vem mesmo assim."""
    try:
        pids = sorted({int(x) for x in ids.split(",") if x.strip()})[:100]
    except ValueError:
        raise HTTPException(422, "Lista de ids inválida.")
    conta = contas.conta_da_sessao(db, request.cookies.get(contas.COOKIE))
    out = {str(pid): {"total": 0, "contagem": {o: 0 for o in contas.OPCOES}, "meu_voto": None} for pid in pids}
    if not pids:
        return {"leis": out}
    for pid, opcao, n in db.execute(select(VotoLei.proposicao_id, VotoLei.opcao, func.count()).where(VotoLei.proposicao_id.in_(pids))
                                    .group_by(VotoLei.proposicao_id, VotoLei.opcao)).all():
        out[str(pid)]["contagem"][opcao] = n
        out[str(pid)]["total"] += n
    if conta is not None:
        for pid, opcao in db.execute(select(VotoLei.proposicao_id, VotoLei.opcao)
                                     .where(VotoLei.conta_id == conta.id, VotoLei.proposicao_id.in_(pids))).all():
            out[str(pid)]["meu_voto"] = opcao
    return {"leis": out, "aviso": "Enquete de pessoas inscritas. Não é votação oficial do Congresso e não representa a população."}


@router.post("/proposicoes/{pid}/voto-lei")
def votar_lei(pid: int, dados: VotoIn, request: Request, db: Session = Depends(get_db)):
    _exige_json(request)
    conta = contas.conta_da_sessao(db, request.cookies.get(contas.COOKIE))
    if conta is None:
        raise HTTPException(401, "Entre na sua conta para votar.")
    _limita(f"voto:{conta.id}", 60, 3600)
    if db.get(Proposicao, pid) is None:
        raise HTTPException(404, "Lei não encontrada.")
    voto = db.scalars(select(VotoLei).where(VotoLei.conta_id == conta.id, VotoLei.proposicao_id == pid)).first()
    if voto is None:
        db.add(VotoLei(conta_id=conta.id, proposicao_id=pid, opcao=dados.opcao))
    else:
        voto.opcao = dados.opcao
        voto.atualizado_em = contas.agora_utc()
    db.commit()
    return {"ok": True, "meu_voto": dados.opcao}
