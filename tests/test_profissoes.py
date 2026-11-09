import pytest

from app import profissoes as P


def _gera(cbo, n, base, horas):
    # linhas sintéticas só para testar a conta (não são dados reais)
    return [(cbo, base + i, horas) for i in range(n)]


def test_faixa_de_horas_cobre_os_limites():
    assert P.faixa_de_horas(30) == "até 30 h"
    assert P.faixa_de_horas(31) == "31 a 36 h"
    assert P.faixa_de_horas(40) == "37 a 40 h"
    assert P.faixa_de_horas(44) == "41 a 44 h"
    assert P.faixa_de_horas(45) == "mais de 44 h"


def test_media_min_max_e_quantis_nearest_rank():
    v = _gera("1234", 100, 1000, 40)  # salários 1000..1099
    r = P.resumir(v)["1234"]
    assert r["vinculos"] == 100
    assert r["minimo"] == 1000 and r["maximo"] == 1099
    assert r["media"] == pytest.approx(1049.5)
    assert r["p10"] == 1009   # posição 10 de 100
    assert r["p90"] == 1089   # posição 90 de 100


def test_faixas_de_horas_com_percentual_de_pessoas():
    v = _gera("5678", 40, 2000, 40) + _gera("5678", 60, 3000, 44)
    r = P.resumir(v)["5678"]
    por = {f["faixa"]: f for f in r["horas"]}
    assert por["37 a 40 h"]["pct"] == 40.0
    assert por["37 a 40 h"]["media"] == pytest.approx(2019.5)
    assert por["41 a 44 h"]["pct"] == 60.0
    assert por["41 a 44 h"]["media"] == pytest.approx(3029.5)


def test_amostra_pequena_nao_sai_e_dado_invalido_e_descartado():
    v = _gera("9999", P.MINIMO_VINCULOS - 1, 1000, 40)
    v += [(None, 500, 40), ("1111", -5, 40)]
    assert P.resumir(v) == {}


def test_ranking_por_media():
    r = {}
    r.update(P.resumir(_gera("A", 30, 1000, 40)))
    r.update(P.resumir(_gera("B", 30, 5000, 40)))
    top = P.ranking(r, limite=1)
    assert top[0]["cbo"] == "B"
