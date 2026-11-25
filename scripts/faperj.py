"""FAPERJ — projetos contemplados (busca pública "Resumo de projetos contemplados", desde julho de 2007).

Uso:
    python -m scripts.faperj            # varre a busca sem filtro, página por página, e grava app/dados/faperj_projetos.json (retoma de onde parou)
    python -m scripts.faperj --refazer  # ignora o que já foi lido

A busca é um formulário POST (`servicos/buscaprojetosinfaperj/busca_resultados.phtml`; campos edicao, nome_pesquisador, titulo_projeto,
palavra_chave, area_conhecimento, pessoa_juridica, pagina). Sem filtro (edicao=0) devolve 10 projetos por página, até a página vir vazia.
Cada projeto traz: pesquisador e a instituição ("Nome - Instituição"), programa (edição), título, área e palavras-chave; o endereço de detalhe
(`busca_detalhe.phtml?atvnumero=N`) tem o resumo. A FAPERJ NÃO publica o valor de cada auxílio: o valor fica "não informado".
Respeito: 4 conexões, pausa curta entre pedidos, tentativas com espera; nada além da busca pública.
"""
from __future__ import annotations

import html
import json
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

import httpx

RAIZ = Path(__file__).resolve().parent.parent
SAIDA = RAIZ / "app" / "dados" / "faperj_projetos.json"
URL = "https://siteantigo.faperj.br/servicos/buscaprojetosinfaperj/busca_resultados.phtml"
PAGINA_BUSCA = "https://siteantigo.faperj.br/servicos/buscaprojetosinfaperj/busca_projeto.phtml"
UA = {"User-Agent": "Mozilla/5.0 (compatible; BRASILMais/1.0; dados abertos)"}
LIMITE_PAGINAS = 20000


def _limpo(t: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", t))).strip()


def ler_pagina(texto: str) -> list[dict]:
    """Projetos de uma página de resultados. Cada bloco tem NOME, EDIÇÃO, TÍTULO, ÁREA, PALAVRAS-CHAVES e o link de detalhe."""
    out = []
    for bloco in re.split(r"(?=<[^>]*>\s*NOME:)", texto):
        if "NOME:" not in bloco:
            continue
        def campo(rotulo, prox):
            m = re.search(rotulo + r"\s*(?:</[^>]+>\s*)*(.*?)(?=" + prox + r"|$)", bloco, re.S | re.I)
            return _limpo(m.group(1)) if m else ""
        nome = campo(r"NOME:", r"EDI[ÇC][ÃA]O:")
        edicao = campo(r"EDI[ÇC][ÃA]O:", r"T[ÍI]TULO:")
        titulo = campo(r"T[ÍI]TULO:", r"[ÁA]REA:")
        area = campo(r"[ÁA]REA:", r"PALAVRAS-CHAVES?:")
        m = re.search(r"atvnumero=(\d+)", bloco)
        if not m or not nome:
            continue
        # "Fulano de Tal - Universidade X": o primeiro " - " separa o pesquisador da instituição
        pesq, _, inst = nome.partition(" - ")
        out.append({"id": int(m.group(1)), "pesquisador": pesq.strip() or None, "instituicao": inst.strip() or None, "edicao": edicao or None,
                    "titulo": titulo or None, "area": area or None})
    return out


def _pedir(cli: httpx.Client, pagina: int) -> list[dict] | None:
    for t in range(5):
        try:
            r = cli.post(URL, data={"edicao": "0", "nome_pesquisador": "", "titulo_projeto": "", "palavra_chave": "", "area_conhecimento": "",
                                    "pessoa_juridica": "", "pagina": str(pagina)})
            if r.status_code == 200:
                return ler_pagina(r.text)
        except httpx.HTTPError:
            pass
        time.sleep(2 * (t + 1))
    return None


def varrer(refazer: bool = False, paralelos: int = 4) -> dict:
    atual = {}
    if SAIDA.exists() and not refazer:
        atual = json.loads(SAIDA.read_text(encoding="utf-8"))
    projetos: dict[int, dict] = {p["id"]: p for p in atual.get("projetos", [])}
    feitas = set(atual.get("paginas_lidas", []))
    cli = httpx.Client(headers=UA, timeout=60, follow_redirects=True)
    trava = threading.Lock()
    estado = {"fim": None, "falhas": []}

    def uma(p: int):
        if p in feitas or (estado["fim"] is not None and p > estado["fim"]):
            return
        r = _pedir(cli, p)
        time.sleep(0.15)
        with trava:
            if r is None:
                estado["falhas"].append(p)
                return
            feitas.add(p)
            if not r:                                           # página vazia: acabou
                estado["fim"] = p if estado["fim"] is None else min(estado["fim"], p)
                return
            for x in r:
                projetos[x["id"]] = x
            if len(feitas) % 100 == 0:
                print(f"  {len(feitas)} páginas, {len(projetos)} projetos", flush=True)

    p0 = 1
    while estado["fim"] is None and p0 < LIMITE_PAGINAS:
        with ThreadPoolExecutor(max_workers=paralelos) as ex:
            list(ex.map(uma, range(p0, p0 + 200)))
        p0 += 200
        _gravar(projetos, feitas, parcial=True)
    # páginas que falharam são tentadas mais uma vez
    for p in sorted(estado["falhas"]):
        uma(p)
    return _gravar(projetos, feitas, estado["falhas"], parcial=False)


def _gravar(projetos, feitas, falhas=None, parcial=False) -> dict:
    d = {"fonte": "FAPERJ — projetos contemplados (busca pública)", "url": PAGINA_BUSCA, "coletado_em": date.today().isoformat(), "parcial": parcial,
         "paginas_lidas": sorted(feitas), "paginas_com_falha": sorted(set(falhas or []) - set(feitas)),
         "projetos": sorted(projetos.values(), key=lambda x: x["id"])}
    SAIDA.write_text(json.dumps(d, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return d


if __name__ == "__main__":
    d = varrer(refazer="--refazer" in sys.argv)
    print(f"{len(d['projetos'])} projetos em {len(d['paginas_lidas'])} páginas; falhas: {d['paginas_com_falha'][:10]} → {SAIDA.name}")
