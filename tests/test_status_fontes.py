"""Situação das fontes: a coleta é achada pelo par (fonte, tarefa) gravado em `coletas`, não pelo nome da linha de comando."""
from datetime import datetime

from fastapi.testclient import TestClient

from app.collectors import TAREFAS
from app.collectors.registro import registro_das_tarefas
from app.db import SessionLocal, criar_tabelas
from app.main import app
from app.models import Coleta


def test_toda_tarefa_tem_o_par_fonte_tarefa():
    mapa = registro_das_tarefas()
    assert set(TAREFAS) <= set(mapa), sorted(set(TAREFAS) - set(mapa))
    assert mapa["camara-proposicoes-situacao"] == ("camara", "proposicoes_situacao")
    assert mapa["siconfi-tributos"] == ("siconfi", "tributos_entes")
    assert mapa["transparencia-cartao"][0] == "transparencia"


def test_status_acha_a_coleta_pelo_par_gravado():
    criar_tabelas()
    cliente = TestClient(app)
    with SessionLocal() as db:
        agora = datetime.now()
        novas = [Coleta(fonte="camara", tarefa="proposicoes_situacao", parametros={"ano": "2026"}, status="ok", inicio=agora, fim=agora, itens=5),
                 Coleta(fonte="siconfi", tarefa="tributos_entes", parametros={"ano": "2025"}, status="erro", inicio=agora, fim=agora, erro="HTTP 429")]
        db.add_all(novas)
        db.commit()
        ids = [c.id for c in novas]
    try:
        depois = cliente.get("/fontes/status").json()
        por = {f["tarefa"]: f for f in depois["fontes"]}
        assert por["camara-proposicoes-situacao"]["situacao"] == "ok" and por["camara-proposicoes-situacao"]["itens_ultima_ok"] == 5
        assert por["siconfi-tributos"]["situacao"] == "sem_coleta_boa" and por["siconfi-tributos"]["ultimo_erro"] == "HTTP 429"
        assert depois["resumo"]["nunca_coletada"] < len(TAREFAS) and depois["resumo"]["ok"] >= 1
    finally:
        with SessionLocal() as db:
            db.query(Coleta).filter(Coleta.id.in_(ids)).delete(synchronize_session=False)
            db.commit()
