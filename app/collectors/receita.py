"""Arrecadação federal por UF — Receita Federal (dataset "Resultado da Arrecadação").
Página: https://www.gov.br/receitafederal/pt-br/acesso-a-informacao/dados-abertos/receitadata/arrecadacao

O CSV vem "largo": colunas Ano, Mês, UF e uma coluna por tributo. O parser abaixo
detecta essas colunas pelo nome, soma todos os tributos e guarda o detalhamento.
"""
import csv
import io
import os
import tempfile

from app import http
from app.collectors.base import registrar_coleta
from app.config import settings
from app.models import Registro
from app.utils import para_float, para_mes, para_uf, sem_acento, upsert


def _ler_texto(caminho: str) -> str:
    bruto = open(caminho, "rb").read()
    for enc in ("utf-8-sig", "latin-1"):
        try:
            return bruto.decode(enc)
        except UnicodeDecodeError:
            continue
    return bruto.decode("latin-1", errors="replace")


def _colunas(cabecalho: list[str]):
    norm = {c: sem_acento(c) for c in cabecalho}
    ano = next((c for c, n in norm.items() if n == "ANO"), None)
    mes = next((c for c, n in norm.items() if n in ("MES", "MES DE REFERENCIA")), None)
    uf = next((c for c, n in norm.items() if n in ("UF", "ESTADO", "SIGLA UF")), None)
    if not (ano and mes and uf):
        raise ValueError(f"Não achei as colunas Ano/Mês/UF no CSV. Cabeçalho: {cabecalho[:8]}")
    return ano, mes, uf


def interpretar_csv(texto: str):
    """Gera (uf, ano, mes, total, {tributo: valor}) para cada linha válida."""
    delim = ";" if texto[:2000].count(";") >= texto[:2000].count(",") else ","
    leitor = csv.DictReader(io.StringIO(texto), delimiter=delim)
    c_ano, c_mes, c_uf = _colunas(leitor.fieldnames or [])
    for linha in leitor:
        uf, mes = para_uf(linha.get(c_uf)), para_mes(linha.get(c_mes))
        try:
            ano = int(str(linha.get(c_ano)).strip())
        except ValueError:
            continue
        if not uf or not mes:
            continue
        tributos = {}
        for col, val in linha.items():
            if col in (c_ano, c_mes, c_uf) or col is None:
                continue
            v = para_float(val)
            if v is not None:
                tributos[col.strip()] = v
        yield uf, ano, mes, round(sum(tributos.values()), 2), tributos


def coletar_arrecadacao_estados(ano_minimo: int | None = None, arquivo_local: str | None = None,
                                url: str | None = None):
    with registrar_coleta("receita", "arrecadacao_estados", ano_minimo=ano_minimo or "todos") as (db, n):
        caminho = arquivo_local or http.baixar(url or settings.receita_arrecadacao_url,
                                               os.path.join(tempfile.gettempdir(), "arrecadacao-estado.csv"))
        for uf, ano, mes, total, tributos in interpretar_csv(_ler_texto(caminho)):
            if ano_minimo and ano < ano_minimo:
                continue
            upsert(db, Registro, {"fonte": "receita", "tipo": "arrecadacao_uf", "chave": f"{uf}-{ano}-{mes:02d}"}, {
                "uf": uf, "ano": ano, "titulo": f"Arrecadação federal {uf} {mes:02d}/{ano}",
                "valor": total, "dados": {"mes": mes, "tributos": tributos},
            })
            n += 1
            if n.itens % 500 == 0:
                db.commit()
    return n.itens
