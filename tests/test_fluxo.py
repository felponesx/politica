"""Fluxo federativo com dados simulados."""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./teste.db")

from fastapi.testclient import TestClient  # noqa: E402

from app import http  # noqa: E402
from app.collectors import receita, tesouro  # noqa: E402
from app.db import criar_tabelas  # noqa: E402
from app.main import app  # noqa: E402

criar_tabelas()
cliente = TestClient(app)

CSV = """Ano;Mês;UF;IMPOSTO SOBRE IMPORTAÇÃO;IRPJ;RECEITA PREVIDENCIÁRIA
2025;Janeiro;SP;1.000,50;2.000,00;3.000,00
2025;Fevereiro;SP;1.000,00;0;0
2025;Janeiro;Bahia;100,00;200,00;300,00
"""


def falso(url, params=None, headers=None):
    if url.endswith("/estados"):
        return {"items": [{"codigo": 25, "nome": "São Paulo"}, {"codigo": 5, "nome": "Bahia"}], "hasMore": False}
    if url.endswith("/transferencias"):
        return {"items": [{"codigo": 1, "nome": "FPE"}, {"codigo": 2, "nome": "FPM"}], "hasMore": False}
    if url.endswith("/por_estados"):
        return {"items": [{"uf": "SP", "ano": 2025, "mes": 1, "transferencia": "FPE", "valor": 500},
                          {"uf": "BA", "ano": 2025, "mes": 1, "transferencia": "FPE", "valor": 900}], "hasMore": False}
    if url.endswith("/por_estado_municipio"):
        return {"items": [{"uf": "SP", "ano": 2025, "mes": 1, "valor": 1500},
                          {"uf": "BA", "ano": 2025, "mes": 1, "valor": 600}], "hasMore": False}
    raise AssertionError(url)


def test_fluxo(monkeypatch, tmp_path):
    arq = tmp_path / "arrec.csv"
    arq.write_bytes(CSV.encode("latin-1"))
    assert receita.coletar_arrecadacao_estados(arquivo_local=str(arq)) == 3
    monkeypatch.setattr(http, "get_json", falso)
    assert tesouro.coletar_transferencias(2025) == 4

    sp = cliente.get("/estados/SP/fluxo", params={"ano": 2025}).json()
    assert sp["arrecadado"] == 7000.5
    assert sp["retornado"] == 2000
    assert sp["redistribuido_pais"] == 3500
    assert sp["saldo"] == 5000.5
    assert "limitacoes" in sp["metodologia"]

    ranking = cliente.get("/fluxo-federativo", params={"ano": 2025}).json()["estados"]
    assert ranking[0]["uf"] == "BA"  # BA recebe 1500 para 600 arrecadados
    assert cliente.get("/estados/SP/resumo").json()["fluxo_federativo"]["uf"] == "SP"


def test_historico_estados_responde():
    """Série por ano dos estados (gráficos em linha): sempre devolve as duas séries, mesmo sem coleta."""
    from fastapi.testclient import TestClient
    from app.main import app
    d = TestClient(app).get("/historico-estados").json()
    assert set(d) >= {"retorno", "arrecadacao", "repasses", "divida", "fonte", "nota"}
    assert set(d["retorno"]) == {"anos", "estados"} and isinstance(d["divida"]["anos"], list)


def test_historico_divida_por_quadrimestre():
    """Um relatório (RGF) já vira série: saldo do ano anterior e cada quadrimestre."""
    from fastapi.testclient import TestClient
    from app.db import SessionLocal
    from app.main import app
    from app.models import Registro
    with SessionLocal() as db:
        db.query(Registro).filter(Registro.chave.like("teste-hist-%")).delete(synchronize_session=False)
        for col, v in (("SALDO DO EXERCÍCIO ANTERIOR", 100.0), ("Até o 1º Quadrimestre", 110.0),
                       ("Até o 2º Quadrimestre", 120.0), ("Até o 3º Quadrimestre", 130.0)):
            db.add(Registro(fonte="siconfi", tipo="rgf-anexo02-divida", chave=f"teste-hist-{col}", uf="XX", ano=2025,
                            valor=v, dados={"cod_conta": "DividaConsolidada", "coluna": col}))
        db.commit()
    d = TestClient(app).get("/historico-estados").json()["divida"]
    assert d["estados"]["XX"] == {"2024.3": 100.0, "2025.1": 110.0, "2025.2": 120.0, "2025.3": 130.0}
    assert d["anos"].index("2024.3") < d["anos"].index("2025.1") < d["anos"].index("2025.3")
