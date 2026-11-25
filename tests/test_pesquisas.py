"""Aba Pesquisas: coletor (scripts/pesquisas.py, com planilhas sintéticas, sem internet) e API (app/pesquisas.py)."""
import io
from datetime import datetime

import openpyxl
from fastapi.testclient import TestClient

from app.main import app
from scripts import pesquisas as pq


def xlsx(cab, linhas) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(cab)
    for r in linhas:
        ws.append(r)
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


CAB_P = ["ano", "processo", "coordenador", "modalidade", "chamada_num", "chamada_desc", "grupochamada", "linha", "titulo", "area", "camaraavaliacao", "valorcontratado",
         "instituicaoexecutora_sigla", "instituicaoexecutora_nome", "instituicaogestora_sigla", "instituicaogestora_nome", "data_inicio", "data_termino", "datadisponibilizacao"]
CAB_I = ["identificador", "nome_instituicao", "estado", "lct", "situacao", "tipo_instituicao", "datadisponibilizacao"]
D = datetime(2026, 6, 1)


def fapemig():
    projs = [
        [2020, "APQ-1", "MARIA DA SILVA", "APOIO PARA PROJETOS DE PESQUISA", "#1", "UNIVERSAL", "U", "PESQUISA", "ESTUDO DE ALGO", "FÍSICA ", None, 1000.5,
         "UFMG", "UNIVERSIDADE FEDERAL DE MINAS GERAIS", "FUNDEP", "FUNDAÇÃO DE DESENVOLVIMENTO DA PESQUISA", datetime(2020, 5, 1), datetime(2022, 5, 1), D],
        [2020, "APQ-1", "REPETIDO", "X", "#1", "U", "U", "P", "REPETIDO", "FÍSICA", None, 5, "UFMG", "UNIVERSIDADE FEDERAL DE MINAS GERAIS", None, None, None, None, D],
        [2015, "TCT-9", "ALGUÉM", "TERMO", "#2", "T", "T", "P", "PROGRAMA DA FAPEMIG", None, None, 70000000, "SEDE", "FAPEMIG SEDE", "NPG", "ESTE PROCESSO NÃO POSSUI GESTORA", None, None, D],
        ["RBE", "APQ-3", "JOÃO", "APOIO PARA PROJETOS DE PESQUISA", "#3", "U", "U", "PESQUISA", None, "QUÍMICA", None, None, "UFV", "UNIVERSIDADE FEDERAL DE VIÇOSA", None, None, None, None, D],
    ]
    inst = [[1, "UNIVERSIDADE FEDERAL DE MINAS GERAIS", "MINAS GERAIS", "SIM", "ATIVA", "PÚBLICA FEDERAL", D],
            [2, "UNIVERSIDADE FEDERAL DE VIÇOSA", "MINAS GERAIS", "SIM", "ATIVA", "PÚBLICA FEDERAL", D],
            [3, "FAPEMIG SEDE", "MINAS GERAIS", "NÃO", "ATIVA", "PÚBLICA ESTADUAL", D]]
    return xlsx(CAB_P, projs), xlsx(CAB_I, inst)


def int_arq(linhas):
    return xlsx(["N.", "Título do Projeto", "Descrição do Projeto", "Data de Assinatura do Contrato", "Valor Pactuado (R$)", "Nome do Cliente/Razão Social"], linhas)


def montar():
    p, i = fapemig()
    a = int_arq([[1, "Projeto A", "desc", "01/12/2025", 1000, "CLIENTE UM"], [2, "Bolsa", "d", "01/09/2025", 8400, "CLIENTE DOIS"], [3, "Bolsa", "d", "01/09/2025", 8400, "CLIENTE DOIS"]])
    b = int_arq([[1, "Projeto A", "desc", "01/12/2025", 1000, "CLIENTE UM"]])     # o mesmo contrato listado em outro arquivo
    return pq.montar(p, i, [(2025, "governo", "u1", a), (2024, "governo", "u2", b)], hoje="2026-11-25")


def test_fapemig_um_registro_por_processo_e_campos_da_fonte():
    d = montar()
    f = [p for p in d["p"] if p[0] == 0]
    assert len(f) == 3                                      # APQ-1 (o repetido some), TCT-9 e APQ-3
    p1 = next(p for p in f if p[2] == "APQ-1")
    assert p1[3] == "ESTUDO DE ALGO" and p1[4] == "Maria da Silva" and p1[10] == 1000.5
    assert d["inst"][p1[5]][:3] == ["Universidade Federal de Minas Gerais", "UFMG", "MG"]      # estado vem do cadastro da própria fonte
    assert d["areas"][p1[7]] == "Física"
    assert p1[11] == "2020-05-01" and p1[12] == "2022-05-01"
    assert d["fontes"][0]["tipo_valor"] == "contratado" and d["fontes"][0]["descartadas"]["repetido"] == 1


def test_sede_da_fapemig_fica_marcada_e_ano_invalido_vira_nulo():
    d = montar()
    sede = next(p for p in d["p"] if p[2] == "TCT-9")
    assert sede[13] == 1 and sede[6] is None                # "ESTE PROCESSO NÃO POSSUI GESTORA" não vira instituição gestora
    rbe = next(p for p in d["p"] if p[2] == "APQ-3")
    assert rbe[1] is None and rbe[10] is None               # ano "RBE" e valor vazio: nulos, nunca zero


def test_int_une_so_entre_arquivos_diferentes():
    d = montar()
    i = [p for p in d["p"] if p[0] == 1]
    assert len(i) == 3                                       # "Projeto A" unido entre os dois arquivos; as duas "Bolsa" do MESMO arquivo ficam separadas
    a = next(p for p in i if p[3] == "Projeto A")
    assert a[14]["listado_em"] == [2025, 2024] and a[14]["cliente"] == "Cliente Um" and a[4] is None
    assert d["inst"][a[5]][:3] == ["Instituto Nacional de Tecnologia", "INT", "RJ"]
    assert d["fontes"][1]["tipo_valor"] == "pactuado"


def test_api_com_os_dados_gerados():
    c = TestClient(app)
    r = c.get("/pesquisas/resumo")
    if r.status_code == 404:
        return                                               # arquivo ainda não gerado
    j = r.json()
    assert j["projetos"] > 20000 and "aviso" in j
    # tipos de valor nunca se misturam: cada fonte diz o seu
    assert {f["id"]: f["tipo_valor"] for f in j["fontes"]} == {"fapemig": "contratado", "int": "pactuado"}
    lista = c.get("/pesquisas", params={"q": "nanoestruturas", "limite": 3}).json()
    assert lista["total"] > 0 and len(lista["projetos"]) <= 3
    p = lista["projetos"][0]
    assert p["tipo_valor"] == "contratado" and p["instituicao"]["nome"]
    assert c.get(f"/pesquisas/projeto/{p['id']}").json()["fonte_info"]["url"].startswith("https://")
    assert c.get("/pesquisas/projeto/99999999").status_code == 404
    inst = c.get("/pesquisas/instituicoes", params={"uf": "MG"}).json()
    assert inst["total"] > 100 and inst["instituicoes"][0]["valor"] >= inst["instituicoes"][1]["valor"]
    f = c.get(f"/pesquisas/instituicao/{inst['instituicoes'][0]['id']}").json()
    assert f["projetos"] > 0 and f["por_ano"] and f["maiores"]


def test_projetos_institucionais_ficam_fora_dos_rankings():
    c = TestClient(app)
    j = c.get("/pesquisas/resumo").json() if c.get("/pesquisas/resumo").status_code == 200 else None
    if not j:
        return
    fap = next(f for f in j["fontes"] if f["id"] == "fapemig")
    assert fap["institucional_n"] > 0                        # SEDE existe e é contada à parte
    sede = c.get("/pesquisas", params={"institucional": "true", "limite": 1}).json()
    assert sede["total"] == fap["institucional_n"] and sede["projetos"][0]["institucional"] is True
