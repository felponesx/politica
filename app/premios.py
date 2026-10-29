"""Prêmios do Brasil: títulos e medalhas por esporte (lista curada em app/dados/premios.json)."""
import json
from functools import lru_cache
from pathlib import Path

ARQ = Path(__file__).parent / "dados" / "premios.json"


@lru_cache(maxsize=1)
def dados() -> dict:
    d = json.loads(ARQ.read_text(encoding="utf-8"))
    for c in d["categorias"]:
        c["total"] = sum(len(g["brasil"]) for g in c["grupos"])
    return d
