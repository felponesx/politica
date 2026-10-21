from app import policias
from app.collectors import isp_rj

CSV = ('"cisp";"mes";"ano";"mes_ano";"aisp";"risp";"munic";"hom_por_interv_policial";"apf";"cmp";"pol_militares_mortos_serv";'
       '"pol_civis_mortos_serv";"letalidade_violenta";"hom_doloso"\n'
       '"5";"12";"2024";"2024m12";"5";"1";"Rio de Janeiro";"2";"30";"10";"1";"0";"9";"6"\n'
       '"5";"1";"2025";"2025m01";"5";"1";"Rio de Janeiro";"1";"20";"5";"0";"0";"4";"3"\n'
       '"6";"1";"2025";"2025m01";"5";"1";"Rio de Janeiro";"3";"";"7";"0";"1";"5";"2"\n'
       '"7";"1";"2025";"2025m01";"13";"1";"Niterói";"0";"4";"1";"0";"0";"1";"1"\n')


def test_isp_agrega_por_aisp_e_ano():
    por = isp_rj.agregar(CSV)
    a5 = por["5"]
    assert a5["anos"]["2025"]["mortes_intervencao"] == 4
    assert a5["anos"]["2025"]["prisoes_flagrante"] == 20 and a5["anos"]["2025"]["mandados_cumpridos"] == 12
    assert a5["anos"]["2024"]["pms_mortos_servico"] == 1
    assert a5["cisps"] == ["5", "6"] and a5["ultimo_mes"] == "2025-01"
    assert a5["anos"]["2025"]["meses"] == 1  # ano incompleto


def test_batalhoes_rj_soma_e_marca_area_sem_dados():
    por = isp_rj.agregar(CSV)
    por["13"]["anos"] = {"2010": por["13"]["anos"]["2025"]}  # área antiga
    b = policias.batalhoes_rj(por)
    assert b["ano_ref"] in ("2024", "2025")
    a5 = next(x for x in b["batalhoes"] if x["aisp"] == 5)
    assert a5["mortes_intervencao_total"] == 6 and a5["pms_mortos_servico_total"] == 1
    assert a5["anos"]["2025"] == [4, 32, 0]
    assert not next(x for x in b["batalhoes"] if x["aisp"] == 13)["ativa"]
    assert b["serie"]["2024"]["mortes_intervencao"] == 2
    assert "não necessariamente pelo batalhão" in b["aviso"]


def test_ficha_descarta_o_que_nao_tem_fonte():
    f = policias._ficha({"chave": "u:SP:Águia", "nome": "Águia", "corp": "u",
                         "historia": [{"ano": "1984", "texto": "criado", "fonte": "https://pt.wikipedia.org/x"},
                                      {"ano": "1990", "texto": "sem fonte"}],
                         "patrono": {"nome": "Fulano", "texto": "x"},
                         "homenageados": [{"nome": "Beltrano", "fonte": "https://a.gov.br"}, {"nome": "", "fonte": "https://b"}],
                         "organizacao": {"texto": "x", "unidades_total": 5, "unidades": [{"nome": "Base 1", "local": "SP", "fonte": "ftp://x"}]},
                         "efetivo": {"valor": "muitos", "fonte": "https://c"}})
    assert f["slug"] == "u-SP-Aguia"
    assert [h["ano"] for h in f["historia"]] == ["1984"]
    assert f["patrono"] is None and [h["nome"] for h in f["homenageados"]] == ["Beltrano"]
    assert f["organizacao"] is None  # sem fonte e sem unidades com fonte
    assert f["efetivo"] is None


def test_arquivos_curados_validos():
    for s, f in policias.fichas().items():
        assert s == policias.slug(f["chave"])
        for h in f["historia"]:
            assert h["fonte"].startswith("http")
