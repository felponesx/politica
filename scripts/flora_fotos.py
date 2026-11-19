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
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from scripts.fauna_fotos import ACEITA, LADO, UA, rotulo

LIMITE_BYTES = 6_000_000     # foto maior que isso não é baixada inteira: a busca passa para a próxima


def candidatas(cli, chave: int, com_nc: bool = False) -> list[dict]:
    """Fotos com licença aberta da espécie (GBIF), na ordem do GBIF."""
    licencas = ["CC0_1_0", "CC_BY_4_0"] + (["CC_BY_NC_4_0"] if com_nc else [])
    d = cli.get("https://api.gbif.org/v1/occurrence/search",
                params=[("taxonKey", chave), ("mediaType", "StillImage")] + [("license", x) for x in licencas] + [("limit", 30)]).json()
    out = []
    for r in d.get("results", []):
        for m in r.get("media", []):
            if m.get("type") != "StillImage":
                continue
            url = m.get("identifier") or ""
            lic = rotulo(m.get("license", ""), com_nc)
            if not lic or not url.lower().split("?")[0].endswith((".jpg", ".jpeg", ".png")):
                continue
            autor = (m.get("creator") or m.get("rightsHolder") or "").strip()
            obs = r.get("references") or f"https://www.gbif.org/occurrence/{r.get('key')}"
            out.append({"url": url, "licenca": lic, "autor": autor or "autor não informado", "obs": obs})
    return out


def baixar_webp(cli, url: str, destino: Path) -> bool:
    """Baixa a foto em pedaços e desiste se passar de LIMITE_BYTES (sem baixar a imagem inteira)."""
    import io
    from PIL import Image
    dados = bytearray()
    with cli.stream("GET", url, timeout=30) as r:
        if r.status_code != 200:
            return False
        for pedaco in r.iter_bytes():
            dados.extend(pedaco)
            if len(dados) > LIMITE_BYTES:
                return False
    im = Image.open(io.BytesIO(bytes(dados))).convert("RGB")
    im.thumbnail((LADO, LADO))
    destino.parent.mkdir(parents=True, exist_ok=True)
    im.save(destino, "WEBP", quality=72, method=6)
    return True

DADOS = Path(__file__).resolve().parent.parent / "app" / "dados"
ESPECIES = DADOS / "flora_ameacada.json"
PASTA = DADOS / "flora_fotos"
INDICE = DADOS / "flora_fotos.json"
CHAVES = DADOS / "flora_fotos_chaves.json"
TENTADAS = DADOS / "flora_fotos_tentadas.json"   # espécies já consultadas no GBIF (com ou sem foto): não são pedidas de novo
REINO = {"Plantas": "Plantae", "Fungos": "Fungi"}
ERROS: list[str] = []


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
    tentadas = set(json.loads(TENTADAS.read_text(encoding="utf-8"))) if TENTADAS.exists() else set()

    with httpx.Client(timeout=30, headers={"User-Agent": UA}, follow_redirects=True) as cli:
        for n in [n for n in nomes if n not in chaves]:
            try:
                chaves[n] = chave_gbif(cli, n, REINO.get(tipo[n], "Plantae"))
            except Exception:
                continue                                  # falha de rede: tenta de novo na próxima rodada
            time.sleep(0.1)
        CHAVES.write_text(json.dumps(chaves, ensure_ascii=False, indent=0, sort_keys=True), encoding="utf-8")

        def um(nome):
            """(nome, registro ou None, consultada). Só marca como consultada quando a GBIF respondeu; falha de rede ou limite de pedidos é tentada de novo."""
            k = chaves.get(nome)
            if not k:
                return nome, None, True                  # sem registro no GBIF: consultado
            for tentativa in range(6):                   # a GBIF limita o ritmo (429): pausa crescente e nova tentativa
                try:
                    time.sleep(1.0)                  # ~1 pedido por segundo: abaixo do limite da GBIF
                    arq = PASTA / (re.sub(r"[^A-Za-z0-9]+", "_", nome).strip("_") + ".webp")
                    for f in candidatas(cli, k, com_nc)[:8]:
                        try:
                            if baixar_webp(cli, f["url"], arq):
                                return nome, {"arquivo": arq.name, "autor": f["autor"], "licenca": f["licenca"], "obs": f["obs"], "fonte": "GBIF"}, True
                        except Exception:
                            continue                     # essa foto falhou: tenta a próxima da espécie
                    return nome, None, True
                except Exception as e:
                    ERROS.append(f"{nome}: {type(e).__name__}")
                    time.sleep(4 * (tentativa + 1))
            return nome, None, False                     # não respondeu: fica para a próxima rodada

        pendentes = [n for n in nomes if refazer or (n not in indice and n not in tentadas)]
        feitos = 0
        with ThreadPoolExecutor(1) as ex:                    # uma conexão só: com mais, a GBIF responde 429
            for nome, reg, consultada in ex.map(um, pendentes):
                feitos += 1
                if reg:
                    indice[nome] = reg
                if consultada:
                    tentadas.add(nome)
                if feitos % 25 == 0:                       # grava aos poucos: uma interrupção não perde o que já foi baixado
                    INDICE.write_text(json.dumps(indice, ensure_ascii=False, indent=0, sort_keys=True), encoding="utf-8")
                    TENTADAS.write_text(json.dumps(sorted(tentadas), ensure_ascii=False), encoding="utf-8")
                    print(f"{feitos}/{len(pendentes)} processadas, {len(indice)} com foto, {len(ERROS)} limites/falhas", flush=True)

    INDICE.write_text(json.dumps(indice, ensure_ascii=False, indent=0, sort_keys=True), encoding="utf-8")
    TENTADAS.write_text(json.dumps(sorted(tentadas), ensure_ascii=False), encoding="utf-8")
    if ERROS:
        print(f"{len(ERROS)} falhas de rede (tentadas de novo); exemplos: {ERROS[:3]}", flush=True)
    com_chave = sum(1 for n in nomes if chaves.get(n))
    print(f"{len(nomes)} espécies: {com_chave} com registro no GBIF, {sum(1 for n in nomes if n in indice)} com foto aberta → {INDICE}")


if __name__ == "__main__":
    main(sys.argv[1:])
