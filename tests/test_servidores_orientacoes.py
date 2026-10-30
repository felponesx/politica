import io
import zipfile

from app.collectors import orientacoes, servidores
from app import orientacao


def _zip():
    cad = ('"Id_SERVIDOR_PORTAL";"NOME";"COD_ORG_EXERCICIO";"ORG_EXERCICIO";"ORGSUP_EXERCICIO";"UF_EXERCICIO"\n'
           '"1";"A";"26405";"Instituto X";"MEC";"CE"\n"2";"B";"26405";"Instituto X";"MEC";"CE"\n"3";"C";"25000";"Saúde";"Saúde";"SP"\n')
    rem = ('"ANO";"MES";"Id_SERVIDOR_PORTAL";"REMUNERAÇÃO BÁSICA BRUTA (R$)";"ABATE-TETO (R$)";"REMUNERAÇÃO APÓS DEDUÇÕES OBRIGATÓRIAS (R$)"\n'
           '"2026";"08";"1";"10.000,50";"0,00";"8.000,00"\n"2026";"08";"2";"50.000,00";"-3.633,81";"40.000,00"\n"2026";"08";"3";"5.000,00";"0,00";"4.000,00"\n')
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("202608_Cadastro.csv", cad.encode("latin-1"))
        z.writestr("202608_Remuneracao.csv", rem.encode("latin-1"))
    return zipfile.ZipFile(io.BytesIO(b.getvalue()))


def test_servidores_liga_cadastro_e_remuneracao_sem_dado_pessoal():
    d = servidores.resumir(servidores.agregar(_zip()), "202608")
    assert d["servidores"] == 3 and d["sem_cadastro"] == 0
    x = next(o for o in d["orgaos"] if o["codigo"] == "26405")
    assert x["n"] == 2 and x["bruta"] == 60000.5 and x["acima_teto"] == 1 and x["cortados_pelo_teto"] == 1 and x["abate_teto"] == -3633.81
    assert d["ufs"]["SP"]["n"] == 1
    assert "NOME" not in str(d) and '"A"' not in str(d)


def test_orientacoes_agrupa_por_votacao_e_mantem_vazio_como_sem_orientacao():
    g = orientacoes.agrupar([{"idVotacao": "1-2", "siglaBancada": "PL", "orientacao": "Sim", "siglaOrgao": "PLEN"},
                             {"idVotacao": "1-2", "siglaBancada": "PT", "orientacao": ""}, {"idVotacao": "", "siglaBancada": "X"}])
    assert list(g) == ["1-2"] and g["1-2"]["bancadas"] == {"PL": "Sim", "PT": ""}
    assert orientacao._chave("Podemos") == "PODE" and orientacao._voto("Não") == "Não"


def test_prf_descobre_links_pelo_titulo_sem_ligar_nada_a_mao():
    from app.collectors import prf
    pagina = ('Documento CSV de Acidentes 2025 (Agrupados por ocorrência) <a href="https://drive.google.com/file/d/AAA/view?usp=sharing/download">Baixar planilha</a>'
              'Documento CSV de Acidentes 2025 (Agrupados por pessoa) <a href="https://drive.google.com/file/d/BBB/view">Baixar planilha</a>'
              'Documento CSV de Acidentes 2024 (Agrupados por ocorrência) <a href="https://drive.google.com/file/d/CCC/view">Baixar planilha</a>')
    assert prf.descobrir(pagina) == {2025: "AAA", 2024: "CCC"}


def test_igc_acha_abas_e_link_do_ano():
    from app.collectors import inep_igc
    assert inep_igc.abas('<a data-id="2023"></a><a data-id="2025"></a>') == [2025, 2023]
    assert inep_igc.link_igc('<a href="https://download.inep.gov.br/x/2023/IGC_2023.xlsx">a</a><a href="https://download.inep.gov.br/x/2023/CPC_2023.xlsx">b</a>', 2023).endswith("IGC_2023.xlsx")
    assert inep_igc.link_igc('<a href="https://download.inep.gov.br/x/conceito_enade_2025.xlsx">a</a>', 2025) is None
