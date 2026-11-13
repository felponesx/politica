"""Grava na cópia estática a aba Catástrofes e acidentes num pacote só dela: p/catastrofes.json.

Uso: DATABASE_URL=... python -m scripts.catastrofes_copia [site/dados] [--sem-partes]
Chaves: /catastrofes (tragédias), /catastrofes/rodovias, /catastrofes/rodovias?ano=AAAA, /catastrofes/transferencias e ?ano=AAAA.
As notícias de catástrofes já vêm no noticias.json do robô rápido (tema "catastrofe")."""
from __future__ import annotations

import base64
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("LIMITE_REQ_POR_MINUTO", "0")
os.environ.setdefault("LIMITE_PESADO_POR_MINUTO", "0")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

ARQ = "p/catastrofes.json"


def _texto(v) -> str:
    return json.dumps(v, ensure_ascii=False, separators=(",", ":"), default=str)


def gravar(pasta: Path, partes: bool = True) -> list[str]:
    cli = TestClient(app)
    man = json.loads((pasta / "manifest.json").read_text(encoding="utf-8"))
    chaves = ["/catastrofes", "/catastrofes/rodovias"]
    r = cli.get("/catastrofes/rodovias")
    if r.status_code == 200:
        chaves += [f"/catastrofes/rodovias?ano={a}" for a in r.json().get("anos", [])]
    t = cli.get("/catastrofes/transferencias")
    if t.status_code == 200:
        chaves += ["/catastrofes/transferencias"] + [f"/catastrofes/transferencias?ano={a}" for a in t.json().get("anos", [])]
    d = {}
    for k in chaves:
        resp = cli.get(k)
        if resp.status_code == 200:
            d[k] = resp.json()
        elif resp.status_code != 404:
            raise RuntimeError(f"{k}: HTTP {resp.status_code}")
    # fotos embutidas no pacote (data URI): não criam arquivo novo na cópia (o Artifact tem limite de arquivos)
    for k, v in d.items():
        for x in (v.get("itens") or []) if isinstance(v, dict) else []:
            img = x.get("imagem")
            if img:
                arq = pasta.parent / img
                if arq.exists():
                    x["imagem"] = "data:image/webp;base64," + base64.b64encode(arq.read_bytes()).decode("ascii")
    (pasta / ARQ).parent.mkdir(exist_ok=True)
    (pasta / ARQ).write_text(_texto(d), encoding="utf-8")
    man.setdefault("pacotes", {})[ARQ] = {"chaves": sorted(d), "telas": ["catastrofes"]}
    (pasta / "manifest.json").write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{ARQ}: {len(d)} chaves, {(pasta / ARQ).stat().st_size // 1024} KB")
    mudou = ["manifest.json", ARQ]
    if partes:
        from scripts.copia_saude_tribunais import Copia
        c = Copia(pasta)
        c.manifest = man
        for k, v in d.items():
            c.gravar(k, v)
        mudou += c.salvar()
    return sorted(set(mudou))


if __name__ == "__main__":
    a = [x for x in sys.argv[1:] if not x.startswith("--")]
    for arq in gravar(Path(a[0] if a else "site/dados"), "--sem-partes" not in sys.argv):
        print(arq)
