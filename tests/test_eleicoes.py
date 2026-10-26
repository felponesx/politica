import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./teste.db")

import zipfile  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from app.collectors import tse_resultados  # noqa: E402
from app.db import criar_tabelas  # noqa: E402
from app.main import app  # noqa: E402

criar_tabelas()
cliente = TestClient(app)

CAB = "ANO_ELEICAO;NR_TURNO;SG_UF;SG_UE;NM_UE;CD_MUNICIPIO;NM_MUNICIPIO;NR_ZONA;DS_CARGO;SQ_CANDIDATO;NR_CANDIDATO;NM_URNA_CANDIDATO;SG_PARTIDO;QT_VOTOS_NOMINAIS;DS_SIT_TOT_TURNO\n"


def linhas(ano, dados):
    return CAB + "".join(f"{ano};1;BA;BA;BAHIA;{cd};{mun};1;GOVERNADOR;{sq};{nr};{nome};{p};{v};{sit}\n"
                         for cd, mun, sq, nr, nome, p, v, sit in dados)


def zipar(tmp, ano, texto):
    caminho = tmp / f"munzona_{ano}.zip"
    with zipfile.ZipFile(caminho, "w") as z:
        z.writestr(f"votacao_candidato_munzona_{ano}_BA.csv", texto.encode("latin-1"))
    return str(caminho)


def test_resultados(tmp_path):
    z22 = zipar(tmp_path, 2022, linhas(2022, [
        ("1", "SALVADOR", "1", "13", "Fulano", "AAA", 600, "NÃO ELEITO"),
        ("1", "SALVADOR", "2", "44", "Ciclana", "BBB", 400, "ELEITO"),
    ]))
    z26 = zipar(tmp_path, 2026, linhas(2026, [
        ("1", "SALVADOR", "3", "13", "Beltrano", "AAA", 700, "ELEITO"),
        ("2", "FEIRA", "3", "13", "Beltrano", "AAA", 100, "ELEITO"),
        ("2", "FEIRA", "4", "44", "Maria", "BBB", 200, "NÃO ELEITO"),
    ]))
    assert tse_resultados.coletar_resultados(2022, arquivo_local=z22) == 2
    assert tse_resultados.coletar_resultados(2026, arquivo_local=z26) == 2
    assert tse_resultados.coletar_resultados(2026, arquivo_local=z26) == 2  # idempotente

    r = cliente.get("/eleicoes/2026/ba", params={"cargo": "Governador"}).json()
    assert r["eleitos"][0]["nome"] == "Beltrano" and r["eleitos"][0]["votos"] == 800
    assert r["por_partido"]["AAA"]["percentual"] == 80.0
    comp = r["comparativo_eleicao_anterior"]["partidos"]["AAA"]
    assert comp["percentual_anterior"] == 60.0 and comp["variacao_pp"] == 20.0

    mapa = cliente.get("/eleicoes/2026/BA/mapa", params={"cargo": "governador"}).json()
    feira = next(m for m in mapa if m["municipio"] == "FEIRA")
    assert feira["vencedor"]["nome"] == "Maria"
    assert cliente.get("/eleicoes/anos").json() == [2026, 2022]
    assert cliente.get("/eleicoes/candidato/3").json()["turnos"][0]["votos"] == 800


CAB_BR = ("ANO_ELEICAO;NR_TURNO;SG_UF;SG_UE;NM_UE;CD_MUNICIPIO;NM_MUNICIPIO;NR_ZONA;DS_CARGO;SQ_CANDIDATO;"
          "NR_CANDIDATO;NM_URNA_CANDIDATO;SG_PARTIDO;QT_VOTOS_NOMINAIS;DS_SIT_TOT_TURNO\n")


def test_presidente_arquivo_br_nao_apaga_os_estados(tmp_path):
    """O arquivo _BR (Presidente) tem votos de todos os estados; ele vem no meio do zip (formato real de 2022/2026)
    e não pode apagar o governador que veio do arquivo do estado."""
    sp = CAB_BR + "2018;1;SP;SP;SÃO PAULO;71072;SÃO PAULO;1;Governador;901;45;DORIA;PSDB;600;2º TURNO\n"
    rj = CAB_BR + "2018;1;RJ;RJ;RIO DE JANEIRO;60011;RIO DE JANEIRO;1;Governador;902;20;WITZEL;PSC;500;2º TURNO\n"
    br = CAB_BR + "".join(f"2018;1;{uf};BR;BRASIL;{cd};{mun};1;Presidente;{sq};{nr};{nm};{p};{v};{sit}\n"
                          for uf, cd, mun, sq, nr, nm, p, v, sit in [
        ("SP", "71072", "SÃO PAULO", "801", "17", "CANDIDATO A", "PSL", 700, "2º TURNO"),
        ("SP", "71072", "SÃO PAULO", "802", "13", "CANDIDATO B", "PT", 300, "2º TURNO"),
        ("RJ", "60011", "RIO DE JANEIRO", "801", "17", "CANDIDATO A", "PSL", 400, "2º TURNO"),
        ("RJ", "60011", "RIO DE JANEIRO", "802", "13", "CANDIDATO B", "PT", 600, "2º TURNO"),
        ("ZZ", "99999", "LISBOA", "802", "13", "CANDIDATO B", "PT", 10, "2º TURNO")])
    caminho = tmp_path / "munzona_2018.zip"
    with zipfile.ZipFile(caminho, "w") as z:  # ordem do zip real: estados, depois _BR, depois mais estados
        z.writestr("votacao_candidato_munzona_2018_SP.csv", sp.encode("latin-1"))
        z.writestr("votacao_candidato_munzona_2018_BR.csv", br.encode("latin-1"))
        z.writestr("votacao_candidato_munzona_2018_RJ.csv", rj.encode("latin-1"))
    for _ in range(2):  # idempotente
        tse_resultados.coletar_resultados(2018, arquivo_local=str(caminho))

    assert cliente.get("/eleicoes/2018/SP/cargos").json() == ["PRESIDENTE", "GOVERNADOR"]
    assert cliente.get("/eleicoes/2018/SP", params={"cargo": "GOVERNADOR"}).json()["mais_votados"][0]["nome"] == "DORIA"
    br = cliente.get("/eleicoes/2018/BR", params={"cargo": "PRESIDENTE"}).json()
    assert [(c["nome"], c["votos"]) for c in br["mais_votados"]] == [("CANDIDATO A", 1100), ("CANDIDATO B", 910)]
    rj = cliente.get("/eleicoes/2018/RJ", params={"cargo": "PRESIDENTE"}).json()
    assert rj["mais_votados"][0]["nome"] == "CANDIDATO B" and rj["mais_votados"][0]["percentual"] == 60.0
    mapa = cliente.get("/eleicoes/2018/SP/mapa", params={"cargo": "PRESIDENTE"}).json()
    assert mapa[0]["vencedor"]["nome"] == "CANDIDATO A"
    assert mapa[0]["segundo"]["percentual"] <= mapa[0]["vencedor"]["percentual"]  # presidente: segundo colocado na cidade

    est = cliente.get("/eleicoes/2018/estados", params={"cargo": "PRESIDENTE"}).json()
    assert est["estados"]["SP"]["candidatos"][0]["nome"] == "CANDIDATO A"
    assert est["estados"]["RJ"]["candidatos"][0]["percentual"] == 60.0
    assert est["brasil"]["candidatos"][0]["votos"] == 1100 and est["brasil"]["votos_validos_nominais"] == 2010
    gov = cliente.get("/eleicoes/2018/estados", params={"cargo": "governador"}).json()
    assert set(gov["estados"]) == {"SP", "RJ"} and gov["estados"]["RJ"]["partidos"][0]["partido"] == "PSC"
    assert cliente.get("/eleicoes/2018/cargos").json() == ["PRESIDENTE", "GOVERNADOR"]


def test_candidato_do_segundo_turno_fica_com_o_resultado_final(tmp_path):
    """No consulta_cand, quem foi ao 2º turno tem duas linhas (turno 1: "2º TURNO"; turno 2: "ELEITO")."""
    from app.collectors import TAREFAS  # a tarefa registrada também normaliza (registros -> candidatos)
    cab = "ANO_ELEICAO;NR_TURNO;SG_UF;NM_UE;DS_CARGO;SQ_CANDIDATO;NR_CANDIDATO;NM_CANDIDATO;NM_URNA_CANDIDATO;SG_PARTIDO;DS_SIT_TOT_TURNO\n"
    linhas = ["2014;2;PI;PIAUÍ;GOVERNADOR;991;13;FULANO DE TAL;FULANO;PT;ELEITO",
              "2014;1;PI;PIAUÍ;GOVERNADOR;991;13;FULANO DE TAL;FULANO;PT;2º TURNO",
              "2014;1;PI;PIAUÍ;GOVERNADOR;992;45;BELTRANO;BELTRANO;PSDB;2º TURNO",
              "2014;2;PI;PIAUÍ;GOVERNADOR;992;45;BELTRANO;BELTRANO;PSDB;NÃO ELEITO"]
    caminho = tmp_path / "cand_2014.zip"
    with zipfile.ZipFile(caminho, "w") as z:
        z.writestr("consulta_cand_2014_PI.csv", (cab + "\n".join(linhas) + "\n").encode("latin-1"))
    TAREFAS["tse-candidatos"](ano=2014, arquivo_local=str(caminho))
    r = cliente.get("/candidatos", params={"ano": 2014, "cargo": "GOVERNADOR"}).json()
    assert {c["nome_urna"]: c["resultado"] for c in r["itens"]} == {"FULANO": "ELEITO", "BELTRANO": "NÃO ELEITO"}
    assert [c["nome_urna"] for c in cliente.get("/candidatos", params={"ano": 2014, "cargo": "GOVERNADOR",
                                                                         "eleitos": "true"}).json()["itens"]] == ["FULANO"]


def test_presidente_espalhado_nos_arquivos_dos_estados(tmp_path):
    """Até 2016 não há arquivo _BR: cada UF traz os votos do Presidente no estado (formato real de 2006)."""
    linhas = {"SP": [("SP", "71072", "SÃO PAULO", "1", "Presidente", "61", "13", "LULA", "PT", 700, "2º TURNO"),
                     ("SP", "71072", "SÃO PAULO", "1", "Presidente", "62", "45", "ALCKMIN", "PSDB", 900, "2º TURNO"),
                     ("SP", "71072", "SÃO PAULO", "1", "Governador", "63", "45", "SERRA", "PSDB", 1000, "ELEITO")],
              "BA": [("BA", "38490", "SALVADOR", "1", "Presidente", "61", "13", "LULA", "PT", 800, "2º TURNO"),
                     ("BA", "38490", "SALVADOR", "1", "Presidente", "62", "45", "ALCKMIN", "PSDB", 200, "2º TURNO")]}
    caminho = tmp_path / "munzona_2006.zip"
    with zipfile.ZipFile(caminho, "w") as z:
        for uf, ls in linhas.items():
            txt = CAB_BR + "".join(f"2006;{t};{u};{u if c != 'Presidente' else 'BR'};X;{cd};{mun};{t};{c};{sq};{nr};{nm};{p};{v};{sit}\n"
                                   for u, cd, mun, t, c, sq, nr, nm, p, v, sit in ls)
            z.writestr(f"votacao_candidato_munzona_2006_{uf}.csv", txt.encode("latin-1"))
    for _ in range(2):  # idempotente
        tse_resultados.coletar_resultados(2006, arquivo_local=str(caminho))
    br = cliente.get("/eleicoes/2006/BR", params={"cargo": "PRESIDENTE"}).json()
    assert [(c["nome"], c["votos"]) for c in br["mais_votados"]] == [("LULA", 1500), ("ALCKMIN", 1100)]
    assert cliente.get("/eleicoes/2006/SP", params={"cargo": "GOVERNADOR"}).json()["mais_votados"][0]["nome"] == "SERRA"


def test_codigo_do_candidato_de_2000_a_2008_vira_unico(tmp_path):
    """De 2000 a 2008 o SQ_CANDIDATO se repete entre estados (2006: 10112 em mais de uma UF)."""
    from app.collectors.tse import sq_unico
    assert sq_unico("10112", "SP", 2006) == "SP-10112" and sq_unico("10112", "RJ", 2006) == "RJ-10112"
    assert sq_unico("61", "BR", 2006) == "61" and sq_unico("250002541303", "SP", 2026) == "250002541303"
    caminho = tmp_path / "munzona_2006.zip"
    with zipfile.ZipFile(caminho, "w") as z:
        for uf, nome in (("SP", "FULANO SP"), ("RJ", "FULANO RJ")):
            txt = CAB_BR + f"2006;1;{uf};{uf};X;1;CAPITAL;1;Governador;10112;45;{nome};PSDB;100;ELEITO\n"
            z.writestr(f"votacao_candidato_munzona_2006_{uf}.csv", txt.encode("latin-1"))
    tse_resultados.coletar_resultados(2006, arquivo_local=str(caminho))
    assert cliente.get("/eleicoes/2006/RJ", params={"cargo": "GOVERNADOR"}).json()["mais_votados"][0]["nome"] == "FULANO RJ"
    assert cliente.get("/eleicoes/2006/SP", params={"cargo": "GOVERNADOR"}).json()["mais_votados"][0]["nome"] == "FULANO SP"


def test_presidente_so_no_arquivo_brasil_1998(tmp_path):
    """Em 1998 o Presidente só vem no arquivo _BRASIL (que também repete as UFs)."""
    gov = CAB_BR + "1998;1;SP;SP;SÃO PAULO;1;CAPITAL;1;Governador;250002503000161;45;COVAS;PSDB;900;ELEITO\n"
    bra = CAB_BR + "".join([
        "1998;1;SP;SP;SÃO PAULO;1;CAPITAL;1;Governador;250002503000161;45;COVAS;PSDB;900;ELEITO\n",
        "1998;1;SP;BR;BRASIL;1;CAPITAL;1;Presidente;280002801000045;45;FHC;PSDB;800;ELEITO\n",
        "1998;1;RJ;BR;BRASIL;2;RIO;1;Presidente;280002801000045;45;FHC;PSDB;300;ELEITO\n",
        "1998;1;RJ;BR;BRASIL;2;RIO;1;Presidente;280002801000013;13;LULA;PT;500;NÃO ELEITO\n"])
    caminho = tmp_path / "munzona_1998.zip"
    with zipfile.ZipFile(caminho, "w") as z:
        z.writestr("votacao_candidato_munzona_1998_SP.csv", gov.encode("latin-1"))
        z.writestr("votacao_candidato_munzona_1998_BRASIL.csv", bra.encode("latin-1"))
    tse_resultados.coletar_resultados(1998, arquivo_local=str(caminho))
    br = cliente.get("/eleicoes/1998/BR", params={"cargo": "PRESIDENTE"}).json()
    assert [(c["nome"], c["votos"]) for c in br["mais_votados"]] == [("FHC", 1100), ("LULA", 500)]
    assert cliente.get("/eleicoes/1998/SP", params={"cargo": "GOVERNADOR"}).json()["mais_votados"][0]["votos"] == 900
