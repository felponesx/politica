"""Plantas e fungos ameaçados (scripts/flora_ameacada.py) com listas pequenas e a rota que serve o arquivo gerado."""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from scripts import flora_ameacada as fa

FLORA = ("Nº;#;Família;Espécie ou Subespécie/Variedade;Categoria de Risco\n"
         "1; ;Fabaceae;Dalbergia nigra;CR\n"
         "2; ;Arecaceae;Euterpe edulis;EN\n"
         "3; ;Myrtaceae;Planta sem dado;VU\n"
         "4; ;Myrtaceae;Especie inventada;XX\n")
FUNGOS = "Nº;Ordem/Família;Espécie;Categoria de risco\n1;Agaricales;Amanita viscidolutea;VU\n"
LISTA2020 = ("Fauna/Flora;Grupo;Família;Espécie (Simplificado);Nome Comum;Categoria de Ameaça;Sigla Categoria de Ameaça;Bioma;"
             "Principais Ameaças;Presença em Áreas Protegidas;Plano de Ação Nacional para Conservação (PAN);Ordenamento Pesqueiro;"
             "Estados de Ocorrência;Espécie exclusiva do Brasil\n"
             "Flora;Angiospermas;Fabaceae;Dalbergia nigra;Jacarandá-da-bahia;Em Perigo;EN;Mata Atlântica;Corte ilegal;;;;SP, RJ;Sim\n"
             "Fauna;Aves;Psittacidae;Ara ararauna;Arara;Vulnerável;VU;Cerrado;;;;;GO;Não\n")


def test_calcula_plantas_e_fungos_com_grupo_e_bioma_da_base_2020():
    d = fa.calcular(FLORA, FUNGOS, LISTA2020)
    por_nome = {e[0]: e for e in d["especies"]}
    assert d["totais"]["especies"] == 3 + 1          # a categoria desconhecida (XX) fica de fora
    assert "Especie inventada" not in por_nome
    dal = por_nome["Dalbergia nigra"]
    assert dal[1] == "Jacarandá-da-bahia" and dal[2] == "Plantas" and dal[3] == "Angiospermas" and dal[5] == "CR"
    assert dal[6] == [fa.BIOMAS.index("Mata Atlântica")] and dal[7] == ["SP", "RJ"] and dal[9] == 1 and dal[10] == 1 and dal[11] == "mma"
    # sem a base de 2020: grupo "Não informado", sem bioma nem estado (nunca estimado)
    semdado = por_nome["Planta sem dado"]
    assert semdado[3] == fa.SEM_GRUPO and semdado[6] == [] and semdado[10] == 0
    # fungo: grupo "Fungos", ordem vai na família, sem bioma
    fun = por_nome["Amanita viscidolutea"]
    assert fun[2] == "Fungos" and fun[3] == "Fungos" and fun[4] == "Agaricales" and fun[5] == "VU" and fun[6] == []
    t = d["totais"]
    assert t["por_tipo"] == {"Plantas": 3, "Fungos": 1}
    assert t["por_categoria"] == {"CR": 1, "EN": 1, "VU": 2}
    assert t["com_dados_2020"] == 1 and t["com_bioma"] == 1


def test_gbif_so_entra_quando_a_base_nao_tem_o_nome():
    d = fa.calcular(FLORA, FUNGOS, LISTA2020, gbif={"Euterpe edulis": "Juçara", "Dalbergia nigra": "Outro nome"})
    por_nome = {e[0]: e for e in d["especies"]}
    assert por_nome["Euterpe edulis"][1] == "Juçara" and por_nome["Euterpe edulis"][11] == "gbif"
    assert por_nome["Dalbergia nigra"][1] == "Jacarandá-da-bahia" and por_nome["Dalbergia nigra"][11] == "mma"


def test_coluna_que_falta_e_erro_e_nao_lista_vazia():
    with pytest.raises(SystemExit):
        fa._lista_oficial(fa._linhas("Nº;Família;Espécie\n1;X;Y\n"), "Plantas")


def test_rota_plantas_com_o_arquivo_gerado():
    r = TestClient(app).get("/ambiente/plantas")
    if r.status_code == 404:
        return
    d = r.json()
    assert "MMA" in d["fonte"] and d["campos"][0] == "nome_cientifico"
    for e in d["especies"][:200]:
        assert e[2] in ("Plantas", "Fungos") and e[5] in d["categorias"]
