from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import Integer, cast, distinct, func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import CandidatoFinancas
from app.models import ResultadoEleicao as R
from app.models import VotoMunicipio as VM
from app.utils import sem_acento

router = APIRouter(prefix="/eleicoes", tags=["Eleições"])


def _por_partido(db, ano, uf, cargo, turno, unidade=None):
    stmt = (select(R.partido, func.sum(R.votos), func.sum(cast(R.eleito, Integer)))
            .where(R.ano == ano, R.uf == uf, R.cargo == cargo, R.turno == turno))
    if unidade:
        stmt = stmt.where(R.unidade == unidade)
    linhas = db.execute(stmt.group_by(R.partido)).all()
    total = sum(v or 0 for _, v, _ in linhas) or 1
    return {p or "?": {"votos": v or 0, "percentual": round(100 * (v or 0) / total, 2), "eleitos": e or 0}
            for p, v, e in linhas}


@router.get("/anos")
def anos(db: Session = Depends(get_db)):
    return [a for (a,) in db.execute(select(distinct(R.ano)).order_by(R.ano.desc()))]


@router.get("/candidato/{sq}")
def candidato(sq: str, db: Session = Depends(get_db)):
    rows = db.scalars(select(R).where(R.sq_candidato == sq).order_by(R.turno)).all()
    if not rows:
        raise HTTPException(404, "Candidato não encontrado")
    r0 = rows[0]
    return {"sq_candidato": sq, "nome": r0.nome, "partido": r0.partido, "cargo": r0.cargo, "ano": r0.ano,
            "uf": r0.uf, "unidade": r0.unidade,
            "turnos": [{"turno": r.turno, "votos": r.votos, "situacao": r.situacao, "eleito": r.eleito} for r in rows],
            "financas": (lambda f: {"patrimonio": f.patrimonio, "bens_por_tipo": f.bens_por_tipo, "bens": f.bens,
                                    "receitas": f.receitas, "receitas_por_fonte": f.receitas_por_fonte,
                                    "despesas": f.despesas, "despesas_por_tipo": f.despesas_por_tipo} if f else None)(
                db.scalar(select(CandidatoFinancas).where(CandidatoFinancas.ano == r0.ano, CandidatoFinancas.sq_candidato == sq))),
            "municipios_top": [{"municipio": m.municipio, "votos": m.votos} for m in db.scalars(
                select(VM).where(VM.sq_candidato == sq).order_by(VM.votos.desc()).limit(20))]}


@router.get("/{ano}/{uf}/cargos")
def cargos(ano: int, uf: str, db: Session = Depends(get_db)):
    return [c for (c,) in db.execute(select(distinct(R.cargo)).where(R.ano == ano, R.uf == uf.upper()))]


@router.get("/{ano}/{uf}")
def resultado(ano: int, uf: str, cargo: str, turno: int = 1, unidade: str | None = None,
              db: Session = Depends(get_db)):
    """Eleitos, mais votados, votos por partido e comparação com a eleição anterior (ano - 4).
    `unidade` filtra o município em eleições municipais (ex.: SÃO PAULO)."""
    uf, cargo = uf.upper(), sem_acento(cargo)
    filtro = [R.ano == ano, R.uf == uf, R.cargo == cargo, R.turno == turno]
    if unidade:
        filtro.append(R.unidade == unidade.upper())
    total = db.scalar(select(func.sum(R.votos)).where(*filtro))
    if not total:
        raise HTTPException(404, "Sem resultados. Rode a coleta tse-resultados para esse ano/UF.")

    def cand(r):
        return {"sq_candidato": r.sq_candidato, "nome": r.nome, "numero": r.numero, "partido": r.partido,
                "unidade": r.unidade, "votos": r.votos, "percentual": round(100 * r.votos / total, 2),
                "situacao": r.situacao}

    eleitos = db.scalars(select(R).where(*filtro, R.eleito).order_by(R.votos.desc())).all()
    mais_votados = db.scalars(select(R).where(*filtro).order_by(R.votos.desc()).limit(20)).all()
    atual = _por_partido(db, ano, uf, cargo, turno, unidade and unidade.upper())
    anterior = _por_partido(db, ano - 4, uf, cargo, turno, unidade and unidade.upper())
    comparativo = None
    if anterior:
        comparativo = {p: {"percentual_atual": atual.get(p, {}).get("percentual", 0),
                           "percentual_anterior": anterior.get(p, {}).get("percentual", 0),
                           "variacao_pp": round(atual.get(p, {}).get("percentual", 0)
                                                - anterior.get(p, {}).get("percentual", 0), 2),
                           "eleitos_atual": atual.get(p, {}).get("eleitos", 0),
                           "eleitos_anterior": anterior.get(p, {}).get("eleitos", 0)}
                       for p in sorted(set(atual) | set(anterior))}
    return {
        "ano": ano, "uf": uf, "cargo": cargo, "turno": turno, "unidade": unidade,
        "votos_validos_nominais": total,
        "eleitos": [cand(r) for r in eleitos],
        "mais_votados": [cand(r) for r in mais_votados],
        "por_partido": dict(sorted(atual.items(), key=lambda x: -x[1]["votos"])),
        "comparativo_eleicao_anterior": {"ano": ano - 4, "partidos": comparativo} if comparativo else None,
    }


@router.get("/{ano}/{uf}/mapa")
def mapa(ano: int, uf: str, cargo: str, turno: int = 1, db: Session = Depends(get_db)):
    """Vencedor por município (cargos majoritários) — alimenta o mapa do estado."""
    uf, cargo = uf.upper(), sem_acento(cargo)
    linhas = db.execute(select(VM.cd_municipio, VM.municipio, VM.sq_candidato, VM.votos)
                        .where(VM.ano == ano, VM.uf == uf, VM.cargo == cargo, VM.turno == turno)).all()
    if not linhas:
        raise HTTPException(404, "Sem dados por município para esse filtro.")
    nomes = {r.sq_candidato: (r.nome, r.partido) for r in
             db.scalars(select(R).where(R.ano == ano, R.uf == uf, R.cargo == cargo, R.turno == turno))}
    por_mun = {}
    for cd, nm, sq, v in linhas:
        m = por_mun.setdefault(cd, {"cd_municipio": cd, "municipio": nm, "total": 0, "vencedor": None, "votos_vencedor": -1})
        m["total"] += v
        if v > m["votos_vencedor"]:
            m["vencedor"], m["votos_vencedor"] = sq, v
    for m in por_mun.values():
        nome, partido = nomes.get(m["vencedor"], ("?", "?"))
        m["vencedor"] = {"sq_candidato": m["vencedor"], "nome": nome, "partido": partido,
                         "percentual": round(100 * m.pop("votos_vencedor") / (m["total"] or 1), 2)}
    from app.models import Municipio
    ibge = {sem_acento(m.nome): m.codigo_ibge for m in db.scalars(select(Municipio).where(Municipio.uf == uf))}
    for m in por_mun.values():
        m["codigo_ibge"] = ibge.get(sem_acento(m["municipio"] or ""))
    return sorted(por_mun.values(), key=lambda m: m["municipio"] or "")
