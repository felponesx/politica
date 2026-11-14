"""Censo Escolar (INEP): escolas, matrículas e professores por estado e por rede (estadual, federal, municipal, privada).

Arquivo público do ano: microdados_censo_escolar_AAAA.zip, com o CSV `microdados_ed_basica_AAAA.csv` (uma linha por escola).
Só escolas em atividade (TP_SITUACAO_FUNCIONAMENTO = 1). Guardamos somas por estado e rede:
- matrículas: total da educação básica e por etapa (infantil, fundamental, médio);
- professores por etapa: NÃO somam entre etapas (quem dá aula em duas etapas conta nas duas), por isso não há total de professores.

O arquivo NÃO traz disciplinas (matérias dadas): não há matéria por rede nesta base.
O certificado do INEP vem sem a cadeia intermediária: usa o cliente do coletor do IDEB (`inep.cliente`), com a verificação ligada.
"""
import csv
import hashlib
import io
import logging
import tempfile
import zipfile
from pathlib import Path

from app.collectors import inep
from app.collectors.base import registrar_coleta
from app.models import Registro
from app.utils import UF_POR_CODIGO_IBGE, upsert

log = logging.getLogger("brasilplus.censo_escolar")
URL = "https://download.inep.gov.br/dados_abertos/microdados_censo_escolar_{ano}.zip"
ARQUIVO = "microdados_ed_basica_{ano}.csv"
REDES = {"1": "federal", "2": "estadual", "3": "municipal", "4": "privada"}
COLUNAS = ("CO_UF", "TP_DEPENDENCIA", "TP_SITUACAO_FUNCIONAMENTO", "QT_MAT_BAS", "QT_MAT_INF", "QT_MAT_FUND", "QT_MAT_MED",
           "QT_DOC_BAS", "QT_DOC_INF", "QT_DOC_FUND", "QT_DOC_MED")


def _n(v: str) -> int:
    try:
        return int(float((v or "0").replace(",", ".")))
    except ValueError:
        return 0


def agregar(linhas, cab: list[str]) -> dict:
    """{(uf, rede): {escolas, mat_total, mat_infantil, mat_fundamental, mat_medio, doc_infantil, doc_fundamental, doc_medio}}.
    uf 'BR' é a soma do país. Escolas que não estão em atividade ficam de fora."""
    faltam = [c for c in COLUNAS if c not in cab]
    if faltam:
        raise ValueError(f"Censo Escolar mudou: faltam colunas {faltam}")
    i = {c: cab.index(c) for c in COLUNAS}
    maximo = max(i.values())
    out: dict[tuple, dict] = {}

    def soma(chave):
        return out.setdefault(chave, {"escolas": 0, "mat_total": 0, "mat_infantil": 0, "mat_fundamental": 0, "mat_medio": 0,
                                      "doc_infantil": 0, "doc_fundamental": 0, "doc_medio": 0})
    for l in linhas:
        if len(l) <= maximo or l[i["TP_SITUACAO_FUNCIONAMENTO"]].strip() != "1":
            continue
        try:
            uf = UF_POR_CODIGO_IBGE.get(int(l[i["CO_UF"]]))
        except ValueError:
            uf = None
        rede = REDES.get(l[i["TP_DEPENDENCIA"]].strip())
        if not uf or not rede:
            continue
        valores = {"mat_total": _n(l[i["QT_MAT_BAS"]]), "mat_infantil": _n(l[i["QT_MAT_INF"]]),
                   "mat_fundamental": _n(l[i["QT_MAT_FUND"]]), "mat_medio": _n(l[i["QT_MAT_MED"]]),
                   "doc_infantil": _n(l[i["QT_DOC_INF"]]), "doc_fundamental": _n(l[i["QT_DOC_FUND"]]), "doc_medio": _n(l[i["QT_DOC_MED"]])}
        for chave in ((uf, rede), ("BR", rede)):
            t = soma(chave)
            t["escolas"] += 1
            for k, v in valores.items():
                t[k] += v
    return {f"{u}|{r}": v for (u, r), v in out.items()}


def coletar_censo_escolar(ano: int = 2024):
    """Baixa o zip do Censo Escolar do `ano` e grava as somas por estado e rede (um registro por estado × rede)."""
    with registrar_coleta("inep", "censo-escolar", ano=str(ano)) as (db, n):
        destino = Path(tempfile.mkdtemp(prefix="censo-")) / f"{ano}.zip"
        cli = inep.cliente()
        with cli.stream("GET", URL.format(ano=ano), timeout=600) as r:
            r.raise_for_status()
            with open(destino, "wb") as f:
                for bloco in r.iter_bytes(1 << 20):
                    f.write(bloco)
        if not zipfile.is_zipfile(destino):
            raise RuntimeError("o INEP não devolveu um zip")
        sha = hashlib.sha256(destino.read_bytes()).hexdigest()
        with zipfile.ZipFile(destino) as z:
            if z.testzip() is not None:
                raise RuntimeError("zip corrompido")
            nome = next(x for x in z.namelist() if x.endswith(ARQUIVO.format(ano=ano)))
            leitor = csv.reader(io.TextIOWrapper(z.open(nome), encoding="latin-1", newline=""), delimiter=";")
            ag = agregar(leitor, [c.strip() for c in next(leitor)])
        destino.unlink(missing_ok=True)
        if ag.get("BR|privada", {}).get("escolas", 0) < 10000 or ag.get("BR|estadual", {}).get("escolas", 0) < 10000:
            raise RuntimeError("poucas escolas no arquivo (leitura incompleta?); nada foi gravado")
        for chave, v in ag.items():
            uf, rede = chave.split("|")
            upsert(db, Registro, {"fonte": "inep", "tipo": "censo_escolar_rede", "chave": f"{ano}|{uf}|{rede}"},
                   {"ano": ano, "uf": None if uf == "BR" else uf, "titulo": f"Censo Escolar {ano}: escolas {rede} em {uf}",
                    "valor": float(v["escolas"]),
                    "dados": {**v, "uf": uf, "rede": rede, "ano": ano, "sha256": sha, "fonte_url": URL.format(ano=ano),
                              "fonte": "INEP — Censo Escolar (microdados da educação básica), escolas em atividade"}})
            n += 1
        db.commit()
    return n.itens
