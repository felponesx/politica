"""Crises e benefícios por estado (scripts/crises_pessoas.py): conversões do SIDRA, Gás do Povo sem dado pessoal e arquivo gerado."""
import json
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from app import habitantes
from app.main import app
from scripts import crises_pessoas as cp

ARQ = Path(__file__).resolve().parent.parent / "app" / "dados" / "crises_pessoas.json"


def _linha(sigla_cod, v, **campos):
    return {"D1C": sigla_cod, "V": v, **campos}


def test_sem_dado_do_sidra_vira_none_nunca_zero():
    assert cp._num("-") is None and cp._num("..") is None and cp._num("...") is None
    assert cp._num("7.6") == 7.6 and cp._num("1537837") == 1537837.0


def test_deficiencia_por_tipo_e_contagem_por_estado():
    tipo = [
        {"D1C": "11", "V": "7.1", "D2C": "13403", "D4C": "58771"},
        {"D1C": "11", "V": "4.2", "D2C": "13403", "D4C": "73771"},
        {"D1C": "11", "V": "65221", "D2C": "12785", "D4C": "73771"},
        {"D1C": "1", "V": "-", "D2C": "13403", "D4C": "73772"},   # sem dado não vira zero
    ]
    pop = [
        {"D1C": "11", "V": "1537837", "D2C": "11852", "D5C": "46583"},
        {"D1C": "11", "V": "108535", "D2C": "11852", "D5C": "58765"},
    ]
    r = cp.censo_deficiencia(tipo, pop)["valores"]
    assert r["RO"]["deficiencia_pct"] == 7.1
    assert r["RO"]["def_visual_pct"] == 4.2
    assert r["RO"]["def_visual_n"] == 65221
    assert r["RO"]["pessoas_2mais"] == 1537837 and r["RO"]["com_deficiencia"] == 108535
    assert "def_auditiva_pct" not in r.get("BR", {})


def test_depressao_com_dois_anos_separados_e_remedio():
    d13 = [{"D1C": "1", "V": "7.6", "D2C": "4642", "D4C": "6794", "D5C": "6795", "D3C": "2013"}]
    d19 = [{"D1C": "1", "V": "10.2", "D2C": "4642", "D4C": "6794", "D5C": "6795", "D3C": "2019"}]
    med = [{"D1C": "1", "V": "48.0", "D2C": "11157", "D4C": "6794", "D5C": "6795", "D3C": "2019"}]
    r = cp.pns_depressao(d13, d19, [], [], med)
    assert r["valores"]["BR"] == {"depressao_prof_2013_pct": 7.6, "depressao_prof_2019_pct": 10.2,
                                  "depressao_remedio_2019_pct": 48.0}
    assert r["periodos"]["BR"]["depressao_prof_2019_pct"] == "2019"


def test_bolsa_familia_usa_mil_domicilios_e_nao_a_linha_de_distribuicao():
    dom = [
        {"D1C": "1", "V": "13638", "MN": "Mil unidades", "D2N": "2025",
         "D3N": "Domicílios em que algum morador do domicílio recebeu rendimento do Programa Bolsa Família"},
        {"D1C": "1", "V": "100.0", "MN": "%", "D2N": "2025",
         "D3N": "Percentual dos domicílios em que algum morador do domicílio recebeu rendimento do Programa Bolsa Família"},
    ]
    pes = [{"D1C": "1", "V": "35866", "MN": "Mil pessoas", "D2N": "2025",
            "D3N": "Pessoas de 10 anos ou mais de idade cujo domicílio possui algum morador que recebeu rendimento do Programa Bolsa Família"}]
    r = cp.pnad_bolsa(dom, pes)["valores"]["BR"]
    assert r == {"bolsa_domicilios_mil": 13638.0, "bolsa_pessoas_mil": 35866.0}


def test_analfabetismo_e_100_menos_a_taxa_de_alfabetizacao():
    linhas = [{"D1C": "11", "V": "93.55", "D2N": "2022",
               "D3N": "Taxa de alfabetização das pessoas de 15 anos ou mais de idade", "D4N": "Total", "D5N": "Total"}]
    assert cp.alfabetizacao(linhas)["valores"]["RO"]["analfabetismo_pct"] == 6.45


def test_gas_do_povo_so_soma_totais_e_nao_guarda_cpf_nem_nome(tmp_path):
    cab = "MÊS REFERÊNCIA;UF;CÓDIGO MUNICÍPIO SIAFI;NOME MUNICÍPIO;CPF BENEFICIÁRIO;NOME FAVORECIDO;CNPJ ESTABELECIMENTO;ESTABELECIMENTO;QUANTIDADE DE PESSOAS NA FAMÍLIA;PERÍODO VALIDADE VALE (meses);DATA INÍCIO VIGÊNCIA VALE;DATA FIM VIGÊNCIA VALE;DATA RETIRADA VALE;VALOR BENEFÍCIO"
    corpo = [
        "202609;AC;0643;ACRELANDIA;***.833.642-**;FULANA DE TAL;43403957000191;GRC GAS LTDA;3;3;10/09/2026;09/12/2026;28/09/2026;123,16",
        "202609;AC;0643;ACRELANDIA;***.037.612-**;BELTRANA DA SILVA;56877653000108;DISTRIBUIDORA;2;3;10/09/2026;09/12/2026;07/10/2026;123,16",
        "202609;SP;3550308;SAO PAULO;***.000.000-**;CICLANA;NULO;ESTAB;1;3;10/09/2026;09/12/2026;;123,16",
    ]
    arq = tmp_path / "gas.zip"
    with zipfile.ZipFile(arq, "w") as z:
        z.writestr("202609_GasdoPovo.csv", "\n".join([cab] + corpo).encode("latin-1"))   # o Portal publica em latin-1
    r = cp.gas_do_povo(arq)
    assert r["mes"] == "202609" and r["linhas"] == 3
    assert r["valores"]["AC"]["gas_familias"] == 2 and r["valores"]["AC"]["gas_pessoas"] == 5
    assert r["valores"]["AC"]["gas_valor_mi"] == round(246.32 / 1e6, 2)
    assert r["valores"]["SP"]["gas_familias"] == 1
    texto = json.dumps(r, ensure_ascii=False)
    for proibido in ("FULANA", "BELTRANA", "CICLANA", "***", "GRC", "DISTRIBUIDORA", "CPF", "NOME"):
        assert proibido not in texto


def test_arquivo_gerado_tem_so_numeros_e_fontes_com_link():
    d = json.loads(ARQ.read_text(encoding="utf-8"))
    assert d["falhas"] == [] or isinstance(d["falhas"], list)
    for sigla, metricas in d["uf"].items():
        assert sigla == "BR" or sigla in cp.SIGLA.values()
        for chave, valor in metricas.items():
            assert valor is None or isinstance(valor, (int, float)), (sigla, chave)
    for chave in ("depressao", "autismo", "deficiencia", "nem_nem", "bolsa", "gas", "analfabetismo"):
        assert chave in d["fontes"] and d["fontes"][chave]["link"].startswith("https://")
    assert d["uf"]["BR"]["depressao_prof_2019_pct"] == 10.2       # PNS 2019 (boletim do MDH cita o mesmo número)
    assert d["uf"]["BR"]["depressao_prof_2013_pct"] == 7.6
    assert d["uf"]["BR"]["com_deficiencia"] > 14_000_000          # Censo 2022 (IBGE publica 14,4 milhões)


def test_populacao_extra_traz_as_crises():
    dado = habitantes.extra()
    if dado is None:
        return
    assert "crises" in dado and dado["crises"]["uf"]["BR"]["nem_nem_pct"] == 16.1
    r = TestClient(app).get("/populacao/extra")
    if r.status_code == 404:
        return
    assert r.status_code == 200 and "crises" in r.json()
