"""Escândalos: só entra informação com fonte; situação jurídica com termos fixos; resumo conta pessoas por situação."""
import json
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./teste.db")

from fastapi.testclient import TestClient  # noqa: E402

from app import escandalos  # noqa: E402
from app.main import app  # noqa: E402

cliente = TestClient(app)
F = "https://exemplo.gov.br/noticia"
CASO = {
    "slug": "caso-teste", "nome": "Caso Teste", "periodo": {"inicio": "2020", "fim": "2022"}, "ano_revelado": 2021,
    "resumo": "Resumo neutro.",
    "valores": {"desviado": {"valor": 1000000, "texto": "R$ 1 milhão", "fonte": F}, "recuperado": {"valor": 5, "texto": "sem fonte"}},
    "orgaos": [{"nome": "Polícia Federal", "papel": "investigação"}],
    "andamento": [{"data": "2022-01", "fato": "Denúncia", "fonte": F}, {"data": "2021-05", "fato": "Operação", "fonte": F},
                  {"data": "2023", "fato": "Sem fonte"}],
    "situacao_atual": {"texto": "Em julgamento", "data": "2026-09", "fonte": F},
    "pessoas": [
        {"nome": "Fulano", "partido_na_epoca": "XYZ", "situacao": "Condenado", "liberdade": "preso", "fonte": F,
         "valor_recebido": {"valor": 200, "texto": "propina", "fonte": F}},
        {"nome": "Beltrano", "situacao": "condenação anulada", "liberdade": "em liberdade", "fonte": F},
        {"nome": "Sicrano", "situacao": "condenado", "liberdade": "foragido"},  # sem fonte: não entra
        {"nome": "Outro", "situacao": "culpado", "liberdade": "solto", "fonte": F},  # termos fora da lista viram None
    ],
}


def test_escandalos(tmp_path, monkeypatch):
    (tmp_path / "caso-teste.json").write_text(json.dumps(CASO), encoding="utf-8")
    monkeypatch.setattr(escandalos, "PASTA", tmp_path)
    escandalos.casos.cache_clear()
    try:
        lista = cliente.get("/escandalos").json()
        r = lista["itens"][0]
        assert lista["total"] == 1 and "presumidos inocentes" in lista["aviso"]
        assert (r["pessoas"], r["condenados"], r["presos"], r["foragidos"], r["partidos"]) == (3, 1, 1, 0, ["XYZ"])
        c = cliente.get("/escandalos/caso-teste").json()
        assert [p["nome"] for p in c["pessoas"]] == ["Fulano", "Beltrano", "Outro"]
        assert c["pessoas"][0]["situacao"] == "condenado" and c["pessoas"][2]["situacao"] is None and c["pessoas"][2]["liberdade"] is None
        assert c["valores"]["recuperado"] is None and c["valores"]["desviado"]["valor"] == 1000000
        assert [a["fato"] for a in c["andamento"]] == ["Operação", "Denúncia"]
        assert cliente.get("/escandalos/nao-existe").status_code == 404
    finally:
        escandalos.casos.cache_clear()


def test_organograma_so_com_pessoas_do_caso_e_fonte(tmp_path, monkeypatch):
    (tmp_path / "caso-teste.json").write_text(json.dumps(CASO), encoding="utf-8")
    (tmp_path / "papeis").mkdir()
    (tmp_path / "papeis" / "caso-teste.json").write_text(json.dumps({
        "slug": "caso-teste", "explicacao": "Dois núcleos.", "explicacao_fonte": F, "nucleos": [{"nome": "Político"}],
        "papeis": [{"nome": "Fulano", "nivel": 1, "nucleo": "Político", "papel": "apontado como líder", "fonte": F},
                   {"nome": "Beltrano", "nivel": 2, "papel": "operador", "fonte": F, "acima": "Fulano"},
                   {"nome": "Outro", "nivel": 3, "papel": "x", "fonte": F, "acima": "Ninguém"},
                   {"nome": "Sicrano", "nivel": 3, "papel": "fora da lista de pessoas", "fonte": F},
                   {"nome": "Fulano", "nivel": 4, "papel": "nível inválido", "fonte": F},
                   {"nome": "Beltrano", "nivel": 3, "papel": "sem fonte"}]}), encoding="utf-8")
    monkeypatch.setattr(escandalos, "PASTA", tmp_path)
    escandalos.casos.cache_clear()
    try:
        o = cliente.get("/escandalos/caso-teste").json()["organograma"]
        assert [(x["nome"], x["nivel"], x["acima"]) for x in o["papeis"]] == [("Fulano", 1, None), ("Beltrano", 2, "Fulano"), ("Outro", 3, None)]
        assert o["explicacao_fonte"] == F
    finally:
        escandalos.casos.cache_clear()


def test_crimes_traz_investigados_com_foro_sem_condenados_nem_ex():
    from app import escandalos
    r = escandalos.crimes()
    assert r["total_foro"] == len(r["foro"]) and r["total_foro"] > 0
    cond = {i["nome"] for i in r["itens"]}
    assert all(x["situacao"] in {"investigado", "indiciado", "denunciado", "réu"} and x["foro"] in {"STF", "STJ"} for x in r["foro"])
    assert not any(x["nome"] in cond for x in r["foro"])
    assert not any(x["cargo"].lower().startswith("ex-") or "candidato" in x["cargo"].lower() for x in r["foro"])


def test_premios_com_fonte():
    from app import premios
    d = premios.dados()
    assert {"futebol", "olimpiadas", "jogos-eletronicos"} <= {c["slug"] for c in d["categorias"]}
    for c in d["categorias"]:
        for g in c["grupos"]:
            assert g["fonte"].startswith("https://")


def test_foragidos_com_fonte():
    from app import escandalos
    c = escandalos.crimes()
    assert c["total_foragidos"] >= 1
    assert all(i["fontes"] for i in c["foragidos"])


def test_prioridade_do_regime():
    from types import SimpleNamespace as N
    from app.projetos import prioridade
    assert prioridade(N(sigla_tipo="PL", regime="Urgência (Art. 155, RICD)")) == "alta"
    assert prioridade(N(sigla_tipo="PL", regime="Prioridade (Art. 151, II, RICD)")) == "media"
    assert prioridade(N(sigla_tipo="PL", regime="Ordinária (Art. 151, III, RICD)")) == "baixa"
    assert prioridade(N(sigla_tipo="MPV", regime=None)) == "alta"
    assert prioridade(N(sigla_tipo="PL", regime=None)) is None


def test_julgamentos_com_fonte():
    from app import julgamentos
    d = julgamentos.dados()
    assert d["itens"] and all(i["fonte"].startswith("https://") for i in d["itens"])
