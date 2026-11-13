import os

import pytest

from app import profissoes as P
from app import rais_leitor as L

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "rais_ni_2025_amostra.csv")


def _v(cbo, rem, faixa):
    return L.Vinculo(cbo, rem, 40, faixa)


def test_faixas_de_horas():
    assert P.faixa_de_horas(1) == "até 12 h"
    assert P.faixa_de_horas(6) == "41 a 44 h"
    assert P.faixa_de_horas(7) == "mais de 44 h"
    assert P.faixa_de_horas(8) is None


def test_media_min_max_e_quantis_nearest_rank():
    v = [_v("1234", 1000 + i, 5) for i in range(100)]
    r = P.resumir(v)["1234"]
    assert r["vinculos"] == 100
    assert r["minimo"] == 1000 and r["maximo"] == 1099
    assert r["media"] == pytest.approx(1049.5)
    assert r["p10"] == 1009
    assert r["p90"] == 1089


def test_faixas_com_percentual_de_pessoas():
    v = [_v("5678", 2000, 5)] * 40 + [_v("5678", 3000, 6)] * 60
    r = P.resumir(v)["5678"]
    por = {f["faixa"]: f for f in r["horas"]}
    assert por["31 a 40 h"]["pct"] == 40.0
    assert por["31 a 40 h"]["media"] == pytest.approx(2000)
    assert por["41 a 44 h"]["pct"] == 60.0
    assert por["41 a 44 h"]["media"] == pytest.approx(3000)


def test_amostra_pequena_nao_sai():
    v = [_v("9999", 1000, 5)] * (P.MINIMO_VINCULOS - 1)
    assert P.resumir(v) == {}


def test_leitor_le_o_arquivo_real_de_amostra():
    with open(FIXTURE, encoding="latin-1") as fh:
        linhas = list(L.ler_linhas(fh))
    # 7 linhas reais: uma está inativa em 31/12 (fica de fora); as outras 6 têm CBO, remuneração e faixa válidos
    assert len(linhas) == 6
    assert {v.cbo for v in linhas} == {"717020", "621005", "715505", "724315"}
    assert any(v.faixa_horas == 7 for v in linhas)  # faixa "mais de 44 h", presente em 2025
    seg = [v for v in linhas if v.cbo == "621005"][0]
    # "Vl Rem Média Nom" = 1711.25 (a coluna 1835.00 é "Vl Rem Dezembro Nom": o leitor lê pelo nome, não pela posição)
    assert seg.remuneracao == 1711.25
    assert seg.faixa_horas in (1, 2, 3, 4, 5, 6)


def test_leitor_descarta_ausentes_e_inativos():
    cab = "CBO 2002 Ocupação - Código,Vl Rem Média Nom,Qtd Hora Contr,Faixa Hora Contrat - Código,Ind Vínculo Ativo 31/12 - Código"
    linhas = [
        cab,
        '717020,1500.00,40,5,1',   # ok
        '999999,1500.00,40,5,1',   # CBO ausente
        '717020,,40,5,1',          # remuneração vazia
        '717020,1500.00,40,5,0',   # inativo em 31/12
        '717020,1500.00,40,9,1',   # faixa fora do oficial
        '717020,1500.00,40,5',     # linha quebrada
    ]
    out = list(L.ler_linhas(linhas))
    assert len(out) == 1 and out[0].cbo == "717020"


def test_layout_sem_coluna_falha_alto():
    with pytest.raises(L.LayoutInesperado):
        list(L.ler_linhas(["so;uma;coluna"]))


def test_ler_7z_extrai_e_le(tmp_path):
    py7zr = pytest.importorskip("py7zr")
    caminho = tmp_path / "RAIS_VINC_TESTE.7z"
    with open(FIXTURE, "rb") as fh:
        conteudo = fh.read()
    with py7zr.SevenZipFile(caminho, "w") as z:
        z.writestr(conteudo, "RAIS_VINC_TESTE.COMT")
    out = list(L.ler_7z(str(caminho)))
    assert len(out) == 6
