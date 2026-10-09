import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./teste.db")

from fastapi.testclient import TestClient  # noqa: E402

from app.db import SessionLocal, criar_tabelas  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Norma, Parlamentar, Registro  # noqa: E402
from app.normalizar import normalizar  # noqa: E402

criar_tabelas()
cliente = TestClient(app)


def test_normaliza_e_busca():
    db = SessionLocal()
    db.add_all([
        Registro(fonte="pncp", tipo="contrato", chave="N-1", uf="BA", ano=2026, titulo="Transporte escolar rural",
                 valor=28608.0, dados={"orgaoEntidade": {"cnpj": "1388", "razaoSocial": "MUNICIPIO DE XIQUE-XIQUE",
                                                         "esferaId": "M"},
                                       "unidadeOrgao": {"municipioNome": "Xique-Xique"}, "niFornecedor": "4428",
                                       "nomeRazaoSocialFornecedor": "MARIA FEITOZA", "dataAssinatura": "2026-02-09"}),
        Registro(fonte="pncp", tipo="contrato", chave="N-2", uf="BA", ano=2026, titulo="Merenda", valor=1000.0,
                 dados={"niFornecedor": "4428", "nomeRazaoSocialFornecedor": "MARIA FEITOZA"}),
        Registro(fonte="obrasgov", tipo="obra", chave="99999.99-99", uf="SP", titulo="Fase 09 Lote 120", valor=11126062.6,
                 dados={"situacao": "Cadastrada", "tipos": [{"descricao": "Rodovia"}],
                        "fontesDeRecurso": [{"origem": "Estadual", "valorInvestimentoPrevisto": 11126062.6}]}),
        Registro(fonte="ibge", tipo="indicador:populacao", chave="AC-2026", uf="AC", ano=2026, titulo="População",
                 valor=46179008, dados={"unidade": "Pessoas", "periodo": "2026"}),
        Norma(tipo="LEI", id_externo="n1", numero="15526", ano=2026, ementa="Educação ambiental nas escolas"),
        Parlamentar(casa="camara", id_externo="p1", nome="Zulmira Teste", partido="ABC", uf="SP"),
    ])
    db.commit()
    db.close()

    r = normalizar()
    assert r["contratos"] >= 2 and r["obras"] >= 1
    assert normalizar()["contratos"] == 0  # incremental: nada novo

    c = cliente.get("/contratos", params={"uf": "BA", "esfera": "M"}).json()["itens"][0]
    assert c["municipio"] == "Xique-Xique" and c["fornecedor"] == "MARIA FEITOZA"
    det = cliente.get(f"/contratos/{c['id']}").json()
    assert det["fornecedor"]["total_contratado"] == 29608.0 and len(det["fornecedor"]["outros_contratos"]) == 1

    o = cliente.get("/obras", params={"uf": "SP", "tipo": "rodovia"}).json()["itens"][0]
    assert o["valor_previsto"] == 11126062.6 and o["valor_federal"] is None

    busca = cliente.get("/busca", params={"q": "Educação"}).json()["resultados"]
    assert busca["normas"][0]["titulo"] == "LEI 15526/2026"
    assert cliente.get("/busca", params={"q": "Zulmira"}).json()["resultados"]["parlamentares"][0]["subtitulo"] == "camara · ABC-SP"


def test_busca_portugues_postgres():
    """Só no Postgres: sem acento acha com acento, e o radical acha variações."""
    import pytest
    from app.db import engine
    if engine.dialect.name != "postgresql":
        pytest.skip("busca avançada só no Postgres")
    r = cliente.get("/busca", params={"q": "educacao escola"}).json()["resultados"]
    assert r["normas"][0]["subtitulo"] == "Educação ambiental nas escolas"
    r = cliente.get("/busca", params={"q": "zulmíra"}).json()["resultados"]
    assert r["parlamentares"][0]["titulo"] == "Zulmira Teste"
