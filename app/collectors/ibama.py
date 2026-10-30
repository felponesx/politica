"""Multas ambientais do IBAMA (autos de infração): totais por estado e ano.

Dados abertos: https://dadosabertos.ibama.gov.br/pt_BR/dataset/fiscalizacao-auto-de-infracao — o zip `auto_infracao_csv.zip` (Azure Blob público) traz um CSV por ano
(`auto_infracao_AAAA.csv`, ';' , UTF-8) com SEQ_AUTO_INFRACAO;...;SIT_CANCELADO (S/N);...;TIPO_MULTA;VAL_AUTO_INFRACAO (vírgula);...;DAT_HORA_AUTO_INFRACAO;...;UF;...;TIPO_INFRACAO;...;TP_PESSOA_INFRATOR;NUM_PESSOA_INFRATOR;NOME_INFRATOR.
Só entram totais (quantidade e valor aplicado, sem os autos cancelados): nomes e CPF/CNPJ dos autuados NÃO são guardados."""
import csv
import re
import sys
from datetime import date

from app.collectors.base import registrar_coleta
from app.collectors.bcb_scr import entradas_zip, linhas_entrada
from app.models import Registro
from app.utils import UFS, upsert

csv.field_size_limit(sys.maxsize)   # há campos de texto longos no CSV do IBAMA (o limite padrão do csv é 131072)
URL = "https://stibamadadosabertosprd.blob.core.windows.net/dados-abertos/dados/SIFISC/auto_infracao/auto_infracao/auto_infracao_csv.zip"
ANOS = 10   # últimos anos lidos
MINIMO_AUTOS = 20_000


def _valor(v) -> float:
    try:
        return float(str(v).strip().replace(".", "").replace(",", ".")) if str(v).strip() else 0.0
    except ValueError:
        return 0.0


def agregar(linhas, ate_ano: int | None = None) -> dict:
    """{"por_uf_ano": {uf: {ano: {"autos", "valor"}}}, "por_tipo": {tipo: {ano: valor}}, "lidos", "cancelados"}."""
    leitor = csv.reader(linhas, delimiter=";")
    cab = [c.strip().upper().lstrip("﻿") for c in next(leitor)]
    try:
        i = {k: cab.index(k) for k in ("SIT_CANCELADO", "VAL_AUTO_INFRACAO", "DAT_HORA_AUTO_INFRACAO", "UF", "TIPO_INFRACAO")}
    except ValueError as e:
        raise ValueError(f"IBAMA: colunas mudaram ({cab[:8]}): {e}") from e
    por_uf: dict = {}
    por_tipo: dict = {}
    lidos = cancelados = 0
    for l in leitor:
        if len(l) <= max(i.values()):
            continue
        lidos += 1
        if l[i["SIT_CANCELADO"]].strip().upper() == "S":
            cancelados += 1
            continue
        uf = l[i["UF"]].strip().upper()
        m = re.match(r"(\d{4})-", l[i["DAT_HORA_AUTO_INFRACAO"]].strip())
        if uf not in UFS or not m:
            continue
        ano = m.group(1)
        if ate_ano and int(ano) > ate_ano:
            continue
        v = _valor(l[i["VAL_AUTO_INFRACAO"]])
        e = por_uf.setdefault(uf, {}).setdefault(ano, {"autos": 0, "valor": 0.0})
        e["autos"] += 1
        e["valor"] += v
        t = l[i["TIPO_INFRACAO"]].strip() or "Outros"
        por_tipo.setdefault(t, {}).setdefault(ano, 0.0)
        por_tipo[t][ano] += v
    return {"por_uf_ano": por_uf, "por_tipo": por_tipo, "lidos": lidos, "cancelados": cancelados}


def juntar(parciais: list[dict]) -> dict:
    por_uf: dict = {}
    por_tipo: dict = {}
    lidos = cancelados = 0
    for p in parciais:
        lidos += p["lidos"]
        cancelados += p["cancelados"]
        for uf, anos in p["por_uf_ano"].items():
            for a, e in anos.items():
                x = por_uf.setdefault(uf, {}).setdefault(a, {"autos": 0, "valor": 0.0})
                x["autos"] += e["autos"]
                x["valor"] += e["valor"]
        for t, anos in p["por_tipo"].items():
            for a, v in anos.items():
                por_tipo.setdefault(t, {}).setdefault(a, 0.0)
                por_tipo[t][a] += v
    arred = lambda d: {k: {a: {"autos": e["autos"], "valor": round(e["valor"], 2)} for a, e in sorted(v.items())} for k, v in sorted(d.items())}
    return {"por_uf_ano": arred(por_uf), "por_tipo": {t: {a: round(v, 2) for a, v in sorted(m.items())} for t, m in por_tipo.items()}, "lidos": lidos, "cancelados": cancelados}


def coletar_ibama_multas():
    with registrar_coleta("ibama", "multas") as (db, n):
        _, entradas = entradas_zip(URL)
        arquivos = sorted((int(m.group(1)), e) for e in entradas if (m := re.fullmatch(r"(?:.*/)?auto_infracao_(\d{4})\.csv", e[0])))
        if not arquivos:
            raise RuntimeError("IBAMA: o zip não tem auto_infracao_AAAA.csv")
        hoje = date.today().year
        parciais = []
        for ano, (_, comp, metodo, off) in arquivos:
            if ano < hoje - ANOS:
                continue
            parciais.append(agregar(linhas_entrada(URL, comp, metodo, off), ate_ano=hoje))
        r = juntar(parciais)
        if r["lidos"] < MINIMO_AUTOS:
            raise RuntimeError(f"IBAMA: só {r['lidos']} autos lidos (esperado ao menos {MINIMO_AUTOS}); nada foi gravado")
        upsert(db, Registro, {"fonte": "ibama", "tipo": "multas_ambientais", "chave": "BR"}, {"titulo": "Multas ambientais do IBAMA", "valor": float(r["lidos"]), "dados": {**r, "anos_lidos": [a for a, _ in arquivos if a >= hoje - ANOS]}})
        db.commit()
        n += 1
    return n.itens
