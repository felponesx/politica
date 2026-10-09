"""Municípios e indicadores sociais — IBGE.

- Lista dos 5.570 municípios: API de localidades
  https://servicodados.ibge.gov.br/api/docs/localidades
- População estimada e PIB municipal: API de agregados (SIDRA)
  https://servicodados.ibge.gov.br/api/docs/agregados?versao=3
- Indicadores sociais: tabelas do SIDRA listadas em INDICADORES_SOCIAIS (edite à vontade) ou
  qualquer planilha com código IBGE + valor (IDHM do Atlas Brasil, DataSUS, INEP...) via
  `python -m scripts.coletar indicador-arquivo arquivo=idhm.csv nome=idhm descricao="IDHM" ano=2010`.
"""
import logging

from sqlalchemy import select

from app import http
from app.collectors.arquivos import achar_coluna, ler_tabela
from app.collectors.base import registrar_coleta
from app.models import IndicadorMunicipal, Municipio
from app.utils import UF_POR_CODIGO_IBGE, cavar, para_float, upsert

log = logging.getLogger("brasilplus.municipios")
LOCALIDADES = "https://servicodados.ibge.gov.br/api/v1/localidades/municipios"
AGREGADOS = "https://servicodados.ibge.gov.br/api/v3/agregados"

# nome: (agregado, variável, descrição, unidade). Confira as tabelas em https://sidra.ibge.gov.br
INDICADORES_SOCIAIS = {
    "densidade_demografica": (4714, 614, "Densidade demográfica (Censo 2022)", "hab/km²"),
    "area_territorial": (4714, 6318, "Área territorial (Censo 2022)", "km²"),
    "taxa_alfabetizacao": (9543, 2513, "Taxa de alfabetização de 15 anos ou mais (Censo 2022)", "%"),
}


def _serie_municipal(agregado: int, variavel: int, periodos: str = "-1"):
    """Gera (codigo_ibge, periodo, valor, unidade) para todos os municípios."""
    resp = http.get_json(f"{AGREGADOS}/{agregado}/periodos/{periodos}/variaveis/{variavel}",
                         params={"localidades": "N6[all]"}) or []
    for var in resp:
        for res in var.get("resultados", []):
            for serie in res.get("series", []):
                cod = str(cavar(serie, "localidade", "id") or "")
                for periodo, valor in (serie.get("serie") or {}).items():
                    v = para_float(valor) if valor not in ("-", "...", "X") else None
                    yield cod, str(periodo), v, var.get("unidade")


def coletar_municipios():
    """Lista oficial + população estimada mais recente + PIB municipal mais recente."""
    with registrar_coleta("ibge", "municipios") as (db, n):
        for m in http.get_json(LOCALIDADES) or []:
            uf = cavar(m, "microrregiao", "mesorregiao", "UF", "sigla") or cavar(m, "regiao-imediata", "regiao-intermediaria", "UF", "sigla")
            cod = str(m["id"])
            upsert(db, Municipio, {"codigo_ibge": cod},
                   {"nome": m.get("nome"), "uf": uf or UF_POR_CODIGO_IBGE.get(int(cod[:2])),
                    "microrregiao": cavar(m, "microrregiao", "nome")})
            n += 1
        db.commit()
        por_cod = {m.codigo_ibge: m for m in db.scalars(select(Municipio))}
        for cod, periodo, v, _ in _serie_municipal(6579, 9324):  # população residente estimada
            if cod in por_cod and v is not None:
                por_cod[cod].populacao, por_cod[cod].populacao_ano = int(v), int(periodo[:4])
        for cod, periodo, v, _ in _serie_municipal(5938, 37):  # PIB a preços correntes (mil R$)
            if cod in por_cod and v is not None:
                por_cod[cod].pib, por_cod[cod].pib_ano = v * 1000, int(periodo[:4])
    return n.itens


def coletar_indicadores_sociais(periodos: str = "-1", nomes: list[str] | None = None):
    """Baixa os indicadores de INDICADORES_SOCIAIS para todos os municípios.
    Um indicador que falhar (tabela mudou) é registrado no log e os outros continuam."""
    with registrar_coleta("ibge", "indicadores_sociais", periodos=periodos) as (db, n):
        falhas = []
        for nome, (agregado, variavel, descricao, unidade) in INDICADORES_SOCIAIS.items():
            if nomes and nome not in nomes:
                continue
            try:
                for cod, periodo, v, un in _serie_municipal(agregado, variavel, periodos):
                    if len(cod) != 7:
                        continue
                    upsert(db, IndicadorMunicipal, {"codigo_ibge": cod, "nome": nome, "ano": int(periodo[:4])},
                           {"uf": UF_POR_CODIGO_IBGE.get(int(cod[:2])), "descricao": descricao, "valor": v,
                            "unidade": unidade or un, "fonte": f"IBGE/SIDRA tabela {agregado}"})
                    n += 1
                db.commit()
            except Exception as e:
                db.rollback()
                falhas.append(f"{nome}: {e}")
                log.warning("Indicador %s falhou: %s", nome, e)
        if falhas and not n.itens:
            raise RuntimeError("; ".join(falhas))
    return n.itens


def importar_indicador_arquivo(arquivo: str, nome: str, descricao: str | None = None, ano: int | None = None,
                               unidade: str | None = None, fonte: str = "arquivo importado"):
    """Planilha com uma coluna de código IBGE do município e uma de valor (e, opcionalmente, ano)."""
    with registrar_coleta("arquivo", "indicador", nome=nome, arquivo=arquivo) as (db, n):
        linhas = ler_tabela(arquivo)
        primeira = next(linhas, None)
        if not primeira:
            raise ValueError("Arquivo vazio")
        cab = list(primeira)
        c_cod = achar_coluna(cab, ("COD", "IBGE"), "IBGE", ("COD", "MUNIC"))
        c_ano = achar_coluna(cab, "ANO")
        c_val = achar_coluna(cab, nome.upper(), "VALOR", "INDICE", "TAXA", evitar=("COD", "ANO", "IBGE"))
        if not c_cod or not c_val:
            raise ValueError(f"Não achei as colunas de código IBGE e valor. Cabeçalho: {cab[:10]}")
        for linha in [primeira, *linhas]:
            cod = "".join(ch for ch in str(linha.get(c_cod) or "") if ch.isdigit())
            if len(cod) == 6:  # alguns arquivos usam o código sem o dígito verificador
                m = db.scalar(select(Municipio.codigo_ibge).where(Municipio.codigo_ibge.like(cod + "%")))
                cod = m or cod
            a = ano or (int(float(linha[c_ano])) if c_ano and str(linha.get(c_ano) or "").strip() else None)
            if len(cod) != 7 or not a:
                continue
            upsert(db, IndicadorMunicipal, {"codigo_ibge": cod, "nome": nome, "ano": a},
                   {"uf": UF_POR_CODIGO_IBGE.get(int(cod[:2])), "descricao": descricao or nome,
                    "valor": para_float(linha.get(c_val)), "unidade": unidade, "fonte": fonte})
            n += 1
            if n.itens % 1000 == 0:
                db.commit()
    return n.itens
