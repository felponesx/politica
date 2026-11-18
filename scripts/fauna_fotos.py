"""Foto de cada espécie da lista de animais ameaçados (app/dados/fauna_ameacada.json), com licença aberta e crédito.

Uso:
    python -m scripts.fauna_fotos [--com-nc] [--refazer] [--limite N]

--com-nc inclui também CC BY-NC (uso não comercial, com crédito), decidido pelo Felipe.

Fonte: GBIF (https://www.gbif.org), registros de observação com foto. Para cada espécie (nome científico exato, como
no Catálogo do GBIF) pega a primeira foto cuja licença permite publicar com crédito: CC0, CC BY e CC BY-SA. Fotos com
"NC" (uso não comercial) e "ND" ficam de fora. Cada foto vira WebP de até 200 px e grava: autor, licença, link da
observação. Sem foto aberta, a espécie fica sem foto (nunca usamos imagem sem licença nem de outro bicho).

Saída:
    app/dados/fauna_fotos/<nome_com_underline>.webp
    app/dados/fauna_fotos.json   {nome_cientifico: {arquivo, autor, licenca, obs, fonte}}
    app/dados/fauna_fotos_chaves.json   {nome_cientifico: chave do GBIF ou null} (cache)

Nota: o GBIF reúne observações de terceiros (iNaturalist, Wikimedia etc.). A foto é de uma observação, não confirmada
pela equipe; o link leva à observação original.
"""
from __future__ import annotations

import io
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

DADOS = Path(__file__).resolve().parent.parent / "app" / "dados"
ESPECIES = DADOS / "fauna_ameacada.json"
PASTA = DADOS / "fauna_fotos"
INDICE = DADOS / "fauna_fotos.json"
CHAVES = DADOS / "fauna_fotos_chaves.json"
UA = "BRASILMais/1.0 (site de dados abertos; fotos com licenca aberta)"
LADO = 200
ACEITA = re.compile(r"creativecommons\.org/(publicdomain/zero|licenses/(by|by-sa|by-nc))/([\d.]+)")


def rotulo(lic: str, com_nc: bool = False) -> str | None:
    """Nome da licença se for aberta e com crédito (CC0, CC BY, CC BY-SA; CC BY-NC só com com_nc=True); senão None."""
    m = ACEITA.search(lic or "")
    if not m:
        return None
    if m.group(1).startswith("publicdomain"):
        return "CC0"
    if m.group(2) == "by-nc":
        return ("CC BY-NC " + m.group(3)) if com_nc else None
    return ("CC BY-SA " if m.group(2) == "by-sa" else "CC BY ") + m.group(3)


def chave_gbif(cli, nome: str) -> int | None:
    r = cli.get("https://api.gbif.org/v1/species/match", params={"name": nome, "kingdom": "Animalia"}).json()
    if r.get("matchType") != "EXACT" or not r.get("usageKey"):
        return None
    return int(r["usageKey"])


def foto_da_chave(cli, chave: int, com_nc: bool = False) -> dict | None:
    # o GBIF filtra a licença na própria busca; sem o filtro, as primeiras fotos são quase todas CC BY-NC
    licencas = ["CC0_1_0", "CC_BY_4_0"] + (["CC_BY_NC_4_0"] if com_nc else [])
    d = cli.get("https://api.gbif.org/v1/occurrence/search",
                params=[("taxonKey", chave), ("mediaType", "StillImage")] + [("license", x) for x in licencas] + [("limit", 30)]).json()
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
            return {"url": url, "licenca": lic, "autor": autor or "autor não informado", "obs": obs}
    return None


def baixar_webp(cli, url: str, destino: Path) -> bool:
    from PIL import Image
    r = cli.get(url, timeout=60)
    if r.status_code != 200 or len(r.content) > 6_000_000:
        return False
    im = Image.open(io.BytesIO(r.content)).convert("RGB")
    im.thumbnail((LADO, LADO))
    destino.parent.mkdir(parents=True, exist_ok=True)
    im.save(destino, "WEBP", quality=72, method=6)
    return True


def main(argv: list[str]) -> None:
    import httpx
    refazer = "--refazer" in argv
    com_nc = "--com-nc" in argv
    limite = int(argv[argv.index("--limite") + 1]) if "--limite" in argv else None
    especies = json.loads(ESPECIES.read_text(encoding="utf-8"))["especies"]
    nomes = [e[0] for e in especies][:limite]
    chaves = json.loads(CHAVES.read_text(encoding="utf-8")) if CHAVES.exists() else {}
    indice = json.loads(INDICE.read_text(encoding="utf-8")) if INDICE.exists() else {}

    with httpx.Client(timeout=30, headers={"User-Agent": UA}, follow_redirects=True) as cli:
        falta_chave = [n for n in nomes if n not in chaves]
        for n in falta_chave:
            try:
                chaves[n] = chave_gbif(cli, n)
            except Exception:
                continue                       # falha de rede: tenta de novo na próxima rodada
            time.sleep(0.1)
        CHAVES.write_text(json.dumps(chaves, ensure_ascii=False, indent=0, sort_keys=True), encoding="utf-8")

        def um(nome):
            k = chaves.get(nome)
            if not k:
                return nome, None
            # o GBIF limita o ritmo: pausa entre pedidos e nova tentativa com espera (sem isso, falhas viram "sem foto")
            for tentativa in range(4):
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
