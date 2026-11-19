"""População por estado: cor ou raça e sexo (Censo 2022), com o total do Brasil.

Uso:
    python -m scripts.populacao_censo [saida.json]

Fonte: IBGE, Censo Demográfico 2022, pela API do SIDRA (https://apisidra.ibge.gov.br):
  - tabela 9605: população residente por cor ou raça (branca, preta, parda, amarela, indígena);
  - tabela 9514: população residente por sexo (homens e mulheres), todas as idades.
Resultado em app/dados/populacao_censo.json (lido por GET /populacao). Não há pergunta de ascendência
(origem de família ou país de origem) no Censo 2022: por isso o site não mostra esse dado.
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

SAIDA = Path(__file__).resolve().parent.parent / "app" / "dados" / "populacao_censo.json"
BASE = "https://apisidra.ibge.gov.br/values"
UA = "BRASILMais/1.0 (site de dados abertos)"
COR = {"Branca": "branca", "Preta": "preta", "Parda": "parda", "Amarela": "amarela", "Indígena": "indigena", "Total": "total"}
SEXO = {"Homens": "homens", "Mulheres": "mulheres", "Total": "total"}


def _baixar(url: str) -> list[dict]:
    import httpx
    r = httpx.get(url, headers={"User-Agent": UA}, timeout=180, follow_redirects=True)
    r.raise_for_status()
    dados = r.json()
    return dados[1:]          # a primeira linha é o cabeçalho com os nomes das colunas


def _soma_por_uf(linhas: list[dict], rotulo, mapa: dict) -> dict:
    """{código do estado (2 dígitos): {campo: pessoas}} a partir das linhas do SIDRA."""
    out: dict[str, dict] = {}
    for x in linhas:
        uf = str(x["D1C"])
        k = mapa.get(rotulo(x))
        if k is None:
            continue
        out.setdefault(uf, {"nome": x["D1N"]})[k] = int(float(x["V"]))
    return out


def calcular(raca: list[dict], sexo: list[dict]) -> dict:
    por_raca = _soma_por_uf(raca, lambda x: x["D4N"], COR)
    por_sexo = _soma_por_uf(sexo, lambda x: x["D4N"], SEXO)
    estados = {}
    for uf, r in por_raca.items():
        s = por_sexo.get(uf, {})
        estados[uf] = {"nome": r.pop("nome"), **{k: v for k, v in r.items()}, "homens": s.get("homens"), "mulheres": s.get("mulheres")}
    total = {k: sum(e.get(k) or 0 for e in estados.values()) for k in ("total", "branca", "preta", "parda", "amarela", "indigena", "homens", "mulheres")}
    return {
        "fonte": "IBGE, Censo Demográfico 2022 (SIDRA, tabelas 9605 e 9514)",
        "link": "https://sidra.ibge.gov.br/tabela/9605",
        "metodo": "Pessoas residentes por cor ou raça declarada e por sexo, em 2022. A cor ou raça é autodeclarada. Não há no Censo 2022 pergunta sobre ascendência ou país de origem da família.",
        "gerado_em": date.today().isoformat(),
        "ano": 2022,
        "brasil": total,
        "estados": estados,
    }


def main(argv: list[str]) -> None:
    raca = _baixar(f"{BASE}/t/9605/n3/all/v/93/p/2022/c86/all")
    sexo = _baixar(f"{BASE}/t/9514/n3/all/v/93/p/2022/c2/all/c287/100362")
    r = calcular(raca, sexo)
    destino = Path(argv[0]) if argv else SAIDA
    destino.write_text(json.dumps(r, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{len(r['estados'])} estados; Brasil: {r['brasil']['total']:,} pessoas → {destino}".replace(",", "."))


if __name__ == "__main__":
    main(sys.argv[1:])
