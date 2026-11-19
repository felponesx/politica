"""Foto de cada planta e fungo da lista de espécies ameaçadas (app/dados/flora_ameacada.json), com licença aberta e crédito.

Uso:
    python -m scripts.flora_fotos [--com-nc] [--refazer] [--limite N]

--com-nc inclui também CC BY-NC (uso não comercial, com crédito), a mesma regra usada nas fotos dos animais.

Fonte: GBIF (https://www.gbif.org), registros de observação com foto. Para cada espécie (nome científico exato, no reino
Plantae ou Fungi) pega a primeira foto cuja licença permite publicar com crédito. Cada foto vira WebP de até 200 px e
grava autor, licença e link da observação. Sem foto aberta, a espécie fica sem foto.

Saída:
    app/dados/flora_fotos/<nome_com_underline>.webp
    app/dados/flora_fotos.json   {nome_cientifico: {arquivo, autor, licenca, obs, fonte}}
    app/dados/flora_fotos_chaves.json   {nome_cientifico: chave do GBIF ou null} (cache)
"""
from __future__ import annotations

import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from scripts.fauna_fotos import UA, baixar_webp, foto_da_chave

DADOS = Path(__file__).resolve().parent.parent / "app" / "dados"
ESPECIES = DADOS / "flora_ameacada.json"
PASTA = DADOS / "flora_fotos"
INDICE = DADOS / "flora_fotos.json"
CHAVES = DADOS / "flora_fotos_chaves.json"
REINO = {"Plantas": "Plantae", "Fungos": "Fungi"}


def chave_gbif(cli, nome: str, reino: str) -> int | None:
    r = cli.get("https://api.gbif.org/v1/species/match", params={"name": nome, "kingdom": reino}).json()
    if r.get("matchType") != "EXACT" or not r.get("usageKey"):
        return None
    return int(r["usageKey"])


def main(argv: list[str]) -> None:
    import httpx
    refazer = "--refazer" in argv
    com_nc = "--com-nc" in argv
    limite = int(argv[argv.index("--limite") + 1]) if "--limite" in argv else None
    especies = json.loads(ESPECIES.read_text(encoding="utf-8"))["especies"][:limite]
    tipo = {e[0]: e[2] for e in especies}
    nomes = list(tipo)
    chaves = json.loads(CHAVES.read_text(encoding="utf-8")) if CHAVES.exists() else {}
    indice = json.loads(INDICE.read_text(encoding="utf-8")) if INDICE.exists() else {}

    with httpx.Client(timeout=30, headers={"User-Agent": UA}, follow_redirects=True) as cli:
        for n in [n for n in nomes if n not in chaves]:
            try:
                chaves[n] = chave_gbif(cli, n, REINO.get(tipo[n], "Plantae"))
            except Exception:
                continue                                  # falha de rede: tenta de novo na próxima rodada
            time.sleep(0.1)
        CHAVES.write_text(json.dumps(chaves, ensure_ascii=False, indent=0, sort_keys=True), encoding="utf-8")

        def um(nome):
            k = chaves.get(nome)
            if not k:
                return nome, None
            for tentativa in range(4):                    # o GBIF limita o ritmo: pausa e nova tentativa com espera
                try:
                    time.sleep(0.4)
                    f = foto_da_chave(cli, k, com_nc)
                    if not f:
                        return nome, None
                    arq = PASTA / (re.sub(r"[^A-Za-z0-9]+", "_", nome).strip("_") + ".webp")
                    if not baixar_webp(cli, f["url"], arq):
                        return nome, None
                    return nome, {"arquivo": arq.name, "autor": f["autor"], "licenca": f["licenca"], "obs": f["obs"], "fonte": "GBIF"}
                except Exception:
                    time.sleep(3 * (tentativa + 1))
            return nome, None

        pendentes = [n for n in nomes if refazer or n not in indice]
        with ThreadPoolExecutor(3) as ex:
            for nome, reg in ex.map(um, pendentes):
                if reg:
                    indice[nome] = reg
                time.sleep(0.05)

    INDICE.write_text(json.dumps(indice, ensure_ascii=False, indent=0, sort_keys=True), encoding="utf-8")
    com_chave = sum(1 for n in nomes if chaves.get(n))
    print(f"{len(nomes)} espécies: {com_chave} com registro no GBIF, {sum(1 for n in nomes if n in indice)} com foto aberta → {INDICE}")


if __name__ == "__main__":
    main(sys.argv[1:])
