"""Origem de um sobrenome, a partir do resumo da Wikipédia em português (com link e licença).

Não é teste genético nem prova de ancestralidade: é o que a enciclopédia registra sobre o sobrenome.
Só aceita a página se ela fala de sobrenome, apelido ou família (página de desambiguação não serve).
"""
from __future__ import annotations

import re
from urllib.parse import quote

RX_VALIDO = re.compile(r"^[A-Za-zÀ-ÿ]+(?:[ '\-][A-Za-zÀ-ÿ]+){0,2}$")
RX_TEMA = re.compile(r"sobrenome|apelido|patron[ií]mico|fam[ií]lia", re.IGNORECASE)
UA = "BRASILMais/1.0 (site de dados abertos; origem de sobrenomes)"
AVISO = ("O que a Wikipédia registra sobre o sobrenome, com link para a fonte. Não é teste genético nem prova de "
         "ancestralidade: um sobrenome pode ter origens diferentes em famílias diferentes.")


class SemOrigem(Exception):
    pass


class Indisponivel(Exception):
    pass


def _titulos(nome: str) -> list[str]:
    base = nome.strip()
    return [f"{base} (sobrenome)", f"{base} (família)", base]


def _pedir(cli, url: str):
    """GET com nova tentativa no 429 (a Wikipédia limita pedidos por IP) e espera pelo Retry-After."""
    import time
    import httpx
    for tentativa in range(4):
        try:
            r = cli.get(url)
        except httpx.HTTPError as e:
            raise Indisponivel(str(e)) from e
        if r.status_code != 429:
            return r
        try:
            espera = float(r.headers.get("Retry-After", 0))
        except ValueError:
            espera = 0
        time.sleep(min(max(espera, 2 * (tentativa + 1)), 15))
    raise Indisponivel("limite de pedidos da Wikipédia")


def origem(nome: str) -> dict:
    nome = " ".join(nome.split())
    if not RX_VALIDO.match(nome):
        raise ValueError("nome inválido")
    import httpx
    with httpx.Client(timeout=20, headers={"User-Agent": UA}, follow_redirects=True) as cli:
        for titulo in _titulos(nome):
            r = _pedir(cli, "https://pt.wikipedia.org/api/rest_v1/page/summary/" + quote(titulo.replace(" ", "_")))
            if r.status_code == 404:
                continue
            if r.status_code != 200:
                raise Indisponivel(f"Wikipédia respondeu {r.status_code}")
            d = r.json()
            if d.get("type") == "disambiguation":
                continue
            resumo = (d.get("extract") or "").strip()
            if not resumo or not RX_TEMA.search(resumo):
                continue
            return {"nome": nome, "titulo": d.get("title", titulo), "resumo": resumo,
                    "url": (d.get("content_urls") or {}).get("desktop", {}).get("page"),
                    "fonte": "Wikipédia (português)", "licenca": "CC BY-SA 4.0", "aviso": AVISO}
    raise SemOrigem(nome)
