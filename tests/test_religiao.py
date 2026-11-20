"""Religião por estado (scripts/religiao.py, app/religiao.py): cálculo com linhas de exemplo e a rota que serve o arquivo."""
import json

from fastapi.testclient import TestClient

from app import populacao, religiao as app_religiao
from app.main import app
from scripts import religiao as coletor


def _censo(uf, nome, cats, total):
    linhas = [{"D1C": uf, "D1N": nome, "D4N": "Total", "D5N": "Total", "D6N": "Total", "V": str(total)}]
    for rel, v in cats.items():
        linhas.append({"D1C": uf, "D1N": nome, "D4N": rel, "D5N": "Total", "D6N": "Total", "V": str(v)})
        # sexo e idade diferentes do Total não podem entrar no cálculo
        linhas.append({"D1C": uf, "D1N": nome, "D4N": rel, "D5N": "Homens", "D6N": "Total", "V": str(v + 999)})
        linhas.append({"D1C": uf, "D1N": nome, "D4N": rel, "D5N": "Total", "D6N": "10 a 14 anos", "V": str(v + 999)})
    return linhas


def _igrejas(uf, ano, n, codigo=coletor.CODIGO_RELIGIOSAS):
    return [{"D1C": uf, "D1N": "x", "D3N": str(ano), "V": str(n), "D4C": codigo},
            {"D1C": uf, "D1N": "x", "D3N": str(ano), "V": "7", "D4C": "999"}]   # outra atividade: fora


def test_calcula_so_total_de_sexo_e_idade_e_guarda_so_a_atividade_religiosa():
    censo = _censo("35", "São Paulo", {"Católica Apostólica Romana": 600, "Sem religião": 400}, 1000)
    unid = _igrejas("35", 2022, 50) + _igrejas("35", 2023, 55) + [{"D1C": "1", "D1N": "Brasil", "D3N": "2022", "V": "50", "D4C": coletor.CODIGO_RELIGIOSAS}]
    d = coletor.calcular(censo, unid)
    sp = d["estados"]["SP"]
    assert sp["total"] == 1000 and sp["categorias"] == {"catolica": 600, "sem_religiao": 400}
    assert sp["igrejas"] == {"2022": 50, "2023": 55}
    assert d["brasil"]["igrejas"] == {"2022": 50}
    assert d["brasil"]["categorias"]["catolica"] == 600


def test_percentuais_e_organizacoes_por_100_mil(tmp_path, monkeypatch):
    arq = tmp_path / "religiao.json"
    arq.write_text(json.dumps({
        "fonte": "f", "link": "l", "metodo": "m", "gerado_em": "2026-01-01", "censo_ano": 2022, "base": "b",
        "brasil": {"total": 200, "categorias": {"catolica": 100, "sem_religiao": 100}, "igrejas": {"2022": 40}},
        "estados": {"SP": {"nome": "São Paulo", "total": 200, "categorias": {"catolica": 100, "sem_religiao": 100},
                           "igrejas": {"2022": 40}}}}), encoding="utf-8")
    monkeypatch.setattr(app_religiao, "ARQUIVO", arq)
    monkeypatch.setattr(populacao, "censo", lambda: {"brasil": {"total": 200_000}, "estados": {"SP": {"total": 100_000}}})
    d = app_religiao.religiao()
    assert d["estados"]["SP"]["pct"]["catolica"] == 50.0
    assert d["estados"]["SP"]["igrejas"]["por_100mil_hab"] == 40.0          # 40 em 100 mil moradores
    assert d["brasil"]["igrejas"]["por_100mil_hab"] == 20.0
    assert d["varias_religioes"]["medido"] is False


def test_rota_religiao_com_o_arquivo_gerado():
    r = TestClient(app).get("/religiao")
    if r.status_code == 404:
        return
    d = r.json()
    assert d["censo_ano"] == 2022 and len(d["estados"]) == 27
    assert d["varias_religioes"]["medido"] is False
    assert 0 < d["brasil"]["pct"]["catolica"] < 100
