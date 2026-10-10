"""Segurança pública por estado: sistema prisional, mortes violentas, Sinesp e efetivos.

As taxas usam a população do IBGE (indicador `populacao`, o ano mais recente de cada estado).
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Indicador, Registro
from app.utils import UFS

router = APIRouter(tags=["Segurança"])

NOTAS = [
    "Taxas por 100 mil habitantes, com a população do IBGE.",
    "Sistema prisional (Sisdepen): fotografia do fim do semestre. 'Presos por dia' são as entradas no sistema "
    "(inclusões originárias) no semestre divididas pelos dias do semestre.",
    "Saídas temporárias: autorizações concedidas no semestre. 'Não voltaram' são os abandonos registrados no "
    "Sisdepen (presos dos regimes semiaberto e aberto que não retornaram, inclusive de saída temporária).",
    "Mortes violentas intencionais (Anuário Brasileiro de Segurança Pública): homicídios dolosos, latrocínios, "
    "lesões corporais seguidas de morte e mortes decorrentes de intervenção policial.",
    "Procurados (mandados de prisão em aberto): o Banco Nacional de Medidas Penais e Prisões (BNMP/CNJ) não "
    "responde a servidores fora do Brasil; o número entra quando o BRASIL+ rodar num servidor no Brasil.",
]


def _populacao(db) -> dict:
    linhas = db.execute(select(Indicador.uf, Indicador.ano, Indicador.valor).where(Indicador.nome == "populacao")).all()
    pop = {}
    for uf, ano, v in linhas:
        if v and (uf not in pop or ano > pop[uf][0]):
            pop[uf] = (ano, v)
    return {uf: v for uf, (a, v) in pop.items()}


def _dias(ref: str | None) -> int:
    """Dias do semestre de uma referência "2025/2"."""
    try:
        ano, sem = ref.split("/")
        bissexto = int(ano) % 4 == 0 and (int(ano) % 100 != 0 or int(ano) % 400 == 0)
        return 184 if sem.strip() == "2" else (182 if bissexto else 181)
    except Exception:
        return 182


def _taxa(v, pop):
    return round(v / pop * 1e5, 1) if v is not None and pop else None


def _ultimo(db, fonte, tipo, campo=Registro.ano):
    return db.scalar(select(func.max(campo)).where(Registro.fonte == fonte, Registro.tipo == tipo))


@router.get("/seguranca")
def seguranca(db: Session = Depends(get_db)):
    """Por estado e no Brasil: presos (total, em celas, em casa com tornozeleira, vagas, déficit, taxa por 100 mil,
    entradas por dia), saídas temporárias e quem não voltou, mortes no sistema, mortes violentas intencionais e
    homicídios (número e taxa), policiais mortos e mortes por intervenção policial."""
    pop = _populacao(db)
    estados = {uf: {"populacao": pop.get(uf)} for uf in UFS}
    refs = {}

    # sistema prisional: semestre mais recente
    regs = db.scalars(select(Registro).where(Registro.fonte == "sisdepen", Registro.tipo == "prisional")).all()
    if regs:
        ref = max((r.dados or {}).get("referencia") or "" for r in regs)
        refs["prisional"] = ref
        dias = _dias(ref)
        for r in regs:
            d = r.dados or {}
            if d.get("referencia") != ref or r.uf not in estados:
                continue
            e = estados[r.uf]
            presos = d.get("populacao")
            e["prisional"] = {k: d.get(k) for k in ("populacao", "populacao_celas", "populacao_domiciliar", "vagas",
                                                    "entradas", "alvaras", "abandonos", "obitos", "saidas_temporarias",
                                                    "estabelecimentos")}
            e["prisional"].update({
                "deficit_vagas": (d.get("populacao_celas") or 0) - (d.get("vagas") or 0) if d.get("vagas") else None,
                "taxa_aprisionamento": _taxa(presos, e["populacao"]),
                "presos_por_dia": round((d.get("entradas") or 0) / dias, 1),
                "nao_voltaram_por_mil_saidas": round(1000 * d["abandonos"] / d["saidas_temporarias"], 1)
                if d.get("saidas_temporarias") else None,
            })

    # mortes violentas: ano mais recente do Anuário (e o anterior, para a variação)
    ano = _ultimo(db, "fbsp", "violencia")
    if ano:
        refs["violencia"] = ano
        ant = {r.uf: r.dados or {} for r in db.scalars(select(Registro).where(
            Registro.fonte == "fbsp", Registro.tipo == "violencia", Registro.ano == ano - 1))}
        brasil_v = None
        for r in db.scalars(select(Registro).where(Registro.fonte == "fbsp", Registro.tipo == "violencia",
                                                   Registro.ano == ano)):
            d = dict(r.dados or {})
            d["taxa_homicidio"] = _taxa(d.get("homicidio_doloso"), pop.get(r.uf)) if r.uf != "BR" else None
            a = ant.get(r.uf, {})
            d["variacao_mvi"] = round(100 * (d["mvi"] / a["mvi"] - 1), 1) if d.get("mvi") and a.get("mvi") else None
            d["ano"] = ano
            if r.uf == "BR":
                brasil_v = d
            elif r.uf in estados:
                estados[r.uf]["violencia"] = d

    # Brasil: soma dos estados
    def soma(bloco, campo):
        vals = [e[bloco].get(campo) for e in estados.values() if e.get(bloco) and e[bloco].get(campo) is not None]
        return sum(vals) if vals else None
    pop_br = sum(v for v in pop.values()) if pop else None
    brasil = {"populacao": pop_br}
    if refs.get("prisional"):
        p = {k: soma("prisional", k) for k in ("populacao", "populacao_celas", "populacao_domiciliar", "vagas", "entradas",
                                                "alvaras", "abandonos", "obitos", "saidas_temporarias", "estabelecimentos")}
        p["deficit_vagas"] = (p["populacao_celas"] or 0) - (p["vagas"] or 0) if p["vagas"] else None
        p["taxa_aprisionamento"] = _taxa(p["populacao"], pop_br)
        p["presos_por_dia"] = round((p["entradas"] or 0) / _dias(refs["prisional"]), 1)
        p["nao_voltaram_por_mil_saidas"] = round(1000 * p["abandonos"] / p["saidas_temporarias"], 1) if p["saidas_temporarias"] else None
        brasil["prisional"] = p
    if refs.get("violencia"):
        brasil["violencia"] = brasil_v or {k: soma("violencia", k) for k in ("mvi", "homicidio_doloso", "latrocinio")}
        if brasil["violencia"] is not None:
            brasil["violencia"]["taxa_homicidio"] = _taxa(brasil["violencia"].get("homicidio_doloso"), pop_br)

    if not refs:
        raise HTTPException(404, "Sem dados. Rode as coletas seguranca-prisional e seguranca-anuario.")
    return {"referencias": refs, "brasil": brasil, "estados": estados, "notas": NOTAS,
            "fontes": {"prisional": "Sisdepen — Secretaria Nacional de Políticas Penais (Ministério da Justiça)",
                       "violencia": "Anuário Brasileiro de Segurança Pública (Fórum Brasileiro de Segurança Pública), "
                                    "com dados das secretarias estaduais de segurança",
                       "populacao": "IBGE"}}
