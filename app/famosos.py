"""Artistas e famosos: leitura de app/dados/famosos.json (gerado por scripts/famosos.py a partir do Wikidata e do Deezer).

Regras que valem para toda a aba:
  * NÃO existe base aberta de "horas ouvidas" por artista (Spotify, YouTube Music e Apple Music não publicam). O ranking de música usa o
    número de FÃS NO DEEZER (identidade pelo ID do artista no Wikidata, sem busca por nome) e os seguidores que o Wikidata registra, sempre com a data;
  * seguidores de redes diferentes nunca se somam (a mesma pessoa aparece em várias) e o número é o do dia registrado, não o de hoje;
  * "obras mais conhecidas" = as com mais idiomas na Wikipédia; "mais recentes" = as de data mais nova que o Wikidata registra (o Wikidata não é completo);
  * campo ausente fica nulo (a tela escreve "não informado"); nada é estimado; o estado é o de NASCIMENTO, não o de moradia;
  * só pessoas com cidadania brasileira no Wikidata e com artigo ou registro lá; não é lista de "melhores", é de quem tem dado aberto.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

ARQ = Path(__file__).resolve().parent / "dados" / "famosos.json"

AVISO = ("Dados abertos do Wikidata (pessoas, profissões, gêneros, obras, prêmios e seguidores com data) e do Deezer (fãs). Não há base aberta de horas ouvidas por artista; "
         "ranking por fãs ou seguidores mostra alcance em uma plataforma, não qualidade nem tudo o que a pessoa fez. O Wikidata é colaborativo e incompleto: quem não aparece "
         "ou aparece sem um dado não deixou de existir.")


@lru_cache(maxsize=1)
def _dados() -> dict | None:
    if not ARQ.exists():
        return None
    return json.loads(ARQ.read_text(encoding="utf-8"))


def recarregar() -> None:
    _dados.cache_clear()


def base() -> dict | None:
    d = _dados()
    return None if d is None else {**d, "aviso": AVISO}


def resumo() -> dict | None:
    d = _dados()
    if d is None:
        return None
    p = d["p"]
    return {"gerado": d["gerado"], "total": len(p), "grupos": d["grupos"],
            "com_deezer": sum(1 for x in p if "dz" in x), "com_seguidores": sum(1 for x in p if "rs" in x), "aviso": AVISO}


def pessoa(q: str) -> dict | None:
    d = _dados()
    if d is None:
        return None
    return next((x for x in d["p"] if x["q"] == q), None)
