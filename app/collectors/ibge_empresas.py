"""Economia das empresas do Brasil — pesquisas anuais do IBGE (PIA-Empresa, PAC, PAS e PAIC), via API de agregados.
Totais do país por setor (indústria, construção, comércio e serviços): nº de empresas, pessoal ocupado, receita,
valor adicionado e gastos com pessoal. Não existe faturamento por empresa em base aberta: só estes totais por setor.
Docs: https://servicodados.ibge.gov.br/api/docs/agregados
"""
from app import http
from app.collectors.base import registrar_coleta
from app.models import Registro
from app.utils import upsert

BASE = "https://servicodados.ibge.gov.br/api/v3/agregados"

# setor -> (tabela, classificação, categoria "total", variáveis {campo: id})
SETORES = {
    "industria": (10451, 12762, 117897, {"empresas": 630, "pessoal": 631, "receita": 806, "receita_total": 805,
                                         "gastos_total": 802, "gastos_pessoal": 803, "valor_adicionado": 811}),
    "construcao": (10463, 12296, 105185, {"empresas": 410, "pessoal": 631, "receita": 1240, "gastos_total": 838,
                                          "gastos_pessoal": 868, "valor_adicionado": 1242}),
    "comercio": (10645, 11070, 83311, {"empresas": 310, "pessoal": 631, "receita": 643, "gastos_pessoal": 314,
                                       "valor_adicionado": 635, "margem_comercializacao": 503, "taxa_margem": 1400}),
    "servicos": (10758, 12355, 106829, {"empresas": 630, "pessoal": 631, "receita": 643, "gastos_pessoal": 856,
                                        "valor_adicionado": 1242, "excedente": 636}),
}
NOMES = {"industria": "Indústria", "construcao": "Construção", "comercio": "Comércio", "servicos": "Serviços"}


def _setor(tabela: int, cls: int, cat: int, variaveis: dict, ano: int) -> dict:
    ids = "|".join(str(v) for v in variaveis.values())
    resp = http.get_json(f"{BASE}/{tabela}/periodos/{ano}/variaveis/{ids}",
                         params={"localidades": "N1[all]", "classificacao": f"{cls}[{cat}]"})
    por_id = {}
    for v in resp or []:
        serie = (((v.get("resultados") or [{}])[0].get("series") or [{}])[0].get("serie") or {})
        bruto = serie.get(str(ano))
        try:
            por_id[int(v["id"])] = float(bruto)
        except (TypeError, ValueError):
            pass
    out = {}
    for campo, vid in variaveis.items():
        if vid in por_id:
            # valores em "Mil Reais" viram reais; contagens e a taxa ficam como vêm
            out[campo] = por_id[vid] * (1000 if campo not in ("empresas", "pessoal", "taxa_margem") else 1)
    return out


def coletar_empresas_economia(ano: int = 2024):
    with registrar_coleta("ibge", "empresas_economia", ano=ano) as (db, n):
        setores = {}
        for nome, (t, c, k, v) in SETORES.items():
            try:
                d = _setor(t, c, k, v, ano)
            except Exception as e:  # noqa: BLE001 - um setor fora do ar não derruba os outros
                n.avisos.append(f"{nome}: {type(e).__name__}: {e}"[:200])
                continue
            if d.get("empresas") and d.get("receita"):
                setores[nome] = d
        if not setores:
            raise RuntimeError("Nenhum setor veio do IBGE")
        upsert(db, Registro, {"fonte": "ibge", "tipo": "empresas_economia", "chave": str(ano)},
               {"ano": ano, "titulo": "Economia das empresas (IBGE)", "dados": {"ano": ano, "setores": setores}})
        db.commit()
        n += len(setores)
    return n.itens
