"""Fontes que entram SEM código novo (cadastradas pela tela ou declaradas com o adaptador `linhas` no vínculo do coletor do celular):
lista cada uma com a seção, quanto já chegou e uma amostra. É o quadro genérico do BRASIL+ para o que ainda não tem tela própria."""
from __future__ import annotations

import json
import os
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.categorias import categorias_atuais
from app.models import FonteCadastrada, Registro

AMOSTRA = 5


def _declaradas_no_celular() -> dict[str, dict]:
    """Fontes do clone de dados do coletor cujo meta.json declara o adaptador genérico `linhas`."""
    raiz = os.environ.get("COLETOR_DADOS")
    out: dict[str, dict] = {}
    if not raiz:
        return out
    for pf in sorted((Path(raiz) / "dados").glob("*/meta.json")):
        try:
            meta = json.loads(pf.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(meta, dict) and meta.get("adaptador") == "linhas" and meta.get("fonte") == pf.parent.name:
            out[pf.parent.name] = meta
    return out


def _resumo(db: Session, fonte: str) -> dict:
    n, ultima = db.execute(select(func.count(Registro.id), func.max(Registro.atualizado_em)).where(Registro.fonte == fonte)).one()
    linhas = db.scalars(select(Registro).where(Registro.fonte == fonte).order_by(Registro.atualizado_em.desc()).limit(AMOSTRA)).all()
    return {"registros": n, "ultima_atualizacao": ultima.isoformat(timespec="minutes") if ultima else None,
            "amostra": [{"titulo": r.titulo, "valor": r.valor, "uf": r.uf, "ano": r.ano, "dados": r.dados} for r in linhas]}


def listar(db: Session) -> dict:
    cats = {c["id"]: c["nome"] for c in categorias_atuais()}
    fontes = []

    def cat(id_):
        return id_ if id_ in cats else None
    for f in db.scalars(select(FonteCadastrada).where(FonteCadastrada.ativa.is_(True)).order_by(FonteCadastrada.nome)).all():
        c = cat((f.campos or {}).get("categoria"))
        fontes.append({"nome": f.nome, "origem": "cadastro", "url": f.url, "formato": f.formato, "intervalo_min": f.intervalo_min,
                       "categoria": c, "categoria_nome": cats.get(c), **_resumo(db, (f.campos or {}).get("fonte") or f.nome)})
    vistos = {f["nome"] for f in fontes}
    for nome, meta in _declaradas_no_celular().items():
        if nome in vistos:
            continue
        c = cat(meta.get("categoria"))
        fontes.append({"nome": nome, "origem": "celular", "url": meta.get("url"), "formato": meta.get("formato"),
                       "intervalo_min": meta.get("intervalo_min"), "categoria": c, "categoria_nome": cats.get(c), **_resumo(db, nome)})
    return {"fontes": fontes,
            "sem_secao": [f["nome"] for f in fontes if not f["categoria"]],
            "aviso": "Fontes novas entram pelo cadastro genérico: mostramos o que chegou, sem tratar nem conferir. "
                     "Quando uma fonte ganhar tela própria, ela sai deste quadro."}
