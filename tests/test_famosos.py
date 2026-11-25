"""Aba Artistas e famosos: coletor (scripts/famosos.py, com respostas simuladas do Wikidata e do Deezer, sem internet) e API (app/famosos.py)."""
import json

from fastapi.testclient import TestClient

from app import famosos
from app.main import app
from scripts import famosos as fm


def test_rotulo_ignora_q_sem_nome():
    assert fm.rotulo("Q12345") is None
    assert fm.rotulo("") is None
    assert fm.rotulo(None) is None
    assert fm.rotulo(" Anitta ") == "Anitta"


def test_ano_e_qid():
    assert fm.ano("1993-03-30T00:00:00Z") == 1993
    assert fm.ano(None) is None
    assert fm.qid("http://www.wikidata.org/entity/Q230401") == "Q230401"


def test_consultas_em_lote_dividem_quando_falha(monkeypatch):
    """Se o Wikidata estoura o tempo com o lote inteiro, o lote é dividido ao meio até caber."""
    chamadas = []

    def falso(q, tentativas=5):
        n = q.count("wd:Q")
        chamadas.append(n)
        if n > 2:
            raise RuntimeError("tempo")
        return [{"p": "http://www.wikidata.org/entity/Q%d" % i} for i in range(n)]

    monkeypatch.setattr(fm, "sparql", falso)
    ids = ["Q%d" % i for i in range(1, 9)]
    r = fm.em_lotes(lambda parte: "VALUES ?p { %s }" % " ".join("wd:" + i for i in parte), ids, 8)
    assert len(r) == 8
    assert max(c for c in chamadas if c <= 2) == 2


def test_juntar_obras_nao_duplica_e_descarta_q():
    dest = {}
    fm.juntar_obras([
        {"p": "http://x/Q1", "wLabel": "Cidade de Deus", "wsl": "40", "data": "2002-08-30T00:00:00Z"},
        {"p": "http://x/Q1", "wLabel": "Cidade de Deus", "wsl": "40", "data": "2002-08-30T00:00:00Z"},
        {"p": "http://x/Q1", "wLabel": "Q99999", "wsl": "1"},
    ], "atuação", dest)
    assert list(dest["Q1"].values()) == [["Cidade de Deus", 2002, "atuação", 40]]


def test_deezer_fas_le_numero_e_trata_erro(monkeypatch):
    class R:
        def __init__(self, d): self.d = d
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return json.dumps(self.d).encode()

    monkeypatch.setattr(fm.urllib.request, "urlopen", lambda req, timeout=0: R({"id": 1, "name": "X", "nb_fan": 1234}))
    assert fm.deezer_fas(1) == 1234
    monkeypatch.setattr(fm.urllib.request, "urlopen", lambda req, timeout=0: R({"error": {"code": 800, "message": "no data"}}))
    assert fm.deezer_fas(2) is None


DOC = {"gerado": "2026-11-25", "grupos": {"musico": {"nome": "Músicos", "n": 2}, "ator": {"nome": "Atores", "n": 1}}, "p": [
    {"q": "Q1", "n": "Artista Um", "g": ["musico"], "s": 40, "a": 1980, "u": "SP", "ge": ["samba"], "dz": [1000, "2026-11-25", 77], "rs": {"ig": [5000, "2025-01-01"]}},
    {"q": "Q2", "n": "Artista Dois", "g": ["musico", "ator"], "s": 3, "a": 1950, "m": 2020},
]}


def test_api_lê_arquivo_e_nao_inventa(tmp_path, monkeypatch):
    arq = tmp_path / "famosos.json"
    arq.write_text(json.dumps(DOC), encoding="utf-8")
    monkeypatch.setattr(famosos, "ARQ", arq)
    famosos.recarregar()
    c = TestClient(app)
    b = c.get("/famosos/base").json()
    assert len(b["p"]) == 2 and "horas ouvidas" in b["aviso"]
    r = c.get("/famosos/resumo").json()
    assert r["total"] == 2 and r["com_deezer"] == 1 and r["com_seguidores"] == 1
    p = c.get("/famosos/pessoa/Q1").json()
    assert p["dz"][0] == 1000 and "dz" not in c.get("/famosos/pessoa/Q2").json()
    assert c.get("/famosos/pessoa/Q404").status_code == 404
    famosos.recarregar()


def test_sem_arquivo_responde_404(tmp_path, monkeypatch):
    monkeypatch.setattr(famosos, "ARQ", tmp_path / "nao_existe.json")
    famosos.recarregar()
    c = TestClient(app)
    assert c.get("/famosos/base").status_code == 404
    assert c.get("/famosos/resumo").status_code == 404
    assert c.get("/famosos/pessoa/Q1").status_code == 404
    famosos.recarregar()


def test_genero_norm():
    assert fm.genero_norm("Arrocha") == "arrocha"
    assert fm.genero_norm("MPB") == "MPB"
    assert fm.genero_norm("R&B") == "R&B"
    assert fm.genero_norm("música pop") == "música pop"
