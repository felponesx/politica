"""Saneamento básico por estado — Censo 2022 (IBGE, API de agregados) e PNAD Contínua (energia).

Água: tabela 6803 (domicílios com ligação à rede geral e que a usam como forma principal).
Esgoto: tabela 6805 (rede geral/pluvial ou fossa ligada à rede). Lixo: tabela 6892 (coletado).
Luz: tabela 9740 (% de moradores em domicílios com energia elétrica, PNAD Contínua).
"""
from app import http
from app.collectors.base import registrar_coleta
from app.models import Registro
from app.utils import UF_POR_CODIGO_IBGE, para_float, upsert

BASE = "https://servicodados.ibge.gov.br/api/v3/agregados"
# nome: (agregado, classificação, categoria do total, categoria "tem o serviço")
SERVICOS = {
    "agua": (6803, 1821, 72129, 72144),
    "esgoto": (6805, 11558, 46292, 46290),
    "lixo": (6892, 67, 10972, 2520),
}


def _serie(resp, cat_id=None) -> dict:
    """{uf: valor} de uma resposta de agregados; cat_id filtra a categoria quando há classificação."""
    out = {}
    for var in resp or []:
        for res in var.get("resultados", []):
            if cat_id is not None:
                cats = {k for c in res.get("classificacoes", []) for k in (c.get("categoria") or {})}
                if str(cat_id) not in cats:
                    continue
            for s in res.get("series", []):
                uf = UF_POR_CODIGO_IBGE.get(int(s["localidade"]["id"]))
                vals = [v for v in (s.get("serie") or {}).values()]
                if uf and vals:
                    out[uf] = para_float(vals[-1])
    return out


def montar_saneamento(dom: dict, pop: dict, energia: dict) -> dict:
    """Junta as séries em {uf: {servico: {pct, domicilios, pessoas}}}. pessoas = pct × população do estado."""
    out = {}
    for uf, p in pop.items():
        d = {}
        for nome, (tot, com) in dom.items():
            t, c = tot.get(uf), com.get(uf)
            if t and c is not None:
                pct = round(100 * c / t, 1)
                d[nome] = {"pct": pct, "domicilios": int(c), "sem_domicilios": int(t - c),
                           "pessoas": round(p * pct / 100), "sem_pessoas": round(p * (100 - pct) / 100)}
        if energia.get(uf) is not None:
            e = energia[uf]
            d["luz"] = {"pct": round(e, 1), "pessoas": round(p * e / 100), "sem_pessoas": round(p * (100 - e) / 100)}
        if d:
            out[uf] = {"populacao": p, **d}
    return out


def coletar_saneamento():
    with registrar_coleta("ibge", "saneamento") as (db, n):
        dom = {}
        for nome, (ag, cls, tot, com) in SERVICOS.items():
            r = http.get_json(f"{BASE}/{ag}/periodos/2022/variaveis/381",
                              params={"localidades": "N3[all]", "classificacao": f"{cls}[{tot},{com}]"}) or []
            dom[nome] = (_serie(r, tot), _serie(r, com))
        pop = _serie(http.get_json(f"{BASE}/9514/periodos/2022/variaveis/93",
                                   params={"localidades": "N3[all]", "classificacao": "2[6794]|287[100362]|286[113635]"}) or [])
        energia = _serie(http.get_json(f"{BASE}/9740/periodos/-1/variaveis/10137", params={"localidades": "N3[all]"}) or [])
        if not pop:
            raise ValueError("IBGE não devolveu a população por estado (tabela 9514)")
        for uf, d in montar_saneamento(dom, pop, energia).items():
            upsert(db, Registro, {"fonte": "ibge", "tipo": "saneamento", "chave": uf},
                   {"uf": uf, "ano": 2022, "titulo": "Saneamento básico", "valor": d.get("agua", {}).get("pct"), "dados": d})
            n += 1
        if len(dom["agua"][0]) < 27:
            n.avisos.append("saneamento: menos de 27 estados na resposta do IBGE")
    return n.itens
