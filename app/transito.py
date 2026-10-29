"""Congestionamento das capitais (lista curada em app/dados/transito.json, do TomTom Traffic Index; atualizar uma vez por ano)."""
import json
from functools import lru_cache
from pathlib import Path

ARQ = Path(__file__).parent / "dados" / "transito.json"


@lru_cache(maxsize=1)
def dados() -> dict:
    d = json.loads(ARQ.read_text(encoding="utf-8"))
    d["itens"] = sorted(d["itens"], key=lambda i: -i["pct"])
    return d
