import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./teste.db")

from datetime import date  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from app import http  # noqa: E402
from app.collectors import legislacao  # noqa: E402
from app.db import SessionLocal, criar_tabelas  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Proposicao, Votacao  # noqa: E402

criar_tabelas()
cliente = TestClient(app)


def falso(url, params=None, headers=None):
    if "legislacao/lista" in url:
        if params["tipo"] != "LEI":
            return {"ListaDocumento": {"documentos": None}}
        return {"ListaDocumento": {"documentos": {"documento": [
            {"Codigo": "9001", "Tipo": "LEI", "Numero": "15.100", "DataAssinatura": "2025-01-10",
             "Ementa": "Dispõe sobre transparência de dados públicos."},
            {"Codigo": "9002", "Tipo": "LEI", "Numero": "15.101", "DataAssinatura": "2025-01-12",
             "Ementa": "Altera a lei de trânsito."}]}}}
    if "/proposicoes/" in url:
        return {"dados": {"statusProposicao": {"descricaoSituacao": "Transformado em Norma Jurídica"},
                          "urnFinal": "urn:lex:br:federal:lei:2025-01-10;15100"}}
    raise AssertionError(url)


def test_normas_e_vinculo(monkeypatch):
    monkeypatch.setattr(http, "get_json", falso)
    db = SessionLocal()
    db.add(Proposicao(casa="camara", id_externo="555", sigla_tipo="PL", numero="42", ano=2024, ementa="Transparência"))
    db.add(Votacao(casa="camara", id_externo="v-42", data=date(2024, 11, 5), materia="PL 42/2024", resultado="Aprovada"))
    db.commit()
    db.close()

    assert legislacao.coletar_normas(2025) == 2
    assert legislacao.enriquecer_proposicoes_camara(2024) == 1

    lista = cliente.get("/legislacao", params={"q": "transparência"}).json()
    assert lista["total"] == 1
    det = cliente.get(f"/legislacao/{lista['itens'][0]['id']}").json()
    assert det["norma"]["urn"] == "urn:lex:br:federal:lei:2025-01-10;15100"
    assert det["proposicao_origem"]["numero"] == "42"
    assert det["votacoes"][0]["resultado"] == "Aprovada"
    resumo = cliente.get("/legislacao-resumo").json()
    assert next(r for r in resumo if r["ano"] == 2025)["quantidade"] == 2
