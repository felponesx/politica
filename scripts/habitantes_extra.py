"""Quem está saindo das cidades grandes, saúde mental e trabalho por aplicativo, por estado (IBGE, pela API do SIDRA).

Uso:
    python -m scripts.habitantes_extra [saida.json]

Fontes:
  - Censo 2010 (tabela 1378) e Censo 2022 (tabela 9514), população residente por município. Os municípios são agrupados
    pelo tamanho que tinham em 2010 (até 20 mil, de 20 a 100 mil, de 100 a 500 mil, acima de 500 mil) e mostra-se quanto
    cada grupo cresceu ou encolheu até 2022, por estado e no Brasil.
  - PNS 2013 (tabela 4407): pessoas de 18 anos ou mais com depressão, entre as que têm alguma doença crônica (física ou mental).
    A PNS mais recente publicada no SIDRA para essa categoria é de 2013.
  - PNAD Contínua 2025 (tabela 10482): pessoas que trabalharam por meio de plataformas de serviço, no Brasil, por tipo de
    plataforma. No SIDRA essa tabela não tem detalhe por estado.
Resultado em app/dados/habitantes_extra.json (lido por GET /populacao/extra).
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

from app.populacao import SIGLA

SAIDA = Path(__file__).resolve().parent.parent / "app" / "dados" / "habitantes_extra.json"
BASE = "https://apisidra.ibge.gov.br/values"
UA = "BRASILMais/1.0 (site de dados abertos)"
FAIXAS = [("ate_20k", "até 20 mil", 0, 20_000), ("de_20_100k", "de 20 a 100 mil", 20_000, 100_000),
          ("de_100_500k", "de 100 a 500 mil", 100_000, 500_000), ("acima_500k", "acima de 500 mil", 500_000, 10**12)]
DEPRESSAO = "33055"        # 'Depressão' na tabela 4407 (PNS 2013)
TOTAL_CRONICA = "33046"    # 'Total' na tabela 4407
PLATAFORMAS = {"83211": "Aplicativo de táxi", "83212": "Aplicativo de transporte particular de passageiros",
               "83213": "Aplicativo de entrega de comida, produtos ou mercadorias", "83214": "Aplicativo de prestação de serviços gerais"}


def _baixar(url: str) -> list[dict]:
    import httpx
    r = httpx.get(url, headers={"User-Agent": UA}, timeout=300, follow_redirects=True)
    r.raise_for_status()
    return r.json()[1:]


def _num(v) -> float | None:
    """Valor do SIDRA como número; '-' e '..' (sem dado) viram None, nunca zero."""
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _faixa(pop: int) -> str:
    for chave, _, lo, hi in FAIXAS:
        if lo < pop <= hi or (chave == "ate_20k" and pop <= hi):
            return chave
    return FAIXAS[-1][0]


def crescimento(pop2010: list[dict], pop2022: list[dict]) -> dict:
    """{UF (sigla ou 'BR'): {faixa: {municipios, pop2010, pop2022, variacao_pct}}} pelo tamanho que o município tinha em 2010."""
    p22 = {str(x["D1C"]): int(_num(x["V"])) for x in pop2022 if _num(x.get("V")) is not None}
    out: dict[str, dict] = {}
    for x in pop2010:
        if _num(x.get("V")) is None:
            continue
        cod, p10 = str(x["D1C"]), int(_num(x["V"]))
        if cod not in p22:
            continue
        uf = SIGLA.get(cod[:2])
        if uf is None:
            continue
        faixa = _faixa(p10)
        for chave in (uf, "BR"):
            d = out.setdefault(chave, {}).setdefault(faixa, {"municipios": 0, "pop2010": 0, "pop2022": 0})
            d["municipios"] += 1
            d["pop2010"] += p10
            d["pop2022"] += p22[cod]
    for ch in out.values():
        for f in ch.values():
            f["variacao_pct"] = round((f["pop2022"] / f["pop2010"] - 1) * 100, 2) if f["pop2010"] else None
    return out


def depressao(linhas: list[dict]) -> dict:
    """{'BR': {depressao_mil, cronica_mil, pct}} = pessoas com depressão ÷ pessoas com alguma doença crônica (PNS 2013)."""
    dep, tot = {}, {}
    for x in linhas:
        sigla = "BR" if str(x["D1C"]) == "1" else None   # o SIDRA só publica esta categoria para o Brasil
        if sigla is None:
            continue
        v = _num(x.get("V"))
        if v is None:
            continue
        if x["D4C"] == DEPRESSAO:
            dep[sigla] = v
        elif x["D4C"] == TOTAL_CRONICA:
            tot[sigla] = v
    out = {}
    for s in dep:   # a PNS 2013 não publica o total com doença crônica no SIDRA (vem '-'): então não há porcentagem
        out[s] = {"depressao_mil": round(dep[s], 1), "cronica_mil": round(tot[s], 1) if s in tot else None,
                  "pct": round(dep[s] / tot[s] * 100, 1) if tot.get(s) else None}
    return out


def plataformas(linhas: list[dict]) -> dict:
    """{'total_mil': ..., 'por_tipo': {nome: mil pessoas}} no Brasil, PNAD 2025."""
    tot, tipos = None, {}
    for x in linhas:
        if str(x["D1C"]) != "1":
            continue
        cod = str(x.get("D4C") or "")
        v = _num(x.get("V"))
        if v is None:
            continue
        if cod == "83215":
            tot = v
        elif cod in PLATAFORMAS:
            tipos[PLATAFORMAS[cod]] = v
    return {"ano": 2025, "total_mil": tot, "por_tipo": tipos}


def main(argv: list[str]) -> None:
    p2010 = _baixar(f"{BASE}/t/1378/n6/all/v/93/p/2010")
    p2022 = _baixar(f"{BASE}/t/9514/n6/all/v/93/p/2022/c2/6794")
    dep = _baixar(f"{BASE}/t/4407/n1/all/v/4375/p/2013/c668/33046,33055")
    plat = _baixar(f"{BASE}/t/10482/n1/all/v/13965/p/last%201/c2363/83215,83211,83212,83213,83214")
    r = {
        "gerado_em": date.today().isoformat(),
        "interiorizacao": {"fonte": "IBGE: Censo 2010 (tabela 1378) e Censo 2022 (tabela 9514), população residente por município",
                           "metodo": "Os municípios são agrupados pelo tamanho que tinham em 2010 e comparados com a população de 2022. "
                                     "Mostra quanto cada grupo cresceu ou encolheu, por estado e no Brasil. Não mede quem se mudou: o Censo "
                                     "não diz de onde veio cada pessoa. Municípios criados depois de 2010 não entram.",
                           "faixas": {c: n for c, n, _, _ in FAIXAS},
                           "dados": crescimento(p2010, p2022)},
        "depressao": {"fonte": "IBGE: PNS 2013 (tabela 4407)", "link": "https://sidra.ibge.gov.br/tabela/4407",
                      "metodo": "Pessoas de 18 anos ou mais que referem diagnóstico de depressão, no Brasil, em 2013 (PNS). "
                                "O SIDRA não publica por estado para esta categoria, e o total com doença crônica não sai nessa tabela, "
                                "por isso não calculamos a porcentagem: mostramos só o número.",
                      "dados": depressao(dep)},
        "plataformas": {"fonte": "IBGE: PNAD Contínua 2025 (tabela 10482)", "link": "https://sidra.ibge.gov.br/tabela/10482",
                        "metodo": "Pessoas de 14 anos ou mais ocupadas que trabalharam por meio de plataformas de serviço (no trabalho principal ou secundário). "
                                  "O SIDRA só publica esse dado para o Brasil, sem detalhe por estado.",
                        "dados": plataformas(plat)},
    }
    destino = Path(argv[0]) if argv else SAIDA
    destino.write_text(json.dumps(r, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"interiorização: {len(r['interiorizacao']['dados'])} recortes; depressão: {len(r['depressao']['dados'])}; "
          f"plataformas: {r['plataformas']['dados']['total_mil']} mil → {destino}")


if __name__ == "__main__":
    main(sys.argv[1:])
