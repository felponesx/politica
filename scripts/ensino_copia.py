"""Grava na cópia estática as telas de Ensino que são novas: professores (RAIS) e redes de ensino (Censo Escolar).

Uso: DATABASE_URL=... python -m scripts.ensino_copia [site/dados] [--sem-partes]
Pacote: p/ensino.json (chaves /ensino/professores e /ensino/redes, e /ensino/redes?uf=XX de cada estado).
Sem --sem-partes as chaves também vão para as partes s<N> (leitura de reserva)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ.setdefault("LIMITE_REQ_POR_MINUTO", "0")
os.environ.setdefault("LIMITE_PESADO_POR_MINUTO", "0")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.utils import UFS  # noqa: E402

ARQ = "p/ensino.json"


def _texto(v) -> str:
    return json.dumps(v, ensure_ascii=False, separators=(",", ":"), default=str)


def gravar(pasta: Path, partes: bool = True) -> list[str]:
    cli = TestClient(app)
    man = json.loads((pasta / "manifest.json").read_text(encoding="utf-8"))
    chaves = ["/ensino/professores", "/ensino/redes"] + [f"/ensino/redes?uf={u}" for u in UFS]
    d = {}
    for k in chaves:
        r = cli.get(k)
        if r.status_code == 200:
            d[k] = r.json()
        elif r.status_code != 404:
            raise RuntimeError(f"{k}: HTTP {r.status_code}")
    if not d:
        return []
    (pasta / ARQ).parent.mkdir(exist_ok=True)
    (pasta / ARQ).write_text(_texto(d), encoding="utf-8")
    man.setdefault("pacotes", {})[ARQ] = {"chaves": sorted(d), "telas": ["ensino"]}
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
