"""Categorias do painel: toda tarefa tem uma categoria escrita de propósito, e a situação mostra a coleta que está rodando."""
from datetime import datetime

from fastapi.testclient import TestClient

import json
import re
from pathlib import Path

from app.categorias import CATEGORIAS, MAPA, SEM_COLETA_PROPRIA, categoria_de, categorias_atuais, tem_secao
from app.collectors import TAREFAS
from app.db import SessionLocal, criar_tabelas
from app.main import app
from app.models import Coleta


def test_toda_tarefa_tem_categoria_escrita_de_proposito():
    escritas = {t for texto in MAPA.values() for t in texto.split()}
    faltam = sorted(set(TAREFAS) - escritas)
    assert not faltam, f"tarefas sem categoria: {faltam}"
    assert not sorted(escritas - set(TAREFAS)), "categoria aponta para tarefa que não existe"


def test_categorias_sao_as_secoes_do_menu_do_site():
    """A lista do painel acompanha o menu do site: nenhuma seção do menu fica de fora (as novas entram sozinhas)."""
    site = (Path(__file__).resolve().parents[1] / "site" / "index.html").read_text(encoding="utf-8")
    nav = json.loads(re.search(r"const NAV=(\[.*?\]);", site, re.S).group(1))
    secoes = {i: n for i, n in nav if i not in ("inicio", "admin")}
    atuais = {c["id"]: c["nome"] for c in categorias_atuais()}
    assert set(secoes) <= set(atuais), set(secoes) - set(atuais)
    assert all(atuais[i] == secoes[i] for i in secoes)


def test_secao_nova_no_menu_vira_categoria_sozinha(tmp_path, monkeypatch):
    pasta = tmp_path / "site"
    pasta.mkdir()
    (pasta / "index.html").write_text('<script>const NAV=[["inicio","Início"],["gastos","Gastos Públicos"],["transporte","Transporte"]];</script>', encoding="utf-8")
    monkeypatch.setenv("BRASILPLUS_SITE", str(pasta))
    atuais = {c["id"]: c for c in categorias_atuais()}
    assert atuais["transporte"]["nome"] == "Transporte" and atuais["transporte"]["nova"] is True
    assert "nova" not in atuais["gastos"] and "saude" in atuais   # as da lista fixa continuam, mesmo fora do menu
    assert [c["id"] for c in categorias_atuais()][: len(CATEGORIAS)] == [c["id"] for c in CATEGORIAS]


def test_coleta_sem_secao_e_avisada():
    assert tem_secao("bcb-series") and not tem_secao("coleta-nova-sem-secao")
    assert categoria_de("coleta-nova-sem-secao") == "relatorios"


def test_toda_secao_com_coleta_tem_tarefa_e_as_sem_coleta_estao_marcadas():
    assert set(MAPA) == {c["id"] for c in CATEGORIAS}
    assert {c for c in MAPA if not MAPA[c].split()} == SEM_COLETA_PROPRIA
    assert categoria_de("nao-existe") == "relatorios"


def test_status_traz_categoria_e_estado_rodando():
    criar_tabelas()
    cliente = TestClient(app)
    with SessionLocal() as db:
        db.add(Coleta(fonte="bcb", tarefa="series", parametros={"anos": "2"}, status="rodando", inicio=datetime.now()))
        db.commit()
    dados = cliente.get("/fontes/status").json()
    assert {c["id"] for c in CATEGORIAS} <= {c["id"] for c in dados["categorias"]}
    assert "sem_secao" in dados and all("sem_secao" in f for f in dados["fontes"])
    bcb = next(f for f in dados["fontes"] if f["tarefa"] == "bcb-series")
    assert bcb["categoria"] == "indicadores" and bcb["rodando"] is True and bcb["estado"] == "rodando"
    assert all(f["estado"] in ("rodando", "aviso", "erro", "ok", "parado") for f in dados["fontes"])
    with SessionLocal() as db:   # falha sem coleta boa anterior também vira erro (vermelho), não "nunca rodou"
        db.add(Coleta(fonte="tse", tarefa="candidatos", parametros={"ano": "2099"}, status="erro", inicio=datetime.now(), fim=datetime.now(), erro="HTTP 503"))
        db.commit()
    tse = next(f for f in cliente.get("/fontes/status").json()["fontes"] if f["tarefa"] == "tse-candidatos")
    assert tse["estado"] == "erro", tse
    with SessionLocal() as db:   # não deixa a coleta de teste "rodando" para os outros testes
        db.query(Coleta).filter(Coleta.fonte == "bcb", Coleta.tarefa == "series", Coleta.status == "rodando").update({"status": "ok", "fim": datetime.now()})
        db.commit()
