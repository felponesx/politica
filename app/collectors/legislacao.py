"""Legislação federal — base de normas do Senado Federal (Dados Abertos).
Endpoints: /legislacao/lista.json, /legislacao/{codigo}.json, /legislacao/{tipo}/{numero}/{ano}.json

Ligação norma ↔ projeto de origem: a Câmara informa no detalhe da proposição o campo `urnFinal`
(URN LexML da norma gerada). Montamos a URN de cada norma e casamos as duas.
"""
import logging
from datetime import date

from app import http
from app.collectors.base import registrar_coleta
from app.collectors.camara import BASE as CAMARA
from app.models import Norma, Proposicao
from app.utils import achar_lista, para_data, pegar, upsert

BASE = "https://legis.senado.leg.br/dadosabertos"
log = logging.getLogger("brasilplus.legislacao")

TIPOS_PADRAO = ["LEI", "LCP", "EMC", "MPV", "DEC", "DLG"]
NOME_URN = {"LEI": "lei", "LCP": "lei.complementar", "EMC": "emenda.constitucional",
            "MPV": "medida.provisoria", "DEC": "decreto", "DLG": "decreto.legislativo", "DEL": "decreto.lei"}


def montar_urn(tipo: str, data, numero) -> str | None:
    """Ex.: urn:lex:br:federal:lei:2025-01-10;15100"""
    if not (tipo in NOME_URN and data and numero):
        return None
    num = "".join(ch for ch in str(numero) if ch.isdigit())
    return f"urn:lex:br:federal:{NOME_URN[tipo]}:{data.isoformat()};{int(num)}" if num else None


def _salvar_norma(db, doc: dict, tipo_padrao: str | None = None):
    codigo = pegar(doc, "Codigo", "CodigoNorma", "id")
    if not codigo:
        return None
    tipo = (pegar(doc, "Tipo", "SiglaTipo", "SiglaTipoNorma", "tipoNorma") or tipo_padrao or "?")
    if isinstance(tipo, dict):
        tipo = pegar(tipo, "Sigla", "sigla") or tipo_padrao or "?"
    tipo = str(tipo).upper().split("-")[0][:20]  # 'LEI-n' -> 'LEI'
    if tipo_padrao and tipo in ("", "?"):
        tipo = tipo_padrao
    numero = pegar(doc, "Numero", "NumeroNorma", "numero")
    data = para_data(pegar(doc, "DataAssinatura", "Data", "DataNorma", "dataAssinatura"))
    ano = pegar(doc, "anoassinatura", "Ano", "AnoNorma") or (data.year if data else None)
    urn = pegar(doc, "Urn", "UrnLexml", "urn") or montar_urn(tipo, data, numero)
    return upsert(db, Norma, {"fonte": "senado", "id_externo": str(codigo)}, {
        "tipo": tipo, "numero": str(numero) if numero else None,
        "ano": int(ano) if ano else None, "data": data,
        "ementa": pegar(doc, "Ementa", "EmentaNorma", "ementa"),
        "url_texto": pegar(doc, "UrlTexto", "Url", "UrlTextoIntegral") or (f"https://www.lexml.gov.br/urn/{urn}" if urn else None),
        "urn": urn, "dados": doc,
    })


def coletar_normas(ano: int, tipos: list[str] | None = None):
    """Normas federais de um ano, por tipo."""
    with registrar_coleta("senado", "legislacao", ano=ano) as (db, n):
        for tipo in tipos or TIPOS_PADRAO:
            try:
                resp = http.get_json(f"{BASE}/legislacao/lista.json", params={"tipo": tipo, "ano": ano}) or {}
            except Exception as e:  # um tipo inválido não derruba os outros
                log.warning("legislacao tipo=%s falhou: %s", tipo, e)
                continue
            for doc in achar_lista(resp, ("Codigo", "CodigoNorma", "Ementa")):
                if _salvar_norma(db, doc, tipo):
                    n += 1
            db.commit()
        vincular_por_urn(db)
    return n.itens


def enriquecer_proposicoes_camara(ano: int, tipos=("PL", "PLP", "PEC", "MPV"), limite: int = 2000):
    """Busca o detalhe das proposições da Câmara (situação e urnFinal) e liga às normas."""
    with registrar_coleta("camara", "proposicoes_detalhe", ano=ano) as (db, n):
        props = (db.query(Proposicao).filter(Proposicao.casa == "camara", Proposicao.ano == ano,
                                             Proposicao.sigla_tipo.in_(tipos)).limit(limite).all())
        for p in props:
            det = (http.get_json(f"{CAMARA}/proposicoes/{p.id_externo}") or {}).get("dados", {})
            status = det.get("statusProposicao") or {}
            p.situacao = (status.get("descricaoSituacao") or "")[:300] or None
            p.urn_final = det.get("urnFinal") or None
            n += 1
            if n.itens % 100 == 0:
                db.commit()
        db.commit()
        vincular_por_urn(db)
    return n.itens


ARQ_PROPOSICOES = "https://dadosabertos.camara.leg.br/arquivos/proposicoes/json/proposicoes-{ano}.json"


def situacao_proposicoes_camara(ano: int | None = None, desde: int | None = None):
    """Situação atual (último status) e data de apresentação de todas as proposições da Câmara, pelo arquivo anual
    de dados abertos (um download por ano, em vez de uma consulta por proposição). Só atualiza as que já estão no banco."""
    hoje = date.today().year
    anos = range(int(desde), hoje + 1) if desde else [int(ano or hoje)]
    with registrar_coleta("camara", "proposicoes_situacao", ano=ano, desde=desde) as (db, n):
        for a in anos:
            try:
                dados = http.get_json(ARQ_PROPOSICOES.format(ano=a)) or {}
            except Exception as e:  # um ano sem arquivo não derruba os outros
                log.warning("arquivo de proposições %s falhou: %s", a, e)
                n.avisos.append(f"{a}: {e}")
                continue
            por_id = {str(p.id_externo): p for p in db.query(Proposicao).filter(Proposicao.casa == "camara", Proposicao.ano == a)}
            for d in achar_lista(dados, ("id", "siglaTipo", "ementa")):
                p = por_id.get(str(d.get("id")))
                if not p:
                    continue
                st = d.get("ultimoStatus") or {}
                sit = st.get("descricaoSituacao") or d.get("ultimoStatus_descricaoSituacao")
                tram = st.get("descricaoTramitacao") or d.get("ultimoStatus_descricaoTramitacao")
                if st.get("regime"):
                    p.regime = str(st["regime"])[:120]
                if sit or tram:
                    p.situacao = (sit or tram)[:300]
                if not p.data_apresentacao:
                    p.data_apresentacao = para_data(d.get("dataApresentacao"))
                if d.get("urnFinal") and not p.urn_final:
                    p.urn_final = d["urnFinal"]
                n += 1
            db.commit()
        vincular_por_urn(db)
    return n.itens


def vincular_por_urn(db) -> int:
    """Liga normas às proposições cuja urnFinal coincide (compara pelo prefixo tipo:data;numero)."""
    def chave(urn):
        return urn.split("!")[0].split("@")[0].lower() if urn else None

    por_urn = {chave(p.urn_final): p.id for p in db.query(Proposicao).filter(Proposicao.urn_final.isnot(None))}
    ligadas = 0
    for norma in db.query(Norma).filter(Norma.urn.isnot(None), Norma.proposicao_id.is_(None)):
        pid = por_urn.get(chave(norma.urn))
        if pid:
            norma.proposicao_id = pid
            ligadas += 1
    db.commit()
    return ligadas
