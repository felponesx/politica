"""Coletor da Câmara dos Deputados — https://dadosabertos.camara.leg.br/swagger/api.html"""
from datetime import date

import httpx

from app import http
from app.collectors.base import registrar_coleta
from app.models import Despesa, Parlamentar, Proposicao, Registro, Votacao, Voto
from app.utils import so_digitos, extrair_materia, extrair_placar, hash_curto, meses, para_data, para_float, upsert

BASE = "https://dadosabertos.camara.leg.br/api/v2"
CASA = "camara"


def paginar(caminho: str, params: dict | None = None):
    """Segue os links rel=next da API até acabar."""
    url, params = f"{BASE}{caminho}", dict(params or {})
    while url:
        resp = http.get_json(url, params=params) or {}
        params = None  # o link "next" já traz os parâmetros
        yield from resp.get("dados", [])
        url = next((l["href"] for l in resp.get("links", []) if l.get("rel") == "next"), None)


def _deputado(db, d: dict) -> Parlamentar:
    return upsert(db, Parlamentar, {"casa": CASA, "id_externo": str(d["id"])}, {
        "nome": d.get("nome") or d.get("nomeCivil") or "",
        "partido": d.get("siglaPartido"),
        "uf": d.get("siglaUf"),
        "foto_url": d.get("urlFoto"),
        "email": d.get("email"),
    })


def coletar_deputados():
    with registrar_coleta("camara", "deputados") as (db, n):
        for d in paginar("/deputados", {"itens": 100, "ordem": "ASC", "ordenarPor": "nome"}):
            _deputado(db, d)
            n += 1
    return n.itens


def coletar_proposicoes(inicio: date, fim: date):
    with registrar_coleta("camara", "proposicoes", inicio=inicio, fim=fim) as (db, n):
        for ini, f in meses(inicio, fim):
            for p in paginar("/proposicoes", {
                "dataApresentacaoInicio": ini.isoformat(), "dataApresentacaoFim": f.isoformat(),
                "itens": 100, "ordem": "ASC", "ordenarPor": "id",
            }):
                upsert(db, Proposicao, {"casa": CASA, "id_externo": str(p["id"])}, {
                    "sigla_tipo": p.get("siglaTipo"),
                    "numero": str(p.get("numero") or ""),
                    "ano": p.get("ano"),
                    "ementa": p.get("ementa"),
                })
                n += 1
            db.commit()
    return n.itens


def coletar_votacoes(inicio: date, fim: date, com_votos: bool = True):
    """Votações (plenário e comissões) + voto de cada deputado."""
    with registrar_coleta("camara", "votacoes", inicio=inicio, fim=fim) as (db, n):
        for ini, f in meses(inicio, fim):
            for v in paginar("/votacoes", {"dataInicio": ini.isoformat(), "dataFim": f.isoformat(),
                                           "itens": 200, "ordem": "ASC", "ordenarPor": "dataHoraRegistro"}):
                aprov = v.get("aprovacao")
                votacao = upsert(db, Votacao, {"casa": CASA, "id_externo": str(v["id"])}, {
                    "data": para_data(v.get("data") or v.get("dataHoraRegistro")),
                    "orgao": v.get("siglaOrgao"),
                    "descricao": v.get("descricao"),
                    # proposicaoObjeto costuma vir vazio; a matéria e o placar estão no texto da descrição
                    "materia": v.get("proposicaoObjeto") or extrair_materia(v.get("descricao")),
                    "placar_oficial": extrair_placar(v.get("descricao")),
                    "resultado": None if aprov is None else ("Aprovada" if aprov else "Rejeitada"),
                })
                db.flush()
                n += 1
                if com_votos:
                    try:
                        votos = http.get_json(f"{BASE}/votacoes/{v['id']}/votos") or {}
                    except httpx.HTTPStatusError as e:
                        if e.response.status_code != 404:
                            raise
                        votos = {}  # votação simbólica: a API responde 404 em vez de lista vazia
                    for voto in votos.get("dados", []):
                        dep = voto.get("deputado_") or {}
                        if not dep.get("id"):
                            continue
                        parl = _deputado(db, dep)
                        db.flush()
                        upsert(db, Voto, {"votacao_id": votacao.id, "parlamentar_id": parl.id}, {
                            "voto": voto.get("tipoVoto") or "?",
                            "partido_na_data": dep.get("siglaPartido"),
                        })
                db.commit()
    return n.itens


def coletar_despesas(ano: int, apenas_ids: list[str] | None = None):
    """Cota parlamentar (CEAP) de todos os deputados em exercício no ano."""
    with registrar_coleta("camara", "despesas", ano=ano) as (db, n):
        deputados = db.query(Parlamentar).filter_by(casa=CASA).all()
        if apenas_ids:
            deputados = [d for d in deputados if d.id_externo in apenas_ids]
        for dep in deputados:
            for d in paginar(f"/deputados/{dep.id_externo}/despesas", {"ano": ano, "itens": 100}):
                id_ext = str(d.get("codDocumento") or hash_curto(
                    d.get("numDocumento"), d.get("dataDocumento"), d.get("valorLiquido"), d.get("cnpjCpfFornecedor")))
                upsert(db, Despesa, {"parlamentar_id": dep.id, "id_externo": id_ext}, {
                    "ano": d.get("ano") or ano,
                    "mes": d.get("mes"),
                    "tipo": d.get("tipoDespesa"),
                    "fornecedor": d.get("nomeFornecedor"),
                    "cnpj_cpf": so_digitos(d.get("cnpjCpfFornecedor")),
                    "valor": para_float(d.get("valorLiquido")) or 0.0,
                    "url_documento": d.get("urlDocumento"),
                })
                n += 1
            db.commit()
    return n.itens


def coletar_orgaos():
    """Órgãos da Câmara (comissões, plenário, CPIs...)."""
    with registrar_coleta("camara", "orgaos") as (db, n):
        for o in paginar("/orgaos", {"itens": 100}):
            upsert(db, Registro, {"fonte": "camara", "tipo": "orgao", "chave": str(o["id"])}, {
                "titulo": o.get("nome"), "dados": o,
            })
            n += 1
    return n.itens
