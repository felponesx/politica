"""Capacidade de Pagamento (CAPAG) dos municípios — Tesouro Nacional.
Dataset: https://www.tesourotransparente.gov.br/ckan/dataset/capag-municipios

Sem `arquivo_local`/`url`, a coleta pergunta à API do CKAN qual é o arquivo mais recente do dataset.
Requer `ibge-municipios` antes (atualiza a tabela de municípios).
"""
from sqlalchemy import select

from app import http
from app.collectors.arquivos import achar_coluna, baixar_temp, ler_tabela
from app.collectors.base import registrar_coleta
from app.config import settings
from app.models import Municipio
from app.utils import sem_acento


def _arquivo_mais_recente() -> str:
    resp = http.get_json(settings.capag_ckan_url) or {}
    recursos = (resp.get("result") or {}).get("resources") or []
    bons = [r for r in recursos if str(r.get("format", "")).upper() in ("CSV", "XLSX") and r.get("url")]
    if not bons:
        raise RuntimeError("Não achei CSV/XLSX no dataset CAPAG. Baixe manualmente e use arquivo_local=...")
    bons.sort(key=lambda r: (r.get("last_modified") or r.get("created") or "", r.get("format") == "CSV"))
    return bons[-1]["url"]


def coletar_capag(arquivo_local: str | None = None, url: str | None = None, ano: int | None = None):
    with registrar_coleta("tesouro", "capag_municipios", arquivo=arquivo_local or url or "ckan") as (db, n):
        if arquivo_local:
            caminho = arquivo_local
        else:
            u = url or _arquivo_mais_recente()
            caminho = baixar_temp(u, "capag" + (".xlsx" if u.lower().endswith(".xlsx") else ".csv"))
        linhas = ler_tabela(caminho)
        primeira = next(linhas, None)
        if not primeira:
            raise ValueError("Arquivo CAPAG vazio")
        cab = list(primeira)
        c_cod = achar_coluna(cab, ("COD", "IBGE"), "IBGE", ("COD", "MUNIC"))
        c_capag = achar_coluna(cab, ("CAPAG", "OFICIAL"), ("CLASSIFICACAO", "CAPAG"), "CAPAG", evitar=("INDICADOR",))
        c_ano = achar_coluna(cab, "ANO")
        if not c_cod or not c_capag:
            raise ValueError(f"Não achei as colunas de código IBGE e CAPAG. Cabeçalho: {cab[:12]}")
        extras = [c for c in cab if any(p in sem_acento(c) for p in ("INDICADOR", "NOTA"))]
        por_cod = {m.codigo_ibge: m for m in db.scalars(select(Municipio))}
        por_cod6 = {k[:6]: v for k, v in por_cod.items()}
        for linha in [primeira, *linhas]:
            cod = "".join(ch for ch in str(linha.get(c_cod) or "") if ch.isdigit())
            m = por_cod.get(cod) or por_cod6.get(cod[:6])
            nota = str(linha.get(c_capag) or "").strip().upper()
            if not m or not nota or nota in ("-", "NAN"):
                continue
            m.capag = nota[:10]
            try:
                m.capag_ano = ano or (int(float(linha[c_ano])) if c_ano and linha.get(c_ano) else None)
            except ValueError:
                m.capag_ano = ano
            m.capag_detalhe = {c: str(linha.get(c)) for c in extras if linha.get(c) not in (None, "")}
            n += 1
    return n.itens
