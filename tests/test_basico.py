"""Testes com respostas simuladas (sem internet). Rode: pytest -q"""
import os
from datetime import date

os.environ.setdefault("DATABASE_URL", "sqlite:///./teste.db")
if os.environ["DATABASE_URL"].startswith("sqlite") and os.path.exists("teste.db"):
    os.remove("teste.db")

from fastapi.testclient import TestClient  # noqa: E402

from app import http  # noqa: E402
from app.collectors import camara, ibge, senado  # noqa: E402
from app.db import criar_tabelas  # noqa: E402
from app.main import app  # noqa: E402

criar_tabelas()
cliente = TestClient(app)


def falso_get_json(url, params=None, headers=None):
    if url.endswith("/deputados"):
        return {"dados": [{"id": 1, "nome": "Fulana Silva", "siglaPartido": "ABC", "siglaUf": "SP"},
                          {"id": 2, "nome": "Beltrano Souza", "siglaPartido": "XYZ", "siglaUf": "BA"}], "links": []}
    if url.endswith("/votacoes"):
        return {"dados": [{"id": "123-45", "data": "2026-09-10", "siglaOrgao": "PLEN",
                           "descricao": "Aprovado o PL 1/2026", "aprovacao": 1}], "links": []}
    if url.endswith("/votos"):
        return {"dados": [{"tipoVoto": "Sim", "deputado_": {"id": 1, "nome": "Fulana Silva", "siglaPartido": "ABC", "siglaUf": "SP"}},
                          {"tipoVoto": "Não", "deputado_": {"id": 2, "nome": "Beltrano Souza", "siglaPartido": "XYZ", "siglaUf": "BA"}}]}
    if "/despesas" in url:
        return {"dados": [{"ano": 2026, "mes": 3, "tipoDespesa": "COMBUSTÍVEIS", "codDocumento": 99,
                           "valorLiquido": 250.5, "nomeFornecedor": "Posto X"}], "links": []}
    if "senador/lista/atual" in url:
        return {"ListaParlamentarEmExercicio": {"Parlamentares": {"Parlamentar": {
            "IdentificacaoParlamentar": {"CodigoParlamentar": "5000", "NomeParlamentar": "Senadora Y",
                                         "SiglaPartidoParlamentar": "ABC", "UfParlamentar": "RJ"}}}}}
    if "plenario/lista/votacao" in url:
        return {"ListaVotacoes": {"Votacoes": {"Votacao": [{
            "CodigoSessaoVotacao": "777", "DataSessao": "2026-09-15", "SiglaMateria": "PEC",
            "NumeroMateria": "8", "AnoMateria": "2026", "Resultado": "Aprovada",
            "Votos": {"VotoParlamentar": [{"CodigoParlamentar": "5000", "NomeParlamentar": "Senadora Y",
                                           "SiglaPartido": "ABC", "SiglaUF": "RJ", "SiglaVoto": "Sim"}]}}]}}}
    if "agregados" in url:
        return [{"unidade": "Pessoas", "resultados": [{"series": [
            {"localidade": {"id": "35"}, "serie": {"2025": "46000000"}}]}]}]
    raise AssertionError(f"URL inesperada: {url}")


def test_coleta_e_api(monkeypatch):
    monkeypatch.setattr(http, "get_json", falso_get_json)
    assert camara.coletar_deputados() == 2
    assert camara.coletar_votacoes(date(2026, 9, 1), date(2026, 9, 30)) == 1
    assert camara.coletar_despesas(2026) == 2
    assert senado.coletar_senadores() == 1
    assert senado.coletar_votacoes(date(2026, 9, 1), date(2026, 9, 30)) == 1
    assert ibge.coletar_indicadores() >= 1

    r = cliente.get("/parlamentares", params={"casa": "camara"}).json()
    assert r["total"] == 2
    vid = cliente.get("/votacoes", params={"casa": "camara"}).json()["itens"][0]["id"]
    det = cliente.get(f"/votacoes/{vid}").json()
    assert det["placar"] == {"Sim": 1, "Não": 1}
    pid = r["itens"][1]["id"]  # Fulana (ordem alfabética)
    perfil = cliente.get(f"/parlamentares/{pid}").json()
    assert perfil["total_gasto"] == 250.5
    resumo = cliente.get("/estados/SP/resumo").json()
    assert resumo["indicadores"]["populacao"]["valor"] == 46000000
    assert cliente.get("/coletas").json()[0]["status"] == "ok"
    # coleta idempotente: rodar de novo não duplica
    camara.coletar_deputados()
    assert cliente.get("/parlamentares", params={"casa": "camara"}).json()["total"] == 2


def test_registros_e_tarefas():
    assert cliente.get("/registros", params={"fonte": "ibge", "uf": "sp"}).json()["total"] >= 1
    assert "camara-votacoes" in cliente.get("/coletas/tarefas").json()
    assert cliente.post("/coletas/camara-deputados", headers={"x-admin-token": "errado"}).status_code in (401, 403)


def test_site_servido_na_raiz():
    from fastapi.testclient import TestClient
    from app.main import app
    r = TestClient(app).get("/")
    assert r.status_code == 200
    assert "BRASIL+" in r.text and "detectarAPI" in r.text
