"""Julgamentos de grande repercussão dos tribunais superiores (lista curada em app/dados/julgamentos.json, com fonte em cada um)."""
import json
from functools import lru_cache
from pathlib import Path

ARQ = Path(__file__).parent / "dados" / "julgamentos.json"


@lru_cache(maxsize=1)
def dados() -> dict:
    d = json.loads(ARQ.read_text(encoding="utf-8"))
    d["itens"] = sorted((i for i in d["itens"] if str(i.get("fonte", "")).startswith("https://")), key=lambda i: i["data"], reverse=True)
    return d
