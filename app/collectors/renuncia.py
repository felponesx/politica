"""Renúncia fiscal (gastos tributários, "bases efetivas") da Receita Federal: quanto o governo deixa de arrecadar, por função orçamentária e região.

Página: https://www.gov.br/receitafederal/pt-br/centrais-de-conteudo/publicacoes/relatorios/renuncia/gastos-tributarios-bases-efetivas/ — um .xlsx por ano-base
(`dgt-bases-efetivas-AAAA-serie-...-quadros.xlsx`). Aba "Q I" = "POR FUNÇÃO ORÇAMENTÁRIA - REGIONALIZADO (valores nominais, R$ 1,00)": linhas por função, colunas NORTE, NORDESTE,
CENTRO-OESTE, SUDESTE, SUL, TOTAL. É estimativa da Receita (não é gasto efetivo do governo)."""
import io
import re
import warnings

from app import http
from app.collectors.base import registrar_coleta
from app.models import Registro
from app.utils import sem_acento, upsert

PAGINA = "https://www.gov.br/receitafederal/pt-br/centrais-de-conteudo/publicacoes/relatorios/renuncia/gastos-tributarios-bases-efetivas/"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36", "Accept": "*/*"}
REGIOES = ("NORTE", "NORDESTE", "CENTRO-OESTE", "SUDESTE", "SUL")
MINIMO_FUNCOES = 10


def arquivos_da_pagina(html: str) -> list[tuple[int, str]]:
    achados = {}
    for u in re.findall(r'href="([^"]*dgt-bases-efetivas-(\d{4})-[^"]*quadros\.xlsx)(?:/view)?"', html, re.I):
        achados[int(u[1])] = u[0]
    return sorted(((a, (u if u.startswith("http") else "https://www.gov.br" + u)) for a, u in achados.items()), reverse=True)


def ler_quadro1(ws) -> dict:
    ano = None
    funcoes = {}
    cab = None
    for lin in ws.iter_rows(values_only=True):
        cels = [c for c in lin]
        txt = str(cels[0] or "")
        if ano is None:
            m = re.search(r"BASES EFETIVAS (\d{4})", txt.upper())
            ano = int(m.group(1)) if m else None
        if cab is None:
            if sem_acento(txt).upper().startswith("FUNCAO ORCAMENTARIA") and any(str(c).upper() == "NORTE" for c in cels[1:]):
                cab = [str(c).upper() if c else "" for c in cels]
            continue
        if not txt.strip():
            if funcoes:
                break
            continue
        valores = {}
        for k, nome in enumerate(cab):
            if nome in REGIOES + ("TOTAL",) and isinstance(cels[k], (int, float)):
                valores[nome.lower().replace("-", "_")] = round(float(cels[k]), 2)
        if "total" in valores:
            funcoes[txt.strip()] = valores
    if cab is None or len(funcoes) < MINIMO_FUNCOES:
        raise ValueError(f"Receita: quadro I não reconhecido ({len(funcoes)} funções)")
    return {"ano_base": ano, "funcoes": funcoes}


def coletar_renuncia_fiscal():
    import openpyxl
    with registrar_coleta("receita", "renuncia_fiscal") as (db, n):
        html = http.get(PAGINA, headers={**UA, "Accept": "text/html"}).text
        arqs = arquivos_da_pagina(html)
        if not arqs:
            raise RuntimeError("Receita: nenhum arquivo dgt-bases-efetivas-AAAA encontrado na página")
        ano, url = arqs[0]
        bruto = http.get(url, headers=UA).content
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            wb = openpyxl.load_workbook(io.BytesIO(bruto), read_only=True, data_only=True)
            q = ler_quadro1(wb["Q I"])
        total = sum(f["total"] for f in q["funcoes"].values() if f.get("total"))
        upsert(db, Registro, {"fonte": "receita", "tipo": "renuncia_fiscal", "chave": "BR"},
               {"titulo": "Gastos tributários", "valor": total, "dados": {**q, "arquivo": url, "total_estimado": round(total, 2)}})
        db.commit()
        n += 1
    return n.itens
