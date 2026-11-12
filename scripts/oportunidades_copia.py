"""Grava na cópia estática as respostas de Concursos e cursos e de Eventos, em três pacotes só dessas telas.

Uso: DATABASE_URL=... python -m scripts.oportunidades_copia [site/dados] [--sem-partes]
Pacotes: p/concursos.json (/concursos, /cursos), p/eventos.json (/eventos, /eventos-patrocinios) e p/eventos-uf.json (as mesmas por estado).
Sem --sem-partes as chaves também vão para as partes s<N> (leitura de reserva, como as demais). No Artifact (limite de 511 arquivos)
publique só os pacotes e o manifest (--sem-partes)."""
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

PACOTES = {
    "p/concursos.json": (["/concursos", "/cursos"], ["concursos"]),
    "p/eventos.json": (["/eventos", "/eventos-patrocinios"], ["eventos"]),
    # patrocínio por estado: a tela filtra a lista do país (cada projeto traz UF e locais)
    "p/eventos-uf.json": ([f"/eventos?uf={u}" for u in UFS], ["eventos"]),
}


def _texto(v) -> str:
    return json.dumps(v, ensure_ascii=False, separators=(",", ":"), default=str)


def gravar(pasta: Path, partes: bool = True) -> list[str]:
    cli = TestClient(app)
    man = json.loads((pasta / "manifest.json").read_text(encoding="utf-8"))
    mudou = ["manifest.json"]
    valores = {}
    for arq, (chaves, telas) in PACOTES.items():
        d = {}
        for k in chaves:
            r = cli.get(k)
            if r.status_code == 200:
                d[k] = r.json()
            elif r.status_code != 404:
                raise RuntimeError(f"{k}: HTTP {r.status_code}")
        if not d:
            continue
        (pasta / arq).parent.mkdir(exist_ok=True)
        (pasta / arq).write_text(_texto(d), encoding="utf-8")
        man.setdefault("pacotes", {})[arq] = {"chaves": sorted(d), "telas": telas}
        valores.update(d)
        mudou.append(arq)
        print(f"{arq}: {len(d)} chaves, {(pasta / arq).stat().st_size // 1024} KB")
    (pasta / "manifest.json").write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")
    if partes:
        from scripts.copia_saude_tribunais import Copia
        c = Copia(pasta)
        c.manifest = man
        for k, v in valores.items():
            c.gravar(k, v)
        mudou += c.salvar()
    return sorted(set(mudou))


if __name__ == "__main__":
    a = [x for x in sys.argv[1:] if not x.startswith("--")]
    for arq in gravar(Path(a[0] if a else "site/dados"), "--sem-partes" not in sys.argv):
        print(arq)
