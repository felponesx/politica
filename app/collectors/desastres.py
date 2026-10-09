"""Desastres reconhecidos por município — Defesa Civil Nacional (S2ID) / Atlas Digital de Desastres.

As fontes publicam planilhas (CSV/XLSX) sem API estável. Baixe a planilha de "reconhecimentos" do S2ID
(https://s2id.mi.gov.br) ou do Atlas Digital (https://atlasdigital.mdr.gov.br) e rode:
  python -m scripts.coletar desastres arquivo_local=reconhecimentos.xlsx
As colunas são achadas pelo nome (código IBGE, município, UF, data, desastre/COBRADE, situação).
"""
from app.collectors.arquivos import achar_coluna, baixar_temp, ler_tabela
from app.collectors.base import registrar_coleta
from app.models import OcorrenciaDesastre
from app.utils import UF_POR_CODIGO_IBGE, hash_curto, para_data, para_uf, upsert


def importar_desastres(arquivo_local: str | None = None, url: str | None = None, fonte: str = "S2ID"):
    if not arquivo_local and not url:
        raise ValueError("Informe arquivo_local=... (planilha do S2ID/Atlas) ou url=...")
    with registrar_coleta("defesacivil", "desastres", arquivo=arquivo_local or url) as (db, n):
        caminho = arquivo_local or baixar_temp(url, "desastres" + (".xlsx" if url.lower().endswith(".xlsx") else ".csv"))
        linhas = ler_tabela(caminho)
        primeira = next(linhas, None)
        if not primeira:
            raise ValueError("Planilha vazia")
        cab = list(primeira)
        c = {"cod": achar_coluna(cab, ("COD", "IBGE"), "IBGE"), "mun": achar_coluna(cab, "MUNICIPIO", evitar=("COD",)),
             "uf": achar_coluna(cab, "UF", evitar=("COD",)),
             "data": achar_coluna(cab, ("DATA", "OCORR"), ("DATA", "DESASTRE"), ("DATA", "REGISTRO"), ("DATA", "DECRET"), "DATA"),
             "tipo": achar_coluna(cab, ("DESCRICAO", "COBRADE"), "TIPOLOGIA", "DESASTRE", ("NOME", "EVENTO"), evitar=("DATA", "COD")),
             "cobrade": achar_coluna(cab, ("COD", "COBRADE"), "COBRADE"),
             "sit": achar_coluna(cab, "RECONHEC", "STATUS", "SITUACAO")}
        if not (c["cod"] or c["mun"]) or not (c["tipo"] or c["cobrade"]):
            raise ValueError(f"Não reconheci as colunas da planilha. Cabeçalho: {cab[:12]}")
        for l in [primeira, *linhas]:
            g = lambda k: str(l.get(c[k]) or "").strip() if c[k] else ""
            cod = "".join(ch for ch in g("cod") if ch.isdigit())[:7] or None
            uf = para_uf(g("uf")) or (UF_POR_CODIGO_IBGE.get(int(cod[:2])) if cod else None)
            data = para_data(l.get(c["data"])) if c["data"] else None
            tipo = g("tipo") or g("cobrade")
            chave = hash_curto(cod or g("mun"), uf, data, tipo, g("cobrade"))
            upsert(db, OcorrenciaDesastre, {"chave": chave},
                   {"codigo_ibge": cod, "municipio": g("mun") or None, "uf": uf, "data": data, "tipo": tipo[:200] or None,
                    "cobrade": g("cobrade")[:20] or None, "situacao": g("sit")[:120] or None, "fonte": fonte})
            n += 1
            if n.itens % 1000 == 0:
                db.commit()
    return n.itens
