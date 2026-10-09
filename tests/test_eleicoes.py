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
