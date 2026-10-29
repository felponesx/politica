"""Prêmios do Brasil: títulos e medalhas por esporte (lista curada em app/dados/premios.json)."""
import json
from functools import lru_cache
from pathlib import Path

ARQ = Path(__file__).parent / "dados" / "premios.json"
WIKI = Path(__file__).parent / "dados" / "premios_wiki.json"


@lru_cache(maxsize=1)
def dados() -> dict:
    d = json.loads(ARQ.read_text(encoding="utf-8"))
    wiki = json.loads(WIKI.read_text(encoding="utf-8")) if WIKI.exists() else {}
    for c in d["categorias"]:
        c["total"] = sum(len(g["brasil"]) for g in c["grupos"])
        for gi, g in enumerate(c["grupos"]):
            for ei, e in enumerate(g["brasil"]):
                e["chave"] = f"{c['slug']}-{gi}-{ei}"
                w = wiki.get(e["chave"])
                if w and w.get("texto"):  # história e imagem vêm do verbete da Wikipédia (CC BY-SA), com o link
                    e["historia"] = {"titulo": w["titulo"], "texto": w["texto"], "pagina": w["pagina"], "imagem": w.get("arquivo")}
    return d
