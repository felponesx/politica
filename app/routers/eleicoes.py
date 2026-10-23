from types import SimpleNamespace

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import Integer, cast, distinct, func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import CandidatoFinancas
from app.models import ResultadoEleicao as R
from app.models import VotoMunicipio as VM
from app.utils import sem_acento

router = APIRouter(prefix="/eleicoes", tags=["Eleições"])


def _presidente_na_uf(db, ano, uf, turno):
    """Presidente dentro de um estado: soma dos votos por município (o total do país fica com uf "BR")."""
    votos = db.execute(select(VM.sq_candidato, func.sum(VM.votos))
                       .where(VM.ano == ano, VM.uf == uf, VM.cargo == "PRESIDENTE", VM.turno == turno)
                       .group_by(VM.sq_candidato)).all()
    if not votos:
        return []
    cands = {r.sq_candidato: r for r in db.scalars(select(R).where(R.ano == ano, R.cargo == "PRESIDENTE",
                                                                   R.turno == turno))}
    linhas = []
    for sq, v in votos:
        r = cands.get(sq)
        if r:
            linhas.append(SimpleNamespace(sq_candidato=sq, nome=r.nome, numero=r.numero, partido=r.partido,
                                          unidade=uf, votos=int(v or 0), situacao=r.situacao, eleito=r.eleito))
    return sorted(linhas, key=lambda r: -r.votos)


def _por_partido(db, ano, uf, cargo, turno, unidade=None):
    if cargo == "PRESIDENTE" and uf != "BR":
        linhas = {}
        for r in _presidente_na_uf(db, ano, uf, turno):
            v, e = linhas.get(r.partido, (0, 0))
            linhas[r.partido] = (v + r.votos, e + int(r.eleito))
        linhas = [(p, v, e) for p, (v, e) in linhas.items()]
        total = sum(v for _, v, _ in linhas) or 1
        return {p or "?": {"votos": v, "percentual": round(100 * v / total, 2), "eleitos": e} for p, v, e in linhas}
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
                                    "despesas": f.despesas, "despesas_por_tipo": f.despesas_por_tipo,
                                    "despesas_fornecedores": f.despesas_fornecedores} if f else None)(
                db.scalar(select(CandidatoFinancas).where(CandidatoFinancas.ano == r0.ano, CandidatoFinancas.sq_candidato == sq))),
            "municipios_top": [{"municipio": m.municipio, "votos": m.votos} for m in db.scalars(
                select(VM).where(VM.sq_candidato == sq).order_by(VM.votos.desc()).limit(20))]}


@router.get("/{ano}/{uf}/cargos")
def cargos(ano: int, uf: str, db: Session = Depends(get_db)):
    uf = uf.upper()
    lista = [c for (c,) in db.execute(select(distinct(R.cargo)).where(R.ano == ano, R.uf == uf))]
    # Presidente: o total fica em "BR", mas cada estado tem os votos por município
    if "PRESIDENTE" not in lista and uf != "BR" and db.scalar(
            select(VM.id).where(VM.ano == ano, VM.uf == uf, VM.cargo == "PRESIDENTE").limit(1)):
        lista.insert(0, "PRESIDENTE")
    return lista


ORDEM_CARGOS = ["PRESIDENTE", "GOVERNADOR", "SENADOR", "DEPUTADO FEDERAL", "DEPUTADO ESTADUAL", "DEPUTADO DISTRITAL",
                "PREFEITO", "VEREADOR"]


@router.get("/{ano}/cargos")
def cargos_do_ano(ano: int, db: Session = Depends(get_db)):
    """Cargos disputados no ano, na ordem da cédula."""
    lista = {c for (c,) in db.execute(select(distinct(R.cargo)).where(R.ano == ano))}
    return sorted(lista, key=lambda c: (ORDEM_CARGOS.index(c) if c in ORDEM_CARGOS else 99, c))


@router.get("/{ano}/estados")
def estados(ano: int, cargo: str, turno: int = 1, db: Session = Depends(get_db)):
    """Resumo por estado para o mapa do país: votos válidos, candidatos mais votados e votos por partido.
    Para o Presidente, cada estado sai dos votos por município; nos demais cargos, da votação de cada UF.
    Vereadores e prefeitos são somados por estado (para ver uma cidade, use /{ano}/{uf}?unidade=...)."""
    cargo = sem_acento(cargo)
    por_uf = {}
    if cargo == "PRESIDENTE":
        cands = {r.sq_candidato: r for r in db.scalars(select(R).where(R.ano == ano, R.cargo == cargo, R.turno == turno))}
        linhas = db.execute(select(VM.uf, VM.sq_candidato, func.sum(VM.votos))
                            .where(VM.ano == ano, VM.cargo == cargo, VM.turno == turno)
                            .group_by(VM.uf, VM.sq_candidato)).all()
        for uf, sq, v in linhas:
            r = cands.get(sq)
            if r:
                por_uf.setdefault(uf, []).append((sq, r.nome, r.numero, r.partido, int(v or 0), r.situacao, r.eleito))
    else:
        for r in db.scalars(select(R).where(R.ano == ano, R.cargo == cargo, R.turno == turno, R.uf != "BR")):
            por_uf.setdefault(r.uf, []).append((r.sq_candidato, r.nome, r.numero, r.partido, r.votos, r.situacao,
                                                r.eleito))
    if not por_uf:
        raise HTTPException(404, "Sem resultados. Rode a coleta tse-resultados para esse ano.")

    def resumo(linhas, n=8):
        total = sum(l[4] for l in linhas) or 1
        partidos = {}
        for _, _, _, p, v, _, e in linhas:
            a = partidos.setdefault(p or "?", {"partido": p or "?", "votos": 0, "eleitos": 0})
            a["votos"] += v
            a["eleitos"] += int(bool(e))
        return {"votos_validos_nominais": total,
                "candidatos": [{"sq_candidato": sq, "nome": nm, "numero": nr, "partido": p, "votos": v,
                                "percentual": round(100 * v / total, 2), "situacao": st, "eleito": bool(e)}
                               for sq, nm, nr, p, v, st, e in sorted(linhas, key=lambda l: -l[4])[:n]],
                "partidos": [{**a, "percentual": round(100 * a["votos"] / total, 2)}
                             for a in sorted(partidos.values(), key=lambda a: -a["votos"])[:n]],
                "eleitos": sum(1 for l in linhas if l[6])}

    pais = [l for ls in por_uf.values() for l in ls]
    if cargo == "PRESIDENTE":  # o mesmo candidato aparece em todos os estados: soma por candidato
        soma = {}
        for l in pais:
            a = soma.get(l[0])
            soma[l[0]] = l if not a else (*a[:4], a[4] + l[4], *a[5:])
        pais = list(soma.values())
    return {"ano": ano, "cargo": cargo, "turno": turno, "brasil": resumo(pais, 12),
            "estados": {uf: resumo(ls) for uf, ls in sorted(por_uf.items())}}


@router.get("/{ano}/{uf}")
def resultado(ano: int, uf: str, cargo: str, turno: int = 1, unidade: str | None = None,
              db: Session = Depends(get_db)):
    """Eleitos, mais votados, votos por partido e comparação com a eleição anterior (ano - 4).
    `unidade` filtra o município em eleições municipais (ex.: SÃO PAULO)."""
    uf, cargo = uf.upper(), sem_acento(cargo)
    filtro = [R.ano == ano, R.uf == uf, R.cargo == cargo, R.turno == turno]
    if unidade:
        filtro.append(R.unidade == unidade.upper())
    if cargo == "PRESIDENTE" and uf != "BR":
        linhas = _presidente_na_uf(db, ano, uf, turno)
        total = sum(r.votos for r in linhas)
    else:
        total = db.scalar(select(func.sum(R.votos)).where(*filtro))
    if not total:
        raise HTTPException(404, "Sem resultados. Rode a coleta tse-resultados para esse ano/UF.")

    def cand(r):
        return {"sq_candidato": r.sq_candidato, "nome": r.nome, "numero": r.numero, "partido": r.partido,
                "unidade": r.unidade, "votos": r.votos, "percentual": round(100 * r.votos / total, 2),
                "situacao": r.situacao}

    if cargo == "PRESIDENTE" and uf != "BR":
        eleitos, mais_votados = [r for r in linhas if r.eleito], linhas[:20]
    else:
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
    nomes = {r.sq_candidato: (r.nome, r.partido) for r in  # Presidente: os nomes ficam no total do país ("BR")
             db.scalars(select(R).where(R.ano == ano, R.uf.in_([uf, "BR"]), R.cargo == cargo, R.turno == turno))}
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
