"""Testa os 27 diários oficiais estaduais e diz o que cada um oferece: API, busca em HTML, arquivos para baixar ou só PDF.

Uso: python -m scripts.diag_diarios [saida.json]   (rode também pelo robô: o ambiente do Claude não alcança alguns sites)
Não coleta nada: só a página inicial e uma busca de teste por "concurso" quando há um caminho conhecido.
"""
from __future__ import annotations

import json
import re
import sys
from urllib.parse import urljoin, urlparse

import httpx

UA = {"User-Agent": "Mozilla/5.0 (compatible; BRASILmais/1.0; dados publicos)"}
# endereços da lista do Felipe (12/11/2026)
DIARIOS = {
    "AC": "https://diario.ac.gov.br/", "AL": "https://www.imprensaoficialal.com.br/", "AP": "https://www.diariooficial.ap.gov.br/",
    "AM": "https://doe.am.gov.br/", "BA": "https://dool.egba.ba.gov.br/", "CE": "https://www.diariooficial.ce.gov.br/",
    "DF": "https://dodf.df.gov.br/", "ES": "https://ioes.dio.es.gov.br/", "GO": "https://diariooficial.go.gov.br/",
    "MA": "https://diariooficial.ma.gov.br/", "MT": "https://www.iomat.mt.gov.br/", "MS": "https://www.imprensaoficial.ms.gov.br/",
    "MG": "https://www.jornalminasgerais.mg.gov.br/", "PA": "https://www.ioepa.com.br/", "PB": "https://auniao.pb.gov.br/servicos/diario-oficial",
    "PR": "https://www.documentos.dioe.pr.gov.br/", "PE": "https://www.cepe.com.br/diario-oficial", "PI": "https://www.diariooficial.pi.gov.br/",
    "RJ": "https://portal.ioerj.com.br/diario-oficial/", "RN": "https://www.diariooficial.rn.gov.br/", "RS": "https://diariooficial.rs.gov.br/",
    "RO": "https://diariooficial.ro.gov.br/", "RR": "https://imprensaoficial.rr.gov.br/", "SC": "https://doe.sc.gov.br/",
    "SP": "https://doe.sp.gov.br/", "SE": "https://doe.se.gov.br/", "TO": "https://diariooficial.to.gov.br/",
}


def testar(cli: httpx.Client, uf: str, url: str) -> dict:
    out = {"uf": uf, "url": url}
    try:
        r = cli.get(url)
    except Exception as e:  # noqa: BLE001
        return out | {"responde": False, "erro": f"{type(e).__name__}: {str(e)[:120]}", "metodo": "nao_responde"}
    t = r.text if "html" in r.headers.get("content-type", "") or r.text[:20].lstrip().startswith("<") else ""
    base = f"{urlparse(str(r.url)).scheme}://{urlparse(str(r.url)).netloc}"
    pdfs = sorted({urljoin(str(r.url), h) for h in re.findall(r'href="([^"]+\.pdf[^"]*)"', t, re.I)})
    out |= {"responde": r.status_code < 400, "http": r.status_code, "final": str(r.url), "tipo": r.headers.get("content-type", ""),
            "tamanho": len(r.content), "pdfs_na_pagina": len(pdfs), "exemplo_pdf": pdfs[:2],
            "formulario_busca": bool(re.search(r'<form[^>]*(busca|pesquisa|search|consulta)', t, re.I) or re.search(r'name="(q|termo|busca|pesquisa|texto)"', t, re.I)),
            "pistas_api": sorted(set(re.findall(r'(?:https?:)?//[a-z0-9.-]*/?[a-z0-9/_-]*(?:/api/|apifront|/wp-json/|graphql|/rest/)[a-z0-9/_.-]*', t, re.I)))[:6],
            "spa": bool(re.search(r'id="(root|app|__next)"', t)) and len(t) < 60000}
    # plataforma comum (MT/ES/GO): busca em Elasticsearch
    try:
        b = cli.get(f"{base}/busca/busca/buscar/query/0/", params={"1": 1, "q": "concurso"}, timeout=30)
        out["plataforma_comum"] = b.status_code == 200 and b.text.lstrip().startswith("{") and '"hits"' in b.text[:400]
    except Exception:  # noqa: BLE001
        out["plataforma_comum"] = False
    out["metodo"] = ("api" if out["plataforma_comum"] or uf == "SP" else "pdf" if out["pdfs_na_pagina"] and not out["formulario_busca"]
                     else "busca_html" if out["formulario_busca"] else "spa_sem_rota" if out["spa"] else "desconhecido") if out["responde"] else "erro_http"
    return out


def main(saida: str | None = None) -> list[dict]:
    with httpx.Client(headers=UA, timeout=30, follow_redirects=True) as cli:
        res = [testar(cli, uf, url) for uf, url in DIARIOS.items()]
    for x in res:
        print(f"{x['uf']} {x.get('http', '---'):>3} {x['metodo']:<13} pdfs={x.get('pdfs_na_pagina', 0):<3} busca={x.get('formulario_busca')} "
              f"plataforma={x.get('plataforma_comum')} {x.get('final', x.get('erro', ''))[:70]}")
    if saida:
        with open(saida, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=1)
    return res


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
