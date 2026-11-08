"""Lote 1 do coletor: deputados e senadores lidos pelo coletor entram em `parlamentares` pelo mesmo caminho do coletor próprio.
Os formatos aqui vêm do código que já roda (camara.py, senado.py), não de uma resposta real: o notebook é quem confere contra a API."""
import hashlib
import json

import pytest

from app.collectors import coletor_externo
from app.db import SessionLocal
from app.models import Coleta, Parlamentar

IDS_CAMARA = ["9001", "9002"]
IDS_SENADO = ["9101", "9102"]


def _publicar(pasta, fonte, corpo_obj, url):
    corpo = json.dumps(corpo_obj, ensure_ascii=False).encode()
    d = pasta / "dados" / fonte
    d.mkdir(parents=True, exist_ok=True)
    (d / "atual.json").write_bytes(corpo)
    meta = {"fonte": fonte, "vinculo": "BRASIL+", "url": url, "sha256": hashlib.sha256(corpo).hexdigest(),
            "sha256_original": hashlib.sha256(corpo).hexdigest(), "corrigido": False, "regras": [], "alteracoes": 0,
            "bytes": len(corpo), "coletado_em": "2026-11-08T12:00:00+00:00", "veredito": "ok", "decisao": "auto",
            "arquivo": "atual.json"}
    (d / "meta.json").write_text(json.dumps(meta))


@pytest.fixture(autouse=True)
def limpo():
    _limpar()
    yield
    _limpar()


def _limpar():
    db = SessionLocal()
    try:
        db.query(Parlamentar).filter(Parlamentar.casa.in_(["camara", "senado"]),
                                     Parlamentar.id_externo.in_(IDS_CAMARA + IDS_SENADO)).delete(synchronize_session=False)
        db.query(Coleta).filter(Coleta.fonte == "coletor", Coleta.tarefa == "ingestao").delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


def _parlamentares(casa, ids):
    db = SessionLocal()
    try:
        return {p.id_externo: p for p in db.query(Parlamentar).filter(Parlamentar.casa == casa,
                                                                      Parlamentar.id_externo.in_(ids)).all()}
    finally:
        db.close()


def test_deputados_das_paginas_juntas_entram_em_parlamentares(tmp_path):
    corpo = {"dados": [
        {"id": 9001, "nome": "Ana Teste", "siglaPartido": "AAA", "siglaUf": "SP"},
        {"id": 9002, "nome": "Beto Teste", "siglaPartido": "BBB", "siglaUf": "RJ"},
    ]}
    _publicar(tmp_path, "camara-deputados", corpo, "https://dadosabertos.camara.leg.br/api/v2/deputados")
    assert coletor_externo.coletar_ingestao(str(tmp_path)) == 2
    p = _parlamentares("camara", IDS_CAMARA)
    assert set(p) == set(IDS_CAMARA)
    assert p["9001"].nome == "Ana Teste" and p["9001"].partido == "AAA" and p["9001"].uf == "SP"


def test_senadores_entram_em_parlamentares(tmp_path):
    corpo = {"ListaParlamentarEmExercicio": {"Parlamentares": {"Parlamentar": [
        {"IdentificacaoParlamentar": {"CodigoParlamentar": 9101, "NomeParlamentar": "Carla Teste",
                                      "SiglaPartidoParlamentar": "CCC", "UfParlamentar": "MG"}},
        {"IdentificacaoParlamentar": {"CodigoParlamentar": 9102, "NomeParlamentar": "Dani Teste",
                                      "SiglaPartidoParlamentar": "DDD", "UfParlamentar": "PR"}},
    ]}}}
    _publicar(tmp_path, "senado-senadores", corpo, "https://legis.senado.leg.br/dadosabertos/senador/lista/atual.json")
    assert coletor_externo.coletar_ingestao(str(tmp_path)) == 2
    p = _parlamentares("senado", IDS_SENADO)
    assert set(p) == set(IDS_SENADO)
    assert p["9102"].nome == "Dani Teste" and p["9102"].uf == "PR"


def test_lista_de_deputados_vazia_e_erro_e_nao_grava(tmp_path):
    _publicar(tmp_path, "camara-deputados", {"dados": []}, "https://dadosabertos.camara.leg.br/api/v2/deputados")
    with pytest.raises(RuntimeError, match="camara-deputados"):
        coletor_externo.coletar_ingestao(str(tmp_path))
    assert _parlamentares("camara", IDS_CAMARA) == {}
