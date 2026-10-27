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
from app.models import Municipio, Registro
from app.utils import sem_acento, upsert
from sqlalchemy import func


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
        atual = db.scalar(select(func.max(Municipio.capag_ano))) or 0
        dist: dict[str, dict[str, int]] = {}
        anos_arq: dict[int, int] = {}
        grav = []
        for linha in [primeira, *linhas]:
            cod = "".join(ch for ch in str(linha.get(c_cod) or "") if ch.isdigit())
            m = por_cod.get(cod) or por_cod6.get(cod[:6])
            nota = str(linha.get(c_capag) or "").strip().upper()
            if not m or not nota or nota in ("-", "NAN"):
                continue
            try:
                a = ano or (int(float(linha[c_ano])) if c_ano and linha.get(c_ano) else None)
            except ValueError:
                a = ano
            if a:
                anos_arq[a] = anos_arq.get(a, 0) + 1
            dist.setdefault(m.uf, {})[nota[:10]] = dist.get(m.uf, {}).get(nota[:10], 0) + 1
            grav.append((m, nota[:10], a, {c: str(linha.get(c)) for c in extras if linha.get(c) not in (None, "")}))
        ano_arq = max(anos_arq, key=anos_arq.get) if anos_arq else None
        if ano_arq:  # guarda o resumo de cada ano para a tabela de linhas por ano (arquivos antigos não sobrescrevem a nota atual)
            upsert(db, Registro, {"fonte": "tesouro", "tipo": "capag_resumo", "chave": str(ano_arq)},
                   {"ano": ano_arq, "titulo": f"CAPAG dos municípios em {ano_arq}", "valor": sum(sum(v.values()) for v in dist.values()), "dados": {"por_uf": dist}})
        if not ano_arq or ano_arq >= atual:
            for m, nota, a, det in grav:
                m.capag, m.capag_ano, m.capag_detalhe = nota, a, det
                n += 1
    return n.itens
