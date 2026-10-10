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
    "Ocorrências (Sinesp VDE, Ministério da Justiça): registros mensais das secretarias estaduais. 'Presos por "
    "mandado por dia' são os mandados de prisão cumpridos nos últimos 12 meses divididos pelos dias do período. "
    "A taxa de homicídio do Sinesp considera os homicídios dolosos dos últimos 12 meses (feminicídios à parte).",
    "Efetivo (Raio-X das Forças de Segurança Pública, FBSP): profissionais da ativa, a partir dos portais da "
    "transparência. Polícia Federal, PRF e Polícia Penal Federal só têm o total nacional. A Receita Federal não é "
    "força de segurança e não entra na conta.",
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


def _dias_mes(mes: str) -> int:
    import calendar
    try:
        return calendar.monthrange(int(mes[:4]), int(mes[5:7]))[1]
    except Exception:
        return 30


def _taxa(v, pop):
    return round(v / pop * 1e5, 1) if v is not None and pop else None


def _ultimo(db, fonte, tipo, campo=Registro.ano):
    return db.scalar(select(func.max(campo)).where(Registro.fonte == fonte, Registro.tipo == tipo))


def _historico(db, pop) -> dict:
    """Série por ano: ocorrências do Sinesp (anos completos ou parciais), presos por semestre e mortes violentas."""
    out = {"ocorrencias": {}, "prisional": {}, "violencia": {}}
    for r in db.scalars(select(Registro).where(Registro.fonte == "sinesp", Registro.tipo == "vde")):
        d = r.dados or {}
        a = out["ocorrencias"].setdefault(str(r.ano), {"meses": 0, "estados": {}, "brasil": {}})
        a["meses"] = max(a["meses"], len(d.get("meses") or {}))
        tot = d.get("totais") or {}
        a["estados"][r.uf] = tot
        for k, v in tot.items():
            a["brasil"][k] = a["brasil"].get(k, 0) + (v or 0)
    for r in db.scalars(select(Registro).where(Registro.fonte == "sisdepen", Registro.tipo == "prisional")):
        d = r.dados or {}
        ref = d.get("referencia")
        if not ref:
            continue
        a = out["prisional"].setdefault(ref, {"brasil": {}, "estados": {}})
        a["estados"][r.uf] = {k: d.get(k) for k in ("populacao", "vagas", "entradas", "abandonos", "saidas_temporarias")}
        for k, v in a["estados"][r.uf].items():
            a["brasil"][k] = a["brasil"].get(k, 0) + (v or 0)
    for r in db.scalars(select(Registro).where(Registro.fonte == "fbsp", Registro.tipo == "violencia")):
        d = r.dados or {}
        a = out["violencia"].setdefault(str(r.ano), {"brasil": None, "estados": {}})
        v = {k: d.get(k) for k in ("mvi", "taxa_mvi", "homicidio_doloso", "latrocinio", "mortes_intervencao",
                                     "policiais_mortos")}
        if r.uf == "BR":
            a["brasil"] = v
        else:
            a["estados"][r.uf] = v
    return out


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

    # ocorrências do Sinesp: últimos 12 meses com dados (pode juntar dois anos)
    meses_uf = {}
    for r in db.scalars(select(Registro).where(Registro.fonte == "sinesp", Registro.tipo == "vde")):
        for mes, evs in ((r.dados or {}).get("meses") or {}).items():
            meses_uf.setdefault(r.uf, {})[mes] = evs
    serie = {}
    if meses_uf:
        todos = sorted({m for ms in meses_uf.values() for m in ms})
        janela = todos[-12:]
        dias = sum(_dias_mes(m) for m in janela)
        refs["ocorrencias"] = {"de": janela[0], "ate": janela[-1], "meses": len(janela), "dias": dias}
        for uf, ms in meses_uf.items():
            tot = {}
            for m in janela:
                for ev, v in (ms.get(m) or {}).items():
                    tot[ev] = tot.get(ev, 0) + v
                    if uf in estados:
                        serie.setdefault(m, {}).setdefault(ev, 0)
                        serie[m][ev] += v
            if uf not in estados:
                continue
            tot["meses_com_dados"] = sum(1 for m in janela if m in ms)
            tot["detidos_por_dia"] = round(tot.get("mandados_cumpridos", 0) / dias, 1) if tot.get("mandados_cumpridos") else None
            tot["homicidios_por_dia"] = round(tot.get("homicidio_doloso", 0) / dias, 1) if tot.get("homicidio_doloso") else None
            tot["taxa_homicidio"] = _taxa(tot.get("homicidio_doloso"), estados[uf]["populacao"]) if tot.get("homicidio_doloso") else None
            estados[uf]["ocorrencias"] = tot

    # efetivo das forças de segurança (Raio-X do FBSP), com policiais por mil habitantes
    ano_ef = _ultimo(db, "fbsp", "efetivo")
    brasil_ef = None
    if ano_ef:
        refs["efetivo"] = ano_ef
        for r in db.scalars(select(Registro).where(Registro.fonte == "fbsp", Registro.tipo == "efetivo",
                                                   Registro.ano == ano_ef)):
            d = {k: v for k, v in (r.dados or {}).items() if k != "url"}
            p = pop.get(r.uf) if r.uf != "BR" else (sum(pop.values()) if pop else None)
            pol = sum(d.get(k) or 0 for k in ("policia_militar", "policia_civil"))
            d["policiais_por_mil"] = round(pol / p * 1000, 2) if p and pol else None
            d["habitantes_por_policial"] = round(p / pol) if p and pol else None
            if r.uf == "BR":
                brasil_ef = d
            elif r.uf in estados:
                estados[r.uf]["efetivo"] = d

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

    if brasil_ef:
        brasil["efetivo"] = brasil_ef
    if refs.get("ocorrencias"):
        o = {}
        for e in estados.values():
            for k, v in (e.get("ocorrencias") or {}).items():
                if isinstance(v, int) and k != "meses_com_dados":
                    o[k] = o.get(k, 0) + v
        dias = sum(_dias_mes(m) for m in serie)
        o["detidos_por_dia"] = round(o.get("mandados_cumpridos", 0) / dias, 1) if o.get("mandados_cumpridos") else None
        o["homicidios_por_dia"] = round(o.get("homicidio_doloso", 0) / dias, 1) if o.get("homicidio_doloso") else None
        o["taxa_homicidio"] = _taxa(o.get("homicidio_doloso"), pop_br)
        brasil["ocorrencias"] = o
        brasil["serie_mensal"] = [{"mes": m, **serie[m]} for m in sorted(serie)]

    historico = _historico(db, pop)

    if not refs:
        raise HTTPException(404, "Sem dados. Rode as coletas seguranca-prisional, seguranca-anuario, seguranca-sinesp e seguranca-efetivo.")
    return {"referencias": refs, "brasil": brasil, "estados": estados, "historico": historico, "notas": NOTAS,
            "fontes": {"prisional": "Sisdepen — Secretaria Nacional de Políticas Penais (Ministério da Justiça)",
                       "violencia": "Anuário Brasileiro de Segurança Pública (Fórum Brasileiro de Segurança Pública), "
                                    "com dados das secretarias estaduais de segurança",
                       "efetivo": "Raio-X das Forças de Segurança Pública do Brasil (Fórum Brasileiro de Segurança Pública)",
                       "ocorrencias": "Sinesp VDE — Ministério da Justiça e Segurança Pública",
                       "populacao": "IBGE"}}
