"""Mini-mapas dos biomas (app/dados/bioma_mini.json): o país e os seis biomas, com desenho."""
import json
from pathlib import Path

ARQ = Path(__file__).resolve().parent.parent / "app" / "dados" / "bioma_mini.json"


def test_tem_pais_e_os_seis_biomas():
    d = json.loads(ARQ.read_text(encoding="utf-8"))
    assert d["h"] == 100 and 80 < d["w"] < 130
    for chave in ("pais", "Amazônia", "Caatinga", "Cerrado", "Mata Atlântica", "Pampa", "Pantanal"):
        assert d[chave].startswith("M") and d[chave].endswith("Z"), chave
    assert len(d["Pantanal"]) < len(d["pais"])


def test_o_site_usa_o_mesmo_desenho():
    site = (ARQ.parent.parent.parent / "site" / "index.html").read_text(encoding="utf-8")
    d = json.loads(ARQ.read_text(encoding="utf-8"))
    assert d["Pampa"] in site, "rode: python -m scripts.bioma_mini e cole o JSON em BIO_MINI no site"
