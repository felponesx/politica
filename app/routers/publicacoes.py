"""Publicações do BRASIL+ (notícias, dados próprios, destaques) e a área do administrador: escrever, enviar fotos e ver o banco."""
from __future__ import annotations

import hmac
from datetime import datetime
from html import escape

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import contas, publicacoes as pub
from app.db import get_db
from app.models import Conta, Midia, Parlamentar, Proposicao, Publicacao, Votacao, VotoLei, agora_utc
from app import limites
from app.config import settings
from app.routers.contas import _exige_json
from app.seguranca import ip_cliente

router = APIRouter(tags=["Publicações e administração"])


class PublicacaoIn(BaseModel):
    titulo: str = Field(max_length=200)
    resumo: str | None = Field(default=None, max_length=400)
    corpo: str = Field(max_length=25000)
    categoria: str = Field(default="noticia", max_length=40)
    fonte: str | None = Field(default=None, max_length=300)
    video: str | None = Field(default=None, max_length=300)
    capa_url: str | None = Field(default=None, max_length=500)
    capa_midia_id: int | None = None
    publicada: bool = False
    slug: str | None = Field(default=None, max_length=160)


class FotoIn(BaseModel):
    nome: str = Field(max_length=120)
    dados_base64: str = Field(max_length=4 * 1024 * 1024 + 64)


def _admin(request: Request, db: Session) -> Conta:
    conta = contas.conta_da_sessao(db, request.cookies.get(contas.COOKIE))
    if conta is None:
        raise HTTPException(401, "Entre na sua conta.")
    if not contas.e_admin(conta):
        raise HTTPException(403, "Esta área é só para administradores.")
    return conta


def _slug_livre(db: Session, base: str, ignorar_id: int | None = None) -> str:
    slug, n = base, 2
    while True:
        q = select(Publicacao.id).where(Publicacao.slug == slug)
        achado = db.scalars(q).first()
        if achado is None or achado == ignorar_id:
            return slug
        slug = f"{base}-{n}"
        n += 1


def _aplica(p: Publicacao, dados: PublicacaoIn, db: Session) -> None:
    campos = pub.valida_campos(dados.titulo, dados.resumo, dados.corpo, dados.categoria, dados.fonte, dados.video, dados.capa_url)
    for k, v in campos.items():
        setattr(p, k, v)
    if dados.capa_midia_id is not None:
        if db.get(Midia, dados.capa_midia_id) is None:
            raise pub.ErroPublicacao("Foto não encontrada.", 404)
        p.capa_midia_id = dados.capa_midia_id
        p.capa_url = None
    elif campos["capa_url"]:
        p.capa_midia_id = None
    else:
        p.capa_midia_id = None
    # o link (slug) é fixo depois de criado; só muda se o administrador pedir outro explicitamente
    if not p.slug or (dados.slug and pub.slugify(dados.slug) != p.slug):
        p.slug = _slug_livre(db, pub.slugify(dados.slug or dados.titulo), p.id)
    agora = agora_utc()
    if dados.publicada and not p.publicada:
        p.publicada_em = agora
    if not dados.publicada:
        p.publicada_em = None
    p.publicada = dados.publicada
    p.atualizada_em = agora


# ---------- público ----------

@router.get("/publicacoes")
def listar_publicacoes(categoria: str | None = Query(None, max_length=40), limite: int = Query(20, ge=1, le=60),
                       pagina: int = Query(1, ge=1, le=200), db: Session = Depends(get_db)):
    q = select(Publicacao).where(Publicacao.publicada.is_(True))
    if categoria:
        q = q.where(Publicacao.categoria == categoria)
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    itens = db.scalars(q.order_by(Publicacao.publicada_em.desc()).offset((pagina - 1) * limite).limit(limite)).all()
    return {"total": total, "pagina": pagina, "itens": [pub.resumo_de(p) for p in itens]}


@router.get("/publicacoes/{slug}")
def ver_publicacao(slug: str, db: Session = Depends(get_db)):
    p = db.scalars(select(Publicacao).where(Publicacao.slug == slug, Publicacao.publicada.is_(True))).first()
    if p is None:
        raise HTTPException(404, "Publicação não encontrada.")
    return pub.completo_de(p)


@router.get("/midia/{mid}")
def foto_publicada(mid: int, db: Session = Depends(get_db)):
    """Só serve a foto se ela for capa de alguma publicação já publicada (rascunhos e fotos avulsas ficam fechados)."""
    ok = db.scalars(select(Publicacao.id).where(Publicacao.capa_midia_id == mid, Publicacao.publicada.is_(True))).first()
    m = db.get(Midia, mid) if ok else None
    if m is None:
        raise HTTPException(404, "Foto não encontrada.")
    return Response(content=m.dados, media_type=m.tipo, headers={"Cache-Control": "public, max-age=86400"})


# ---------- administrador ----------

@router.get("/admin/publicacoes")
def admin_listar(request: Request, db: Session = Depends(get_db)):
    _admin(request, db)
    itens = db.scalars(select(Publicacao).order_by(Publicacao.atualizada_em.desc())).all()
    return {"itens": [{"id": p.id, **pub.resumo_de(p), "publicada": p.publicada, "atualizada_em": p.atualizada_em.isoformat()} for p in itens]}


@router.get("/admin/publicacoes/{pid}")
def admin_ver(pid: int, request: Request, db: Session = Depends(get_db)):
    _admin(request, db)
    p = db.get(Publicacao, pid)
    if p is None:
        raise HTTPException(404, "Publicação não encontrada.")
    return {**pub.completo_de(p), "capa_midia_id": p.capa_midia_id, "capa_url_propria": p.capa_url}


@router.post("/admin/publicacoes")
def admin_criar(dados: PublicacaoIn, request: Request, db: Session = Depends(get_db)):
    _exige_json(request)
    _admin(request, db)
    try:
        p = Publicacao(criada_em=agora_utc(), corpo="", titulo="", slug="", publicada=False)
        db.add(p)
        db.flush()
        _aplica(p, dados, db)
        db.commit()
    except pub.ErroPublicacao as e:
        db.rollback()
        raise HTTPException(e.status, e.mensagem)
    return {"id": p.id, "slug": p.slug, "publicada": p.publicada}


@router.post("/admin/publicacoes/{pid}")
def admin_salvar(pid: int, dados: PublicacaoIn, request: Request, db: Session = Depends(get_db)):
    _exige_json(request)
    _admin(request, db)
    p = db.get(Publicacao, pid)
    if p is None:
        raise HTTPException(404, "Publicação não encontrada.")
    try:
        _aplica(p, dados, db)
        db.commit()
    except pub.ErroPublicacao as e:
        db.rollback()
        raise HTTPException(e.status, e.mensagem)
    return {"id": p.id, "slug": p.slug, "publicada": p.publicada}


@router.post("/admin/publicacoes/{pid}/apagar")
def admin_apagar(pid: int, request: Request, db: Session = Depends(get_db)):
    _exige_json(request)
    _admin(request, db)
    p = db.get(Publicacao, pid)
    if p is None:
        raise HTTPException(404, "Publicação não encontrada.")
    db.delete(p)
    db.commit()
    return {"ok": True}


@router.post("/admin/midia")
def admin_enviar_foto(dados: FotoIn, request: Request, db: Session = Depends(get_db)):
    _exige_json(request)
    _admin(request, db)
    try:
        bruto, tipo = pub.decodifica_foto(dados.dados_base64)
    except pub.ErroPublicacao as e:
        raise HTTPException(e.status, e.mensagem)
    nome = " ".join(dados.nome.split())[:120] or "foto"
    m = Midia(nome=nome, tipo=tipo, tamanho=len(bruto), dados=bruto, criada_em=agora_utc())
    db.add(m)
    db.commit()
    return {"id": m.id, "tipo": tipo, "tamanho": m.tamanho, "url": f"/admin/midia/{m.id}"}


@router.get("/admin/midia/{mid}")
def admin_foto(mid: int, request: Request, db: Session = Depends(get_db)):
    _admin(request, db)
    m = db.get(Midia, mid)
    if m is None:
        raise HTTPException(404, "Foto não encontrada.")
    return Response(content=m.dados, media_type=m.tipo, headers={"Cache-Control": "private, max-age=600"})


# ---------- banco de dados (só leitura, só para administradores) ----------

BANCO = {
    "publicacoes": (Publicacao, (), "Publicações do site"),
    "midias": (Midia, ("dados",), "Fotos enviadas (só os dados, sem o arquivo)"),
    "contas": (Conta, ("senha_hash", "cpf_codigo", "google_sub"), "Contas de pessoas (sem senha, CPF e identificador Google)"),
    "votos_lei": (VotoLei, (), "Votos nas leis (uma conta = um voto por lei)"),
    "proposicoes": (Proposicao, (), "Projetos de lei, PEC e outras proposições"),
    "votacoes": (Votacao, (), "Votações do Congresso"),
    "parlamentares": (Parlamentar, (), "Parlamentares"),
}
POR_PAGINA = 50


def _valor(v):
    if v is None or isinstance(v, (int, float, bool)):
        return v
    if isinstance(v, datetime):
        return v.isoformat(timespec="minutes")
    if hasattr(v, "isoformat"):
        return v.isoformat()
    s = str(v)
    return s if len(s) <= 300 else s[:300] + "…"


@router.get("/admin/banco")
def admin_banco(request: Request, db: Session = Depends(get_db)):
    _admin(request, db)
    out = []
    for nome, (modelo, ocultas, descr) in BANCO.items():
        out.append({"tabela": nome, "descricao": descr, "linhas": db.scalar(select(func.count()).select_from(modelo))})
    return {"tabelas": out}


@router.get("/admin/banco/{tabela}")
def admin_banco_tabela(tabela: str, request: Request, pagina: int = Query(1, ge=1, le=100000), db: Session = Depends(get_db)):
    _admin(request, db)
    if tabela not in BANCO:
        raise HTTPException(404, "Tabela não disponível para consulta.")
    modelo, ocultas, descr = BANCO[tabela]
    colunas = [c for c in modelo.__table__.columns if c.name not in ocultas]
    total = db.scalar(select(func.count()).select_from(modelo))
    chave = list(modelo.__table__.primary_key.columns)[0]
    linhas = db.scalars(select(modelo).order_by(chave.desc()).offset((pagina - 1) * POR_PAGINA).limit(POR_PAGINA)).all()
    return {"tabela": tabela, "descricao": descr, "colunas": [c.name for c in colunas], "total": total,
            "pagina": pagina, "paginas": max(1, -(-total // POR_PAGINA)),
            "linhas": [[_valor(getattr(l, c.name)) for c in colunas] for l in linhas]}


# ---------- configuração inicial do administrador (sem terminal, pelo celular) ----------

class ConfigurarIn(BaseModel):
    chave: str = Field(max_length=200)
    email: str = Field(max_length=254)


def _setup_ativo() -> bool:
    return len(settings.setup_admin_token or "") >= 32


@router.get("/admin/configurar", response_class=HTMLResponse)
def pagina_configurar():
    """Página que torna administrador uma conta JÁ criada pelo site. Desligada (404) sem SETUP_ADMIN_TOKEN de 32+ caracteres."""
    if not _setup_ativo():
        raise HTTPException(404)
    return HTMLResponse("""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Configurar administrador</title>
<style>body{font-family:system-ui,sans-serif;background:#F5F7FA;color:#1D2939;margin:0;padding:20px}main{max-width:420px;margin:24px auto;background:#fff;border-radius:16px;padding:22px;box-shadow:0 8px 24px rgba(15,25,45,.08)}
h1{font-size:20px;margin:0 0 6px}p{font-size:14px;line-height:1.5;color:#475467}label{display:block;font-size:13px;margin:12px 0 4px;color:#344054}
input{width:100%;box-sizing:border-box;padding:11px 12px;border:1px solid #D0D5DD;border-radius:10px;font-size:16px}button{width:100%;margin-top:16px;padding:12px;border:0;border-radius:12px;background:#2F6FED;color:#fff;font-size:15px;font-weight:600}
#res{margin-top:14px;font-size:14px;line-height:1.5}.ok{color:#067647}.erro{color:#B42318}</style></head><body><main>
<h1>Configurar administrador</h1>
<p>Esta página torna administradora uma conta que você <b>já criou</b> pelo site (Criar conta). Ela não pede senha.</p>
<label for="chave">Chave de configuração</label><input id="chave" type="password" autocomplete="off">
<label for="email">E-mail da conta</label><input id="email" type="email" autocomplete="off" placeholder="voce@gmail.com">
<button id="ir" type="button">Tornar administrador</button>
<div id="res" role="status"></div></main>
<script>
document.getElementById("ir").onclick=async()=>{const r=document.getElementById("res");r.className="";r.textContent="Enviando…";
 try{const x=await fetch("/admin/configurar",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({chave:document.getElementById("chave").value,email:document.getElementById("email").value.trim()})});
  const d=await x.json().catch(()=>({}));if(!x.ok){r.className="erro";r.textContent=d.detail||"Não foi possível concluir ("+x.status+")."}else{r.className="ok";r.textContent=d.mensagem}}
 catch(e){r.className="erro";r.textContent="Sem conexão com o servidor."}};
</script></body></html>""")


@router.post("/admin/configurar")
def configurar_admin(dados: ConfigurarIn, request: Request, db: Session = Depends(get_db)):
    _exige_json(request)
    if not _setup_ativo():
        raise HTTPException(404)
    _limita_setup(request)
    if not hmac.compare_digest(dados.chave.encode(), settings.setup_admin_token.encode()):
        raise HTTPException(403, "Chave incorreta.")
    email = contas.normalizar_email(dados.email)
    conta = db.scalars(select(Conta).where(Conta.email == email)).first() if contas.email_valido(email) else None
    if conta is None:
        raise HTTPException(404, "Não há conta com este e-mail. Crie a conta primeiro pelo site (Criar conta) e tente de novo.")
    conta.papel = "admin"
    db.commit()
    return {"ok": True, "mensagem": "Pronto: esta conta agora é administradora. Saia e entre de novo no site. Depois, apague SETUP_ADMIN_TOKEN no servidor."}


def _limita_setup(request: Request) -> None:
    try:
        r = limites.consumir(f"setup:{limites.hash_cliente(ip_cliente(request))}", 10, 900)
    except limites.LimiteIndisponivel:
        raise HTTPException(503, "Serviço indisponível. Tente de novo em instantes.")
    if not r.ok:
        raise HTTPException(429, "Muitas tentativas. Espere alguns minutos.")
