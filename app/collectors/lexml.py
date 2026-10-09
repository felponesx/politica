"""Leis estaduais — acervo do Portal LexML (Senado), consulta SRU que devolve XML.
Docs: https://www12.senado.leg.br/dados-abertos/legislativo/legislacao/acervo-do-portal-lexml

Cada norma tem uma URN LexML, ex.: urn:lex:br;sao.paulo:estadual:lei:2023-12-20;17832
Daí tiramos estado, tipo, data e número. As expressões de busca (CQL) ficam em
settings.lexml_cql_estadual (tentadas em ordem) porque o índice exato do LexML ainda precisa ser
conferido na primeira coleta real; a que trouxer resultados é usada.
"""
import logging
import re
import xml.etree.ElementTree as ET

from app import http
from app.collectors.base import registrar_coleta
from app.config import settings
from app.models import Norma
from app.utils import CODIGO_IBGE_POR_UF, NOME_PARA_UF, UFS, hash_curto, para_data, upsert

log = logging.getLogger("brasilplus.lexml")
UF_PARA_NOME = {v: k for k, v in NOME_PARA_UF.items()}
TIPO_URN = {"lei": "LEI", "lei.complementar": "LCP", "decreto": "DEC", "emenda.constitucional": "EMC",
            "constituicao": "CON", "lei.organica": "LOR", "resolucao": "RES", "decreto.legislativo": "DLG"}
URN_RE = re.compile(r"urn:lex:br;([a-z.]+):estadual:([a-z.]+):(\d{4}-\d{2}-\d{2})[^;]*;?([\w.\-]*)")


def localidade(uf: str) -> str:
    """'SP' -> 'sao.paulo' (forma usada nas URNs do LexML)."""
    return UF_PARA_NOME[uf].lower().replace(" ", ".")


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def interpretar(xml_texto: str):
    """Gera (total, [registros]) do XML SRU; cada registro é um dict com os campos Dublin Core + urn."""
    raiz = ET.fromstring(xml_texto)
    total = next((int(e.text) for e in raiz.iter() if _local(e.tag) == "numberOfRecords" and (e.text or "").isdigit()), 0)
    regs = []
    for rec in (e for e in raiz.iter() if _local(e.tag) == "recordData"):
        d = {}
        for el in rec.iter():
            nome, txt = _local(el.tag), (el.text or "").strip()
            if txt and nome not in d:
                d[nome] = txt
        regs.append(d)
    return total, regs


def converter(d: dict, uf: str) -> dict | None:
    urn = d.get("urn") or next((v for v in d.values() if str(v).startswith("urn:lex:br;")), None)
    m = URN_RE.search(urn or "")
    if not m:
        return None
    _, tipo_urn, data, numero = m.groups()
    data_n = para_data(data)
    return {"id_externo": hash_curto(urn), "tipo": TIPO_URN.get(tipo_urn, tipo_urn.upper()[:20]),
            "numero": (numero or "").replace(".", "")[:20] or None, "ano": data_n.year if data_n else None,
            "data": data_n, "ementa": d.get("description") or d.get("title"), "urn": urn[:300],
            "url_texto": f"https://www.lexml.gov.br/urn/{urn}", "esfera": "estadual", "uf": uf,
            "dados": {k: v for k, v in d.items() if len(str(v)) < 500}}


def coletar_estaduais(ano: int, ufs: list[str] | None = None, limite_por_uf: int = 2000):
    """Leis, leis complementares e emendas às constituições estaduais publicadas no ano."""
    with registrar_coleta("lexml", "normas_estaduais", ano=ano, ufs=",".join(ufs or ["todas"])) as (db, n):
        for uf in ufs or UFS:
            loc = localidade(uf)
            for modelo in settings.lexml_cql_estadual:
                cql = modelo.format(localidade=loc, ano=ano, uf=uf, ibge=CODIGO_IBGE_POR_UF[uf])
                inicio, total, achou = 1, None, 0
                while total is None or (inicio <= total and inicio <= limite_por_uf):
                    r = http.get(settings.lexml_sru_url, params={
                        "operation": "searchRetrieve", "version": "1.1", "query": cql,
                        "startRecord": inicio, "maximumRecords": 100}, headers={"Accept": "application/xml"})
                    if "<html" in r.text[:500].lower():
                        raise RuntimeError("O LexML respondeu com uma página HTML (\"Verificação de segurança\" do Senado, "
                                           "proteção contra robôs) em vez do XML da busca. A coleta automática está bloqueada "
                                           "a partir deste servidor.")
                    total, regs = interpretar(r.text)
                    if not regs:
                        break
                    for d in regs:
                        v = converter(d, uf)
                        if v and v["ano"] == ano:
                            upsert(db, Norma, {"fonte": "lexml", "id_externo": v.pop("id_externo")}, v)
                            n += 1
                            achou += 1
                    inicio += len(regs)
                db.commit()
                if achou:
                    break  # esta expressão funcionou; não tenta as próximas
                log.info("LexML %s: nenhuma norma com a expressão %s", uf, cql)
    return n.itens
