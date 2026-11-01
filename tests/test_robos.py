"""Robôs: situação de cada coleta por categoria, veículos de notícia e auditoria do Gemini."""
from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from app import robos
from app.db import SessionLocal
from app.main import app
from app.models import Coleta, Registro

cliente = TestClient(app)


def test_situacao_por_status():
    agora = datetime(2026, 11, 1, 12, 0)
    assert robos.situacao(None, agora) == robos.AGUARDANDO
    assert robos.situacao(Coleta(fonte="x", tarefa="y", status="rodando", inicio=agora), agora) == robos.RODANDO
    assert robos.situacao(Coleta(fonte="x", tarefa="y", status="erro", inicio=agora, fim=agora), agora) == robos.FALHOU
    assert robos.situacao(Coleta(fonte="x", tarefa="y", status="parcial", inicio=agora, fim=agora), agora) == robos.PARCIAL
    assert robos.situacao(Coleta(fonte="x", tarefa="y", status="ok", inicio=agora, fim=agora), agora) == robos.OK
    antiga = agora - timedelta(days=30)
    assert robos.situacao(Coleta(fonte="x", tarefa="y", status="ok", inicio=antiga, fim=antiga), agora) == robos.ATRASADO


def test_categoria_de_fonte_desconhecida_vai_para_outras():
    assert robos.categoria_de("camara")[0] == "congresso"
    assert robos.categoria_de("fonte-que-nao-existe") == robos.OUTRAS


def test_rota_resumo_e_categoria_e_404():
    r = cliente.get("/robos")
    assert r.status_code == 200
    nomes = [c["nome"] for c in r.json()["categorias"]]
    assert "Notícias" in nomes and "Corretor Gemini" in nomes
    assert cliente.get("/robos/congresso").status_code == 200
    assert cliente.get("/robos/nao-existe").status_code == 404


def test_noticias_mostram_veiculos_com_ok_e_sem_materia():
    db = SessionLocal()
    try:
        agora = datetime.now()
        db.add(Registro(fonte="noticias", tipo="materia", chave="teste-robo-1", titulo="t",
                        dados={"veiculo": "g1", "tema": "geral", "data": agora.isoformat(timespec="minutes")}))
        db.commit()
    finally:
        db.close()
    d = cliente.get("/robos/noticias").json()
    por = {v["veiculo"].lower(): v for v in d["veiculos"]}
    g1 = [v for v in d["veiculos"] if v["veiculo"].lower() == "g1"]
    assert [v["situacao"] for v in g1 if v["tema"] == "geral"] == [robos.OK]
    assert [v["situacao"] for v in g1 if v["tema"] == "economia"] == [robos.SEM_MATERIA]  # matéria de um tema não conta no outro
    assert any(v["situacao"] == robos.SEM_MATERIA for v in d["veiculos"])


def test_auditoria_inclui_relatos_manuais_pendentes():
    d = cliente.get("/robos/auditoria").json()
    problemas = [i["problema"] for i in d["itens"]]
    assert "dado do impostômetro errado" in problemas
    assert "notícia de implantação com dado errado" in problemas
    assert d["contagem"]["pendente"] >= 2
    assert all("Gemini" != i["origem"] or i.get("status") for i in d["itens"])


def test_todas_as_categorias_da_copia_existem():
    from app import robos as r
    from scripts.exportar_snapshot import FIXAS
    for slug, *_ in r.CATEGORIAS:
        assert f"/robos/{slug}" in FIXAS
    assert "/robos" in FIXAS and "/robos/auditoria" in FIXAS
