"""População: porcentagens do Censo (app/populacao.py), rotas /populacao e /sobrenomes e a busca de origem de sobrenomes
(app/sobrenomes.py) com respostas simuladas da Wikipédia (sem rede)."""
import json
from urllib.parse import unquote

from fastapi.testclient import TestClient

from app import populacao, sobrenomes
from app.main import app


class _Resp:
    def __init__(self, status, corpo=None):
        self.status_code = status
        self.headers = {}
        self._corpo = corpo or {}

    def json(self):
        return self._corpo


def test_porcentagens_de_uma_linha():
    d = {"total": 200, "indigena": 2, "branca": 100, "preta": 20, "parda": 60, "amarela": 10, "homens": 90, "mulheres": 110}
    l = populacao._linha("X", d)
    assert l["indigena_pct"] == 1.0
    assert l["pardos_pretos_pct"] == 40.0          # parda + preta
    assert l["mulheres_pct"] == 55.0
    assert populacao._pct(None, 200) is None and populacao._pct(5, 0) is None


def test_siglas_cobrem_os_27_estados():
    assert len(populacao.SIGLA) == 27
    assert populacao.SIGLA["35"] == "SP" and populacao.SIGLA["53"] == "DF"


def test_censo_le_o_arquivo_e_troca_codigo_por_sigla(tmp_path, monkeypatch):
    arq = tmp_path / "pop.json"
    arq.write_text(json.dumps({
        "fonte": "f", "link": "l", "metodo": "m", "gerado_em": "2026-01-01", "ano": 2022,
        "brasil": {"total": 200, "branca": 100, "preta": 20, "parda": 60, "amarela": 10, "indigena": 2, "homens": 90, "mulheres": 110},
        "estados": {"35": {"nome": "São Paulo", "total": 200, "branca": 100, "preta": 20, "parda": 60, "amarela": 10, "indigena": 2,
                           "homens": 90, "mulheres": 110}}}), encoding="utf-8")
    monkeypatch.setattr(populacao, "ARQUIVO", arq)
    d = populacao.censo()
    assert set(d["estados"]) == {"SP"} and d["estados"]["SP"]["nome"] == "São Paulo"
    assert d["brasil"]["indigena_pct"] == 1.0 and "não perguntou" not in d["aviso"] and "indígenas" in d["aviso"]


def test_censo_sem_arquivo_devolve_none(tmp_path, monkeypatch):
    monkeypatch.setattr(populacao, "ARQUIVO", tmp_path / "nao_existe.json")
    assert populacao.censo() is None


def test_rota_populacao_com_o_arquivo_gerado():
    r = TestClient(app).get("/populacao")
    assert r.status_code == 200
    d = r.json()
    assert d["ano"] == 2022 and "SP" in d["estados"] and len(d["estados"]) == 27
    assert d["brasil"]["total"] > 200_000_000
    assert 0 < d["brasil"]["indigena_pct"] < 2


def test_titulos_procurados_na_wikipedia():
    assert sobrenomes._titulos("Silva") == ["Silva (sobrenome)", "Silva (família)", "Silva"]


def test_origem_pega_a_pagina_de_sobrenome(monkeypatch):
    respostas = {
        "Freire_(sobrenome)": _Resp(404),
        "Freire_(família)": _Resp(404),
        "Freire": _Resp(200, {"type": "standard", "title": "Freire", "extract": "Freire é um sobrenome português, apelido de família originário da Galiza."}),
    }
    monkeypatch.setattr(sobrenomes, "_pedir", lambda cli, url: respostas[unquote(url.rsplit("/", 1)[1])])
    d = sobrenomes.origem("Freire")
    assert d["titulo"] == "Freire" and "Galiza" in d["resumo"] and d["licenca"] == "CC BY-SA 4.0"


def test_origem_ignora_desambiguacao_e_pagina_sem_tema(monkeypatch):
    respostas = {
        "Barros_(sobrenome)": _Resp(200, {"type": "disambiguation", "extract": "Barros pode ser"}),
        "Barros_(família)": _Resp(404),
        "Barros": _Resp(200, {"type": "standard", "extract": "Barros é um município do Piauí."}),
    }
    monkeypatch.setattr(sobrenomes, "_pedir", lambda cli, url: respostas[unquote(url.rsplit("/", 1)[1])])
    try:
        sobrenomes.origem("Barros")
        assert False, "não deveria achar origem"
    except sobrenomes.SemOrigem:
        pass


def test_nome_invalido_nao_vai_para_a_rede():
    try:
        sobrenomes.origem("Sil va 2")
        assert False
    except ValueError:
        pass


def test_rota_sobrenomes_trata_erros(monkeypatch):
    cli = TestClient(app)
    assert cli.get("/sobrenomes", params={"nome": "a"}).status_code == 422

    def sem(nome):
        raise sobrenomes.SemOrigem(nome)
    monkeypatch.setattr(sobrenomes, "origem", sem)
    r = cli.get("/sobrenomes", params={"nome": "Zzqwx"})
    assert r.status_code == 404 and "não tem uma origem" in r.json()["detail"]

    def fora(nome):
        raise sobrenomes.Indisponivel("x")
    monkeypatch.setattr(sobrenomes, "origem", fora)
    assert cli.get("/sobrenomes", params={"nome": "Zzqwy"}).status_code == 503
