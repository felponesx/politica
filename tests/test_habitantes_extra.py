"""Interiorização (Censo 2010→2022), depressão (PNS 2013) e trabalho por aplicativo (PNAD 2025): cálculo e rota."""
from fastapi.testclient import TestClient

from app import habitantes
from app.main import app
from scripts import habitantes_extra as he


def test_faixa_pelo_tamanho_de_2010():
    assert he._faixa(5_000) == "ate_20k" and he._faixa(20_000) == "ate_20k"
    assert he._faixa(20_001) == "de_20_100k" and he._faixa(100_000) == "de_20_100k"
    assert he._faixa(100_001) == "de_100_500k" and he._faixa(500_000) == "de_100_500k"
    assert he._faixa(500_001) == "acima_500k"


def test_crescimento_por_faixa_e_sem_dado_nao_vira_zero():
    p2010 = [{"D1C": "3550308", "V": "600000"}, {"D1C": "3500001", "V": "10000"}, {"D1C": "3500002", "V": "-"}]
    p2022 = [{"D1C": "3550308", "V": "660000"}, {"D1C": "3500001", "V": "11000"}, {"D1C": "3500002", "V": "9000"}]
    d = he.crescimento(p2010, p2022)
    assert d["SP"]["acima_500k"]["variacao_pct"] == 10.0                  # 600 mil → 660 mil
    assert d["SP"]["ate_20k"]["municipios"] == 1                          # o município sem dado em 2010 não entra
    assert d["BR"]["acima_500k"]["pop2022"] == 660_000


def test_depressao_so_com_valor_publicado_e_sem_porcentagem_quando_nao_ha_total():
    linhas = [{"D1C": "1", "D4C": "33055", "V": "11063.400"}, {"D1C": "1", "D4C": "33046", "V": "-"}]
    d = he.depressao(linhas)
    assert d["BR"]["depressao_mil"] == 11063.4 and d["BR"]["pct"] is None and d["BR"]["cronica_mil"] is None


def test_plataformas_separa_total_e_tipos_e_ignora_sem_dado():
    linhas = [{"D1C": "1", "D4C": "83215", "V": "1959"}, {"D1C": "1", "D4C": "83211", "V": "232"}, {"D1C": "1", "D4C": "83213", "V": "-"}]
    r = he.plataformas(linhas)
    assert r["total_mil"] == 1959 and r["por_tipo"] == {"Aplicativo de táxi": 232}


def test_rota_populacao_extra_com_o_arquivo_gerado():
    r = TestClient(app).get("/populacao/extra")
    if r.status_code == 404:
        return
    d = r.json()
    assert set(d) >= {"interiorizacao", "depressao", "plataformas"}
    assert "fonte" in d["interiorizacao"] and d["interiorizacao"]["metodo"]
    assert habitantes.extra() is not None
