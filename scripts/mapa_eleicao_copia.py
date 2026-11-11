"""Acrescenta à cópia estática o mapa por município (/eleicoes/<ano>/<UF>/mapa?...) de uma eleição antiga.

Uso: DATABASE_URL=... python -m scripts.mapa_eleicao_copia <ano> [site/dados] [ano_modelo]
O banco precisa ter `tse-resultados ano=<ano>`. As chaves seguem as do ano modelo (2018) que já estão na cópia. O código IBGE vem
dos mapas de 2018/2022 da própria cópia pelo código TSE do município (que não muda; 2014 escreve com zero à esquerda).
Depois rode `python -m scripts.pacotes_copia site/dados` para montar os pacotes el-<ano>-*.
"""
from __future__ import annotations

import glob
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("LIMITE_REQ_POR_MINUTO", "0")
os.environ.setdefault("LIMITE_PESADO_POR_MINUTO", "0")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from scripts.copia_saude_tribunais import Copia  # noqa: E402


def _cod(x) -> str:
    return str(x or "").lstrip("0")


def juntar(ano: int, pasta: Path, modelo: int = 2018) -> dict:
    c = Copia(pasta)
    chaves = sorted({k.replace(f"/{modelo}/", f"/{ano}/") for f in glob.glob(str(pasta / "s*.json"))
                     for k in json.loads(Path(f).read_text(encoding="utf-8")) if k.startswith(f"/eleicoes/{modelo}/") and "/mapa?" in k})
    ibge: dict = {}
    for k in chaves:
        for a in (modelo, 2022):
            x = c.ler(k.replace(f"/{ano}/", f"/{a}/"))
            for m in x if isinstance(x, list) else []:
                if m.get("codigo_ibge"):
                    ibge.setdefault(_cod(m.get("cd_municipio")), m["codigo_ibge"])
    cli = TestClient(app)
    res = {"gravadas": 0, "sem_dados": 0, "sem_ibge": 0}
    for k in chaves:
        r = cli.get(k)
        v = r.json() if r.status_code == 200 else None
        if not isinstance(v, list) or not v:
            res["sem_dados"] += 1
            continue
        for m in v:
            m["codigo_ibge"] = m.get("codigo_ibge") or ibge.get(_cod(m.get("cd_municipio")))
            res["sem_ibge"] += not m["codigo_ibge"]
        c.gravar(k, v)
        res["gravadas"] += 1
    c.salvar()
    return res


if __name__ == "__main__":
    a = sys.argv[1:]
    print(juntar(int(a[0]), Path(a[1] if len(a) > 1 else "site/dados"), int(a[2]) if len(a) > 2 else 2018))
