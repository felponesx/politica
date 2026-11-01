"""Bots: execução paralela por fonte, verificador Gemini gravando sugestões e rota de revisão."""
import threading
import time

import pytest

from app.collectors import paralelo
from app.collectors.paralelo import executar_grupo
from app.db import SessionLocal
from app.models import Registro


def test_fontes_diferentes_rodam_juntas_e_mesma_fonte_em_fila():
    ativos = {"n": 0, "pico": 0}
    lock = threading.Lock()
    ordem = []

    def executar(nome, params):
        with lock:
            ativos["n"] += 1
            ativos["pico"] = max(ativos["pico"], ativos["n"])
            ordem.append(nome)
        time.sleep(0.05)
        with lock:
            ativos["n"] -= 1

    registro = {"a1": ("fonte_a", "x"), "a2": ("fonte_a", "y"), "b1": ("fonte_b", "z")}
    tarefas = [("a1", {}), ("a2", {}), ("b1", {})]
    res = executar_grupo(tarefas, executar, registro, workers=4, pausa=0.0)
    assert [n for n, _ in res] == ["a1", "a2", "b1"]  # ordem original preservada
    assert all(e is None for _, e in res)
    assert ativos["pico"] == 2  # fonte_a e fonte_b em paralelo; a1 e a2 nunca juntas


def test_uma_falha_nao_para_as_outras():
    def executar(nome, params):
        if nome == "ruim":
            raise ValueError("fonte fora do ar")

    res = executar_grupo([("ruim", {}), ("boa", {})], executar, {}, workers=2, pausa=0.0)
    assert isinstance(dict(res)["ruim"], ValueError)
    assert dict(res)["boa"] is None


def test_pausa_entre_tarefas_da_mesma_fonte(monkeypatch):
    esperas = []
    monkeypatch.setattr(paralelo.time, "sleep", lambda s: esperas.append(s))
    executar_grupo([("a", {}), ("b", {}), ("c", {})], lambda n, p: None, {"a": ("f", ""), "b": ("f", ""), "c": ("f", "")}, workers=1, pausa=2.0)
    assert esperas == [2.0, 2.0]


def test_gemini_sem_chave_falha_sem_gravar(monkeypatch, tmp_path):
    from app.collectors.gemini_verificar import coletar_gemini_verificar
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    (tmp_path / "x.json").write_text("{}", encoding="utf-8")
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        coletar_gemini_verificar(pasta=str(tmp_path))


def test_gemini_grava_sugestao_pendente_e_preserva_decisao(monkeypatch, tmp_path):
    import json

    import httpx

    from app.collectors import gemini_verificar as gv
    from scripts import verificar_gemini as vg

    (tmp_path / "x.json").write_text(json.dumps({"valor": 10}), encoding="utf-8")
    monkeypatch.setenv("GEMINI_API_KEY", "chave-falsa")

    def achados(cli, chave, modelo, arquivo, texto):
        return [{"caminho": "valor", "problema": "valor suspeito", "valor_atual": "10", "sugestao": "conferir", "fonte": "IBGE", "confianca": "baixa"}]

    monkeypatch.setattr(vg, "perguntar", achados)
    monkeypatch.setattr(vg, "pedacos", lambda p: [("x.json", "{}")])
    gv.coletar_gemini_verificar(pasta=str(tmp_path))
    db = SessionLocal()
    try:
        reg = db.query(Registro).filter_by(fonte="gemini", tipo="sugestao").one()
        assert reg.dados["status"] == "pendente" and reg.dados["problema"] == "valor suspeito"
        reg.dados = {**reg.dados, "status": "descartada"}
        db.commit()
        chave = reg.chave
    finally:
        db.close()
    gv.coletar_gemini_verificar(pasta=str(tmp_path))  # nova rodada não reabre a decisão humana
    db = SessionLocal()
    try:
        assert db.query(Registro).filter_by(fonte="gemini", tipo="sugestao", chave=chave).one().dados["status"] == "descartada"
    finally:
        db.close()


def test_rota_sugestoes_lista_pendentes():
    from fastapi.testclient import TestClient

    from app.main import app
    client = TestClient(app)
    db = SessionLocal()
    try:
        db.add(Registro(fonte="gemini", tipo="sugestao", chave="teste-rota-1", titulo="t", dados={"problema": "p1", "status": "pendente"}))
        db.add(Registro(fonte="gemini", tipo="sugestao", chave="teste-rota-2", titulo="t", dados={"problema": "p2", "status": "aprovada"}))
        db.commit()
    finally:
        db.close()
    r = client.get("/sugestoes?status=pendente")
    assert r.status_code == 200
    problemas = [i["problema"] for i in r.json()["itens"]]
    assert "p1" in problemas and "p2" not in problemas
