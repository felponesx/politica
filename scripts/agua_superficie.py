"""Superfície de água (MapBiomas Água, Coleção 5) por bioma, estado e região hidrográfica, de 1985 a 2025.

Uso:
    python -m scripts.agua_superficie [zip_ou_pasta_com_as_planilhas] [saida.json]

Fonte: https://brasil.mapbiomas.org/iniciativas-e-produtos/agua/mapeamento-anual/ (arquivo "Múltiplos territórios", planilhas
BIOMES, STATES e HYDROGRAPHIC_REGIONS, aba WATER_SURFACE). Os valores estão em hectares (ha) de superfície de água mapeada por
satélite (30 m): rios, lagos, represas e áreas alagadas. NÃO é o comprimento de rios (km) e muda com a cheia e a seca.
O resultado fica em app/dados/agua_superficie.json (lido por GET /ambiente/agua).
"""
from __future__ import annotations

import io
import json
import sys
import zipfile
from datetime import date
from pathlib import Path

import openpyxl

URL = "https://brasil.mapbiomas.org/wp-content/uploads/sites/3/2026/10/5-MAPBIOMAS-BRAZIL-WATER-ANNUAL-SURFACE-WATER-COLLECTION_5-MULTIPLE_TERRITORIES.zip"
SAIDA = Path(__file__).resolve().parent.parent / "app" / "dados" / "agua_superficie.json"
ARQUIVOS = {"biomas": "BIOMES.xlsm", "estados": "STATES.xlsm", "regioes": "HYDROGRAPHIC_REGIONS.xlsm"}
UF_DE_NOME = {"Acre": "AC", "Alagoas": "AL", "Amapá": "AP", "Amazonas": "AM", "Bahia": "BA", "Ceará": "CE", "Distrito Federal": "DF",
              "Espírito Santo": "ES", "Goiás": "GO", "Maranhão": "MA", "Mato Grosso": "MT", "Mato Grosso do Sul": "MS", "Minas Gerais": "MG",
              "Pará": "PA", "Paraíba": "PB", "Paraná": "PR", "Pernambuco": "PE", "Piauí": "PI", "Rio de Janeiro": "RJ", "Rio Grande do Norte": "RN",
              "Rio Grande do Sul": "RS", "Rondônia": "RO", "Roraima": "RR", "Santa Catarina": "SC", "São Paulo": "SP", "Sergipe": "SE",
              "Tocantins": "TO"}


def _ler(origem: bytes, nome: str) -> list[dict]:
    wb = openpyxl.load_workbook(io.BytesIO(origem), read_only=True, data_only=True)
    ws = wb["WATER_SURFACE"]
    linhas = list(ws.iter_rows(values_only=True))
    cab = [str(c) for c in linhas[0]]
    anos = [(i, int(c[1:])) for i, c in enumerate(cab) if c.startswith("y") and c[1:].isdigit()]
    out = []
    for r in linhas[1:]:
        if not r or not r[1]:
            continue
        out.append({"nome": str(r[1]).strip(), "ha": {a: round(float(r[i])) for i, a in anos if r[i] is not None}})
    return out


def calcular(arquivos: dict[str, bytes]) -> dict:
    biomas = {x["nome"]: x["ha"] for x in _ler(arquivos["biomas"], "biomas")}
    estados = {}
    for x in _ler(arquivos["estados"], "estados"):
        uf = UF_DE_NOME.get(x["nome"])
        if uf:
            estados[uf] = {"nome": x["nome"], "ha": x["ha"]}
    regioes = {x["nome"].title(): x["ha"] for x in _ler(arquivos["regioes"], "regioes")}
    anos = sorted(next(iter(biomas.values())).keys())
    brasil = {a: sum(v.get(a, 0) for v in biomas.values()) for a in anos}
    return {
        "fonte": "MapBiomas Água, Coleção 5 (estatísticas de superfície de água anual, 1985–2025)",
        "link": "https://brasil.mapbiomas.org/iniciativas-e-produtos/agua/mapeamento-anual/",
        "metodo": "Área de superfície de água mapeada por satélite (Landsat, 30 m), em hectares: rios, lagos, represas e áreas alagadas. Não é o comprimento dos rios.",
        "gerado_em": date.today().isoformat(),
        "unidade": "ha",
        "anos": [str(a) for a in anos],
        "brasil": brasil,
        "biomas": biomas,
        "estados": estados,
        "regioes_hidrograficas": regioes,
    }


def _arquivos(origem: str | None) -> dict[str, bytes]:
    if origem and Path(origem).is_dir():
        pasta = Path(origem)
        return {k: next(pasta.glob(f"*-{n}")).read_bytes() for k, n in ARQUIVOS.items()}
    if origem and Path(origem).is_file():
        z = zipfile.ZipFile(origem)
    else:
        import httpx
        r = httpx.get(URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=300, follow_redirects=True)
        r.raise_for_status()
        z = zipfile.ZipFile(io.BytesIO(r.content))
    return {k: z.read(next(n for n in z.namelist() if n.endswith("-" + arq))) for k, arq in ARQUIVOS.items()}


def main(argv: list[str]) -> None:
    r = calcular(_arquivos(argv[0] if argv else None))
    destino = Path(argv[1]) if len(argv) > 1 else SAIDA
    destino.write_text(json.dumps(r, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    u = r["anos"][-1]
    print(f"{len(r['biomas'])} biomas, {len(r['estados'])} estados, {len(r['regioes_hidrograficas'])} regiões; Brasil em {u}: {r['brasil'][int(u)]/100:,.0f} km² → {destino}")


if __name__ == "__main__":
    main(sys.argv[1:])
