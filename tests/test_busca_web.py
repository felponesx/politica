"""Busca na internet (Perplexity Search API) com respostas simuladas no formato da referência
(https://docs.perplexity.ai/api-reference/search-post), sem internet e sem chave real."""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./teste.db")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import busca_web  # noqa: E402
from app.config import settings  # noqa: E402
from app.main import app  # noqa: E402

cliente = TestClient(app)

PAGINA = {"title": "Senado aprova reforma", "url": "https://www12.senado.leg.br/noticias/a",
          "snippet": "O Plenário aprovou...", "date": "2026-10-14", "last_updated": "2026-10-15"}
RESPOSTA = {"results": [PAGINA, {"title": "Agência Brasil", "url": "https://agenciabrasil.ebc.com.br/b",
                                 "snippet": "Texto segue para a Câmara."}],
            "id": "e38104d5-6bd7-4d82-bc4e-0a21179d1f77", "server_time": None}


class _Resp:
    def __init__(self, dados, status=200, headers=None):
        self.dados, self.status_code, self.headers = dados, status, headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx
            raise httpx.HTTPStatusError(f"HTTP {self.status_code}", request=None, response=self)

    def json(self):
        return self.dados


@pytest.fixture
def com_chave(monkeypatch):
    monkeypatch.setattr(settings, "perplexity_api_key", "chave-de-teste")


def test_sem_chave(monkeypatch):
    monkeypatch.setattr(settings, "perplexity_api_key", "")
    r = cliente.post("/busca/web", json={"query": "reforma tributária"})
    assert r.status_code == 503 and "PERPLEXITY_API_KEY" in r.json()["detail"]


def test_busca_simples_monta_corpo_da_referencia(monkeypatch, com_chave):
    enviados = []

    def falso(url, json=None, timeout=None, headers=None, **_):
        enviados.append((url, json, headers))
        return _Resp(RESPOSTA)

    monkeypatch.setattr(busca_web.httpx, "post", falso)
    r = cliente.post("/busca/web", json={"query": "reforma tributária Senado", "max_resultados": 3,
                                         "dominios": ["senado.leg.br", "camara.leg.br"], "recencia": "week",
                                         "idiomas": ["pt"]})
    assert r.status_code == 200
    d = r.json()
    assert [x["url"] for x in d["resultados"]] == [PAGINA["url"], "https://agenciabrasil.ebc.com.br/b"]
    assert d["resultados"][0] == {"titulo": "Senado aprova reforma", "url": PAGINA["url"], "trecho": "O Plenário aprovou...",
                                  "data": "2026-10-14", "atualizado": "2026-10-15"}
    url, corpo, headers = enviados[0]
    assert url == "https://api.perplexity.ai/search"
    assert headers["Authorization"] == "Bearer chave-de-teste"
    assert corpo == {"query": "reforma tributária Senado", "max_results": 3, "country": "BR",
                     "search_language_filter": ["pt"], "search_domain_filter": ["senado.leg.br", "camara.leg.br"],
                     "search_recency_filter": "week"}
    # mesma busca: vem da memória, sem nova cobrança
    cliente.post("/busca/web", json={"query": "reforma tributária Senado", "max_resultados": 3,
                                     "dominios": ["senado.leg.br", "camara.leg.br"], "recencia": "week", "idiomas": ["pt"]})
    assert len(enviados) == 1


def test_varias_consultas_tira_links_repetidos(monkeypatch, com_chave):
    por_consulta = {"results": [[PAGINA], [PAGINA, {"title": "Outra", "url": "https://g1.globo.com/c", "snippet": "x"}]],
                    "id": "1"}
    monkeypatch.setattr(busca_web.httpx, "post", lambda *a, json=None, **k: _Resp(por_consulta))
    d = busca_web.buscar(["reforma Senado", "reforma Câmara"])
    assert [x["url"] for x in d["resultados"]] == [PAGINA["url"], "https://g1.globo.com/c"]
    assert d["consultas"] == ["reforma Senado", "reforma Câmara"]


def test_validacoes(com_chave):
    with pytest.raises(ValueError):
        busca_web.buscar(["a", "b", "c", "d", "e", "f"])
    with pytest.raises(ValueError):
        busca_web.buscar("x", dominios=["gov.br", "-g1.globo.com"])
    with pytest.raises(ValueError):
        busca_web.buscar("x", recencia="decada")
    assert cliente.post("/busca/web", json={"query": ["1", "2", "3", "4", "5", "6"]}).status_code == 422


def test_429_respeita_retry_after(monkeypatch, com_chave):
    respostas = [_Resp({}, 429, {"Retry-After": "2"}), _Resp(RESPOSTA)]
    pausas = []
    monkeypatch.setattr(busca_web.httpx, "post", lambda *a, **k: respostas.pop(0))
    monkeypatch.setattr(busca_web.time, "sleep", pausas.append)
    assert len(busca_web.buscar("x")["resultados"]) == 2
    assert pausas == [2.0]


def test_limite_diario(monkeypatch, com_chave):
    monkeypatch.setattr(settings, "perplexity_busca_limite_dia", 1)
    monkeypatch.setattr(busca_web.httpx, "post", lambda *a, **k: _Resp(RESPOSTA))
    assert cliente.post("/busca/web", json={"query": "um"}).status_code == 200
    assert cliente.post("/busca/web", json={"query": "dois"}).status_code == 429
