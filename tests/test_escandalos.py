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
