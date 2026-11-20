"""Religião por estado (Censo 2022) e organizações religiosas registradas por estado e ano (Cadastro Central de Empresas).

Uso:
    python -m scripts.religiao [saida.json]

Fontes (IBGE, pela API do SIDRA):
  - tabela 9537: pessoas de 10 anos ou mais de idade, por religião, sexo e grupos de idade (Censo Demográfico 2022).
    Usa só a combinação "Total" de sexo e de idade. O Censo pergunta UMA religião por pessoa: não há
    porcentagem de quem declara mais de uma religião.
  - tabela 9528 (2022–2024), Cadastro Central de Empresas: unidades locais da classe 94.91-0 "Atividades de
    organizações religiosas". Conta os locais registrados (templos, sedes, filiais); não é a contagem de todas as
    igrejas (grupos não registrados não entram). A tabela 6450 (2006–2021) não é comparável: em 2021 dá 85.806 e em
    2022 já dá 197.594, por isso não entra na série.
Resultado em app/dados/religiao.json (lido por GET /religiao).
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

from app.populacao import SIGLA

SAIDA = Path(__file__).resolve().parent.parent / "app" / "dados" / "religiao.json"
BASE = "https://apisidra.ibge.gov.br/values"
UA = "BRASILMais/1.0 (site de dados abertos)"
CODIGO_RELIGIOSAS = "117871"          # CNAE 2.0 94.91-0 Atividades de organizações religiosas
RELIGIOES = {
    "Total": "total",
    "Católica Apostólica Romana": "catolica",
    "Evangélicas": "evangelicas",
    "Espírita": "espirita",
    "Umbanda e Candomblé": "umbanda_candomblé",
    "Tradições indígenas": "tradicoes_indigenas",
    "Outras religiosidades": "outras",
    "Sem religião": "sem_religiao",
    "Não sabe": "nao_sabe",
    "Sem declaração": "sem_declaracao",
}


def _baixar(url: str) -> list[dict]:
    import httpx
    r = httpx.get(url, headers={"User-Agent": UA}, timeout=300, follow_redirects=True)
    r.raise_for_status()
    return r.json()[1:]                  # a primeira linha é o cabeçalho


def censo_religiao(linhas: list[dict]) -> dict:
    """{código UF: {nome, total, categorias: {chave: pessoas}}} só com sexo Total e idade Total."""
    out: dict[str, dict] = {}
    for x in linhas:
        if x["D5N"] != "Total" or x["D6N"] != "Total":
            continue
        chave = RELIGIOES.get(x["D4N"])
        if chave is None:
            continue
        uf = out.setdefault(str(x["D1C"]), {"nome": x["D1N"], "total": None, "categorias": {}})
        v = int(float(x["V"]))
        if chave == "total":
            uf["total"] = v
        else:
            uf["categorias"][chave] = v
    return out


def igrejas(linhas: list[dict]) -> dict:
    """{código UF: {ano: unidades}} para a classe 94.91-0 (e {"BR": {ano: total}} a partir da linha do país)."""
    out: dict[str, dict] = {}
    for x in linhas:
        if x.get("D4C") != CODIGO_RELIGIOSAS:
            continue
        chave = "BR" if str(x["D1C"]) == "1" else str(x["D1C"])
        out.setdefault(chave, {})[str(x["D3N"])] = int(float(x["V"]))
    return out


def calcular(censo: list[dict], unidades: list[dict]) -> dict:
    c = censo_religiao(censo)
    unid = igrejas(unidades)
    estados = {}
    for cod, d in c.items():
        sigla = SIGLA.get(cod, cod)
        estados[sigla] = {"nome": d["nome"], "total": d["total"], "categorias": d["categorias"],
                          "igrejas": unid.get(cod, {})}
    brasil_cat: dict[str, int] = {}
    for d in c.values():
        for k, v in d["categorias"].items():
            brasil_cat[k] = brasil_cat.get(k, 0) + v
    brasil_total = sum(d["total"] or 0 for d in c.values())
    return {
        "fonte": "IBGE: Censo Demográfico 2022 (religião, tabela 9537) e Cadastro Central de Empresas (unidades locais de organizações religiosas, CNAE 94.91-0, tabelas 6450 e 9528)",
        "link": "https://sidra.ibge.gov.br/tabela/9537",
        "metodo": "Religião declarada por pessoas de 10 anos ou mais de idade no Censo 2022 (uma religião por pessoa). "
                  "Não há no Censo porcentagem de quem declara mais de uma religião. Pode haver diferença de até 2 pessoas entre o total "
                  "e a soma das religiões em alguns estados (arredondamento do IBGE). A contagem de organizações religiosas é de unidades "
                  "locais registradas como organizações religiosas no Cadastro Central de Empresas, de 2022 em diante (não inclui grupos sem registro).",
        "gerado_em": date.today().isoformat(),
        "censo_ano": 2022,
        "base": "pessoas de 10 anos ou mais de idade",
        "brasil": {"total": brasil_total, "categorias": brasil_cat, "igrejas": unid.get("BR", {})},
        "estados": estados,
    }


def main(argv: list[str]) -> None:
    censo = _baixar(f"{BASE}/t/9537/n3/all/v/140/p/2022/c133/all/c2/all/c58/all")
    unidades = _baixar(f"{BASE}/t/9528/n1/all/n3/all/v/706/p/all/c12762/{CODIGO_RELIGIOSAS}")
    r = calcular(censo, unidades)
    destino = Path(argv[0]) if argv else SAIDA
    destino.write_text(json.dumps(r, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{len(r['estados'])} estados; Brasil: {r['brasil']['total']:,} pessoas de 10 anos ou mais; "
          f"organizações religiosas {sorted(r['brasil']['igrejas'].items())[-1] if r['brasil']['igrejas'] else '—'} → {destino}".replace(",", "."))


if __name__ == "__main__":
    main(sys.argv[1:])
