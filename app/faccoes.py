"""Facções criminosas de maior alcance (lista curada em app/dados/faccoes.json; cada uma com fonte)."""
import json
from functools import lru_cache
from pathlib import Path

ARQ = Path(__file__).parent / "dados" / "faccoes.json"


@lru_cache(maxsize=1)
def dados() -> dict:
    d = json.loads(ARQ.read_text(encoding="utf-8"))
    d["itens"] = [i for i in d["itens"] if str(i.get("fonte", "")).startswith("https://")]
    return d
