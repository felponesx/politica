"""Focos de queimadas (INPE, Programa Queimadas): focos detectados por estado, bioma e ano.

Arquivos anuais do satélite de referência: https://dataserver-coids.inpe.br/queimadas/queimadas/focos/csv/anual/Brasil_sat_ref/focos_br_ref_AAAA.zip (~6 MB, CSV ',' dentro de `tmp/`).
Um foco é um ponto com calor detectado por satélite em um dia: não mede área queimada nem diz se o fogo é criminoso. Lê as colunas por nome (estado, bioma, data)."""
import csv
import io
import re
import zipfile
from datetime import date

from app import http
from app.collectors.ambiente import uf_de
from app.collectors.base import registrar_coleta
from app.models import Registro
from app.utils import sem_acento, upsert

BASE = "https://dataserver-coids.inpe.br/queimadas/queimadas/focos/csv/anual/Brasil_sat_ref/focos_br_ref_{ano}.zip"
ANOS = 8
MINIMO_POR_ANO = 20_000   # o Brasil tem centenas de milhares de focos por ano (guarda contra arquivo cortado)


def agregar(texto: str, ano: int) -> dict:
    leitor = csv.reader(io.StringIO(texto))
    cab = [sem_acento(c).lower().strip() for c in next(leitor)]
    try:
        i_uf = next(k for k, c in enumerate(cab) if c in ("estado", "uf"))
    except StopIteration as e:
        raise ValueError(f"INPE focos: coluna de estado não encontrada ({cab[:10]})") from e
    i_bio = next((k for k, c in enumerate(cab) if c == "bioma"), None)
    por_uf: dict[str, int] = {}
    por_bioma: dict[str, int] = {}
    mensal: dict[str, int] = {}
    i_data = next((k for k, c in enumerate(cab) if c.startswith("data")), None)
    total = 0
    for l in leitor:
        if len(l) <= i_uf:
            continue
        total += 1
        uf = uf_de(l[i_uf])
        if uf:
            por_uf[uf] = por_uf.get(uf, 0) + 1
        if i_bio is not None and len(l) > i_bio and l[i_bio].strip():
            b = l[i_bio].strip()
            por_bioma[b] = por_bioma.get(b, 0) + 1
        if i_data is not None and len(l) > i_data:
            m = re.match(r"(\d{4}-\d{2})", l[i_data].strip())
            if m:
                mensal[m.group(1)] = mensal.get(m.group(1), 0) + 1
    return {"ano": ano, "total": total, "por_uf": por_uf, "por_bioma": por_bioma, "mensal": dict(sorted(mensal.items()))}


def baixar_ano(ano: int) -> dict | None:
    try:
        r = http.get(BASE.format(ano=ano), headers={"Accept": "*/*"})
    except Exception:  # noqa: BLE001 - ano ainda não publicado
        return None
    z = zipfile.ZipFile(io.BytesIO(r.content))
    nome = next(n for n in z.namelist() if n.lower().endswith(".csv"))
    bruto = z.read(nome)
    try:
        texto = bruto.decode("utf-8-sig")
    except UnicodeDecodeError:
        texto = bruto.decode("latin-1")
    return agregar(texto, ano)


def coletar_queimadas():
    with registrar_coleta("inpe", "queimadas") as (db, n):
        hoje = date.today().year
        anos = {}
        for ano in range(hoje, hoje - ANOS - 1, -1):
            r = baixar_ano(ano)
            if not r:
                continue
            if r["total"] < MINIMO_POR_ANO:
                n.avisos.append(f"{ano}: só {r['total']} focos (esperado ≥ {MINIMO_POR_ANO}); ignorado")
                continue
            anos[str(ano)] = r
        if not anos:
            raise RuntimeError("INPE focos: nenhum ano válido; nada foi gravado")
        por_uf = {}
        por_bioma = {}
        for a, r in anos.items():
            for uf, v in r["por_uf"].items():
                por_uf.setdefault(uf, {})[a] = v
            for b, v in r["por_bioma"].items():
                por_bioma.setdefault(b, {})[a] = v
        ult = max(anos)
        upsert(db, Registro, {"fonte": "inpe", "tipo": "focos_queimadas", "chave": "BR"},
               {"titulo": "Focos de queimadas", "valor": float(anos[ult]["total"]),
                "dados": {"ultimo_ano": ult, "total": {a: r["total"] for a, r in sorted(anos.items())}, "por_uf": por_uf, "por_bioma": por_bioma, "mensal": anos[ult]["mensal"]}})
        db.commit()
        n += len(anos)
    return n.itens
