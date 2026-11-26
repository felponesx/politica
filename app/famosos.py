"""Artistas e famosos: leitura de app/dados/famosos.json (gerado por scripts/famosos.py a partir do Wikidata e do Deezer).

Regras que valem para toda a aba:
  * NÃO existe base aberta de "horas ouvidas" por artista (Spotify, YouTube Music e Apple Music não publicam). O ranking de música usa o
    número de FÃS NO DEEZER (identidade pelo ID do artista no Wikidata, sem busca por nome) e os seguidores que o Wikidata registra, sempre com a data;
  * seguidores de redes diferentes nunca se somam (a mesma pessoa aparece em várias) e o número é o do dia registrado, não o de hoje;
  * "obras mais conhecidas" = as com mais idiomas na Wikipédia; "mais recentes" = as de data mais nova que o Wikidata registra (o Wikidata não é completo);
  * campo ausente fica nulo (a tela escreve "não informado"); nada é estimado; o estado é o de NASCIMENTO, não o de moradia;
  * foto = imagem principal do Wikidata, hospedada no Wikimedia Commons (licença livre); sempre com autor, licença e link do arquivo (`/famosos/fotos/{n}`);
  * só pessoas com cidadania brasileira no Wikidata e com artigo ou registro lá; não é lista de "melhores", é de quem tem dado aberto.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

ARQ = Path(__file__).resolve().parent / "dados" / "famosos.json"
PASTA_FOTOS = Path(__file__).resolve().parent / "dados" / "famosos_fotos"
ARQ_FOTOS = Path(__file__).resolve().parent / "dados" / "famosos_fotos.json"
N_FOTOS = 5  # arquivos de fotos: 0 músicos, 1 atores, 2 redes, 3 dubladores/arquitetos/engenheiros, 4 outras profissões

AVISO = ("Dados abertos do Wikidata (pessoas, profissões, gêneros, obras, prêmios e seguidores com data) e do Deezer (fãs). Não há base aberta de horas ouvidas por artista; "
         "ranking por fãs ou seguidores mostra alcance em uma plataforma, não qualidade nem tudo o que a pessoa fez. O Wikidata é colaborativo e incompleto: quem não aparece "
         "ou aparece sem um dado não deixou de existir.")


def arquivo_da_foto(grupos: list[str]) -> int:
    """Em qual dos arquivos de fotos fica a foto de quem está nestes grupos (o primeiro que servir)."""
    for g, n in (("musico", 0), ("ator", 1), ("rede", 2), ("dublador", 3), ("arquiteto", 3), ("engenheiro", 3)):
        if g in grupos:
            return n
    return 4


def _creditos() -> dict:
    if not ARQ_FOTOS.exists():
        return {}
    c = json.loads(ARQ_FOTOS.read_text(encoding="utf-8"))
    return {q: v for q, v in c.items() if (PASTA_FOTOS / f"{q}.webp").exists()}


@lru_cache(maxsize=1)
def _dados() -> dict | None:
    if not ARQ.exists():
        return None
    d = json.loads(ARQ.read_text(encoding="utf-8"))
    cred = _creditos()
    for p in d["p"]:
        if p["q"] in cred:
            p["ft"] = arquivo_da_foto(p["g"])  # a tela baixa só o arquivo de fotos de que precisa
    return d


def recarregar() -> None:
    _dados.cache_clear()
    fotos.cache_clear()


@lru_cache(maxsize=N_FOTOS)
def fotos(n: int) -> dict | None:
    """{Q: [webp em base64, autor, licença, link da licença, página do arquivo no Wikimedia Commons]} das pessoas do arquivo n."""
    import base64
    d = _dados()
    if d is None or not 0 <= n < N_FOTOS:
        return None
    cred = _creditos()
    return {p["q"]: [base64.b64encode((PASTA_FOTOS / f"{p['q']}.webp").read_bytes()).decode("ascii"), *cred[p["q"]]]
            for p in d["p"] if p.get("ft") == n}


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
