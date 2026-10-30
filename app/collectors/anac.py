"""Aeródromos públicos (ANAC): lista cadastral em CSV ';' latin-1.

https://sistemas.anac.gov.br/dadosabertos/Aerodromos/Aer%C3%B3dromos%20P%C3%BAblicos/Lista%20de%20aer%C3%B3dromos%20p%C3%BAblicos/AerodromosPublicos.csv
A 1ª linha é "Atualizado em: AAAA-MM-DD"; o cabeçalho vem na linha seguinte: Código OACI;CIAD;Nome;Município;UF;...;Operação Diurna;Operação Noturna;Situação;..."""
import csv
import io
import re
from collections import Counter

from app import http
from app.collectors.base import registrar_coleta
from app.models import Registro
from app.utils import NOME_PARA_UF, UFS, sem_acento, upsert

URL = ("https://sistemas.anac.gov.br/dadosabertos/Aerodromos/Aer%C3%B3dromos%20P%C3%BAblicos/"
       "Lista%20de%20aer%C3%B3dromos%20p%C3%BAblicos/AerodromosPublicos.csv")
MINIMO = 300   # a lista tem alguns milhares de aeródromos públicos (guarda contra arquivo cortado)


def uf_de(v) -> str | None:
    t = str(v or "").strip()
    return t.upper() if t.upper() in UFS else NOME_PARA_UF.get(sem_acento(t))


def ler(texto: str) -> dict:
    linhas = texto.splitlines()
    atualizado = None
    if linhas and linhas[0].lower().startswith("atualizado"):
        m = re.search(r"\d{4}-\d{2}-\d{2}", linhas[0])
        atualizado = m.group(0) if m else None
        linhas = linhas[1:]
    leitor = csv.reader(io.StringIO("\n".join(linhas)), delimiter=";")
    cab = [sem_acento(c).lower().strip() for c in next(leitor)]
    try:
        i = {"uf": cab.index("uf"), "sit": next(k for k, c in enumerate(cab) if c.startswith("situa")), "dia": next(k for k, c in enumerate(cab) if "diurna" in c),
             "noite": next(k for k, c in enumerate(cab) if "noturna" in c)}
    except (ValueError, StopIteration) as e:
        raise ValueError(f"ANAC: colunas mudaram ({cab[:10]})") from e
    total, por_uf, situacao, noturno = 0, {}, Counter(), 0
    for l in leitor:
        if len(l) <= max(i.values()):
            continue
        uf = uf_de(l[i["uf"]])
        if not uf:
            continue
        total += 1
        u = por_uf.setdefault(uf, {"total": 0, "noturno": 0})
        u["total"] += 1
        sit = l[i["sit"]].strip() or "sem informação"
        situacao[sit] += 1
        if l[i["noite"]].strip() and l[i["noite"]].strip().lower() not in ("não", "nao", "-", "nd"):
            u["noturno"] += 1
            noturno += 1
    return {"atualizado": atualizado, "total": total, "noturno": noturno, "por_uf": dict(sorted(por_uf.items())), "situacao": dict(situacao.most_common())}


def coletar_anac_aerodromos():
    with registrar_coleta("anac", "aerodromos") as (db, n):
        bruto = http.get(URL, headers={"Accept": "*/*"}).content
        try:
            texto = bruto.decode("utf-8")
        except UnicodeDecodeError:
            texto = bruto.decode("latin-1")
        r = ler(texto)
        if r["total"] < MINIMO:
            raise RuntimeError(f"vieram {r['total']} aeródromos (esperado ao menos {MINIMO}); nada foi gravado")
        upsert(db, Registro, {"fonte": "anac", "tipo": "aerodromos", "chave": "BR"}, {"titulo": "Aeródromos públicos", "valor": float(r["total"]), "dados": r})
        db.commit()
        n += 1
    return n.itens
