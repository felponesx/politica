"""Atenção básica — Ministério da Saúde (API de Dados Abertos, https://apidadosabertos.saude.gov.br).

- Unidades Básicas de Saúde: `/assistencia-a-saude/unidade-basicas-de-saude` (cerca de 47 mil UBS do CNES, uma linha por unidade, com o código do
  município). Contamos por município.
- Mais Médicos: `/atencao-primaria/pmmb-consolidado` (uma linha por município, com vagas ativas, ocupadas e desocupadas na data de referência).
  Linhas "ESTADUAL" e "DSEI" (distritos de saúde indígena) não são de um município: vão para um resumo à parte.
Limites da API: `limit` até 1.000 e `offset` é a posição da linha. Testamos também `cnes-leitos` e `hospitais-e-leitos`, mas `cnes-leitos` devolve uma linha por
chamada e `hospitais-e-leitos` mistura todos os meses sem dizer qual é qual: por isso leitos hospitalares ainda não entram (docs/FONTES.md).
"""
import logging

from app import http
from app.collectors.base import registrar_coleta
from app.models import Registro
from app.utils import UF_POR_CODIGO_IBGE, upsert

log = logging.getLogger("brasilplus.saude")
BASE = "https://apidadosabertos.saude.gov.br"
PAGINA = 1000
MINIMO_UBS = 40_000          # o Brasil tem ~47 mil; leitura menor que isso é leitura cortada
MINIMO_MUNICIPIOS_MM = 5_000  # o Mais Médicos traz ~5.570 municípios


def _paginas(caminho: str, chave: str):
    off = 0
    while True:
        d = http.get_json(f"{BASE}/{caminho}", params={"limit": PAGINA, "offset": off}) or {}
        linhas = d.get(chave) or []
        yield from linhas
        if len(linhas) < PAGINA:
            return
        off += PAGINA


def _uf(cod6: str) -> str | None:
    try:
        return UF_POR_CODIGO_IBGE.get(int(cod6[:2]))
    except ValueError:
        return None


def contar_ubs(linhas) -> dict[str, int]:
    """{código IBGE de 6 dígitos: número de UBS}. Repetição do mesmo CNES conta uma vez."""
    vistos, por_mun = set(), {}
    for x in linhas:
        cnes, cod = str(x.get("cnes") or "").strip(), str(x.get("ibge") or "").strip()[:6]
        if len(cod) < 6 or (cnes and cnes in vistos):
            continue
        vistos.add(cnes)
        por_mun[cod] = por_mun.get(cod, 0) + 1
    return por_mun


def coletar_ubs():
    """UBS por município (CNES, Ministério da Saúde)."""
    with registrar_coleta("saude", "ubs") as (db, n):
        por_mun = contar_ubs(_paginas("assistencia-a-saude/unidade-basicas-de-saude", "ubs"))
        total = sum(por_mun.values())
        if total < MINIMO_UBS:
            raise RuntimeError(f"só {total} UBS lidas (esperado mais de {MINIMO_UBS}): leitura incompleta, nada foi gravado")
        for cod, q in por_mun.items():
            upsert(db, Registro, {"fonte": "saude", "tipo": "ubs_municipio", "chave": cod},
                   {"uf": _uf(cod), "valor": float(q), "titulo": f"UBS em {cod}", "dados": {"ubs": q}})
            n += 1
        db.commit()
    return n.itens


def resumir_mais_medicos(linhas) -> tuple[dict[str, dict], dict]:
    """({cod6: {vagas, ocupadas, desocupadas, em_processo}}, resumo das linhas que não são de um município)."""
    por_mun, fora = {}, {"estadual": {"vagas": 0, "ocupadas": 0}, "dsei": {"vagas": 0, "ocupadas": 0}}
    data = None
    for x in linhas:
        vagas, oc = int(x.get("total_vagas_ativas") or 0), int(x.get("total_ocupadas") or 0)
        data = x.get("dt_referencia") or data
        nivel = (x.get("nivel") or "").upper()
        if nivel == "MUNICIPAL":
            cod = str(x.get("co_ibge") or "").strip()[:6]
            if len(cod) == 6:
                por_mun[cod] = {"vagas": vagas, "ocupadas": oc, "desocupadas": int(x.get("total_desocupadas") or 0),
                                "em_processo": int(x.get("em_processo_ocupacao") or 0)}
        elif nivel in ("ESTADUAL", "DSEI"):
            alvo = fora[nivel.lower()]
            alvo["vagas"] += vagas
            alvo["ocupadas"] += oc
    return por_mun, {**fora, "data_referencia": data}


def coletar_mais_medicos():
    """Vagas do Programa Mais Médicos (ativas, ocupadas, desocupadas) por município, na data de referência do Ministério."""
    with registrar_coleta("saude", "mais_medicos") as (db, n):
        por_mun, resumo = resumir_mais_medicos(_paginas("atencao-primaria/pmmb-consolidado", "pmmb"))
        if len(por_mun) < MINIMO_MUNICIPIOS_MM:
            raise RuntimeError(f"só {len(por_mun)} municípios lidos (esperado mais de {MINIMO_MUNICIPIOS_MM}): leitura incompleta, nada foi gravado")
        for cod, d in por_mun.items():
            upsert(db, Registro, {"fonte": "saude", "tipo": "mais_medicos_municipio", "chave": cod},
                   {"uf": _uf(cod), "valor": float(d["ocupadas"]), "titulo": f"Mais Médicos em {cod}", "dados": {**d, "data_referencia": resumo["data_referencia"]}})
            n += 1
        upsert(db, Registro, {"fonte": "saude", "tipo": "mais_medicos_resumo", "chave": "BR"}, {"titulo": "Mais Médicos: estadual e saúde indígena", "dados": resumo})
        db.commit()
    return n.itens
