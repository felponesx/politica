"""Categorias do painel: toda tarefa tem uma categoria escrita de propósito, e a situação mostra a coleta que está rodando."""
from datetime import datetime

from fastapi.testclient import TestClient

from app.categorias import CATEGORIAS, MAPA, categoria_de
from app.collectors import TAREFAS
from app.db import SessionLocal, criar_tabelas
from app.main import app
from app.models import Coleta


def test_toda_tarefa_tem_categoria_escrita_de_proposito():
    escritas = {t for texto in MAPA.values() for t in texto.split()}
    faltam = sorted(set(TAREFAS) - escritas)
    assert not faltam, f"tarefas sem categoria: {faltam}"
    assert not sorted(escritas - set(TAREFAS)), "categoria aponta para tarefa que não existe"


def test_categorias_tem_id_unico_e_nome():
    ids = [c["id"] for c in CATEGORIAS]
    assert len(ids) == len(set(ids)) and all(c["nome"] for c in CATEGORIAS)
    assert set(MAPA) <= set(ids)
    assert categoria_de("nao-existe") == "outras"


def test_status_traz_categoria_e_estado_rodando():
    criar_tabelas()
    cliente = TestClient(app)
    with SessionLocal() as db:
        db.add(Coleta(fonte="bcb", tarefa="series", parametros={"anos": "2"}, status="rodando", inicio=datetime.now()))
        db.commit()
    dados = cliente.get("/fontes/status").json()
    assert {c["id"] for c in dados["categorias"]} == {c["id"] for c in CATEGORIAS}
    bcb = next(f for f in dados["fontes"] if f["tarefa"] == "bcb-series")
    assert bcb["categoria"] == "economia" and bcb["rodando"] is True and bcb["estado"] == "rodando"
    assert all(f["estado"] in ("rodando", "aviso", "erro", "ok", "parado") for f in dados["fontes"])
    with SessionLocal() as db:   # falha sem coleta boa anterior também vira erro (vermelho), não "nunca rodou"
        db.add(Coleta(fonte="tse", tarefa="candidatos", parametros={"ano": "2099"}, status="erro", inicio=datetime.now(), fim=datetime.now(), erro="HTTP 503"))
        db.commit()
    tse = next(f for f in cliente.get("/fontes/status").json()["fontes"] if f["tarefa"] == "tse-candidatos")
    assert tse["estado"] == "erro", tse
    with SessionLocal() as db:   # não deixa a coleta de teste "rodando" para os outros testes
        db.query(Coleta).filter(Coleta.fonte == "bcb", Coleta.tarefa == "series", Coleta.status == "rodando").update({"status": "ok", "fim": datetime.now()})
        db.commit()
