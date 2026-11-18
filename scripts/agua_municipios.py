"""Superfície de água (MapBiomas Água, Coleção 5) por município, de 2016 a 2025.

Uso:
    python -m scripts.agua_municipios [zip_ou_xlsm_de_municipios] [saida.json]

Fonte: https://brasil.mapbiomas.org/iniciativas-e-produtos/agua/mapeamento-anual/ (arquivo "Múltiplos territórios",
planilha MUNICIPALITIES, aba WATER_SURFACE). Cada linha é um município (código IBGE 2025 em GEOCODE) com a área de
água mapeada por satélite, em hectares (rios, lagos, represas e áreas alagadas). Confere com a soma dos estados
(a mesma base de app/dados/agua_superficie.json): a diferença no total do país é de 1 ha.

Guarda só 2016–2025 (a janela dos outros mapas do site), em hectares arredondados. O resultado fica em
app/dados/agua_municipio.json (lido por GET /ambiente/agua/municipios).
"""
from __future__ import annotations

import io
import json
import sys
import zipfile
from datetime import date
from pathlib import Path

import openpyxl

from scripts.agua_superficie import URL

SAIDA = Path(__file__).resolve().parent.parent / "app" / "dados" / "agua_municipio.json"
ARQUIVO = "MUNICIPALITIES.xlsm"
ANOS = list(range(2016, 2026))


def _planilha(origem: str | None) -> bytes:
    if origem and Path(origem).is_file() and origem.endswith(".xlsm"):
        return Path(origem).read_bytes()
    if origem and Path(origem).is_file():
        z = zipfile.ZipFile(origem)
    else:
        import httpx
        r = httpx.get(URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=300, follow_redirects=True)
        r.raise_for_status()
        z = zipfile.ZipFile(io.BytesIO(r.content))
    return z.read(next(n for n in z.namelist() if n.endswith("-" + ARQUIVO)))


def calcular(planilha: bytes) -> dict:
    wb = openpyxl.load_workbook(io.BytesIO(planilha), read_only=True, data_only=True)
    linhas = list(wb["WATER_SURFACE"].iter_rows(values_only=True))
    cab = [str(c) for c in linhas[0]]
    ix = {c: i for i, c in enumerate(cab)}
    cols = {a: ix[f"y{a}"] for a in ANOS}
    municipios = {}
    for r in linhas[1:]:
        if not r or r[ix["CLASS_NAME"]] != "Água" or r[ix["GEOCODE"]] is None:
            continue
        cod = str(int(r[ix["GEOCODE"]]))
        municipios[cod] = {"n": str(r[ix["TERRITORY_NAME"]]).strip(),
                           "v": [round(float(r[cols[a]] or 0)) for a in ANOS]}
    return {
        "fonte": "MapBiomas Água, Coleção 5 (superfície de água anual por município, IBGE 2025)",
        "link": "https://brasil.mapbiomas.org/iniciativas-e-produtos/agua/mapeamento-anual/",
        "metodo": "Área de superfície de água mapeada por satélite (Landsat, 30 m), em hectares: rios, lagos, represas e áreas alagadas. Não é o comprimento dos rios. Muda com a cheia e a seca.",
        "gerado_em": date.today().isoformat(),
        "unidade": "ha",
        "anos": [str(a) for a in ANOS],
        "municipios": municipios,
    }


def main(argv: list[str]) -> None:
    r = calcular(_planilha(argv[0] if argv else None))
    destino = Path(argv[1]) if len(argv) > 1 else SAIDA
    destino.write_text(json.dumps(r, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{len(r['municipios'])} municípios, {r['anos'][0]}–{r['anos'][-1]} → {destino} ({destino.stat().st_size / 1e3:.0f} KB)")


if __name__ == "__main__":
    main(sys.argv[1:])
