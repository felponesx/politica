"""Setor financeiro (IF.data do Banco Central): soma das instituições e a conta de onde vai a receita."""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./teste.db")

from fastapi.testclient import TestClient  # noqa: E402

from app.collectors import bcb_financeiro  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Registro  # noqa: E402

cliente = TestClient(app)


def _linha(cod, nome, valor):
    return {"CodInst": cod, "NomeColuna": nome, "Saldo": valor}


def test_calcular_soma_semestres_e_fecha_a_conta():
    balanco = [_linha("C1", "Ativo Total", 1000), _linha("C1", "Carteira de Crédito", 400), _linha("C1", "Patrimônio Líquido", 100)]
    sem = [_linha("C1", "Rendas de Operações de Crédito  (c)", 300), _linha("C1", "Rendas de Tarifas Bancárias  (m)", 50),
           _linha("C1", "Despesas de Captações  (g)", -150), _linha("C1", "Resultado com Perda Esperada  (f)", -40),
           _linha("C1", "Despesas de Pessoal  (o)", -30), _linha("C1", "Despesas Administrativas  (p)", -20),
           _linha("C1", "Lucro Líquido  (z) = (w) + (x) + (y)", 100)]
    r = bcb_financeiro.calcular(balanco, sem + sem, {"C1": {"NomeInstituicao": "BANCO TESTE", "Uf": "SP"}})  # dois semestres iguais
    t = r["totais"]
    assert r["instituicoes"] == 1 and t["receita"] == 700 and t["lucro"] == 200 and t["captacao"] == 300
    assert r["maiores"][0]["nome"] == "BANCO TESTE" and r["maiores"][0]["ativo"] == 1000


def test_economia_empresas_traz_o_setor_financeiro():
    from app.routers.v02 import _setor_financeiro
    d = {"instituicoes": 2, "referencia": "2025-12", "totais": {"receita": 1000.0, "lucro": 100.0, "captacao": 500.0, "perdas": 100.0, "pessoal": 100.0, "administracao": 100.0}}
    s = _setor_financeiro(d)
    assert s["margem"] == 10.0 and s["receita_media"] == 500.0 and abs(sum(v for _, v in s["fatias"]) - 100) < 0.2
    with SessionLocal() as db:
        db.query(Registro).filter_by(fonte="bcb", tipo="financeiro").delete()
        db.add(Registro(fonte="bcb", tipo="financeiro", chave="sistema", ano=2025, titulo="t", dados=d))
        db.add(Registro(fonte="ibge", tipo="empresas_economia", chave="9999", ano=9999, titulo="t",
                        dados={"ano": 9999, "setores": {"industria": {"empresas": 10, "pessoal": 100, "receita": 1e6, "valor_adicionado": 4e5, "gastos_pessoal": 2e5}}}))
        db.commit()
    try:
        r = cliente.get("/economia-empresas").json()
        assert r["financeiro"]["nome"].startswith("Financeiro") and r["financeiro"]["empresas"] == 2
    finally:
        with SessionLocal() as db:
            db.query(Registro).filter_by(fonte="bcb", tipo="financeiro").delete()
            db.query(Registro).filter_by(fonte="ibge", tipo="empresas_economia", chave="9999").delete()
            db.commit()
