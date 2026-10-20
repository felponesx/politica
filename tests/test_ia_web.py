"""Pesquisa na internet da IA (Perplexity) com resposta simulada (sem internet e sem chave real)."""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./teste.db")

from fastapi.testclient import TestClient  # noqa: E402

from app import ia_web  # noqa: E402
from app.config import settings  # noqa: E402
from app.main import app  # noqa: E402

cliente = TestClient(app)

# formato da Agent API (POST /v1/responses), resumido
RESPOSTA = {
    "id": "resp_1", "model": "perplexity/sonar", "status": "completed",
    "output": [
        {"type": "search_results", "results": [{"title": "Agência Senado", "url": "https://www12.senado.leg.br/noticias/x"}]},
        {"type": "message", "role": "assistant", "content": [{
            "type": "output_text", "text": "O Senado aprovou a proposta em 14/10/2026.",
            "annotations": [{"type": "url_citation", "url": "https://agenciabrasil.ebc.com.br/y", "title": "Agência Brasil"},
                            {"type": "url_citation", "url": "https://www12.senado.leg.br/noticias/x", "title": "Agência Senado"}]}]},
    ],
}


class _Resp:
    def __init__(self, dados):
        self.dados = dados

    def raise_for_status(self):
        pass

    def json(self):
        return self.dados


def test_ia_web_sem_chave(monkeypatch):
    monkeypatch.setattr(settings, "perplexity_api_key", "")
    r = cliente.post("/ia/web", json={"pergunta": "O que o Senado votou esta semana?"})
    assert r.status_code == 503 and "PERPLEXITY_API_KEY" in r.json()["detail"]


def test_ia_web_responde_com_fontes(monkeypatch):
    chamadas = []

    def falso(url, headers=None, json=None, timeout=None):
        chamadas.append((url, headers, json))
        return _Resp(RESPOSTA)

    monkeypatch.setattr(settings, "perplexity_api_key", "chave-de-teste")
    monkeypatch.setattr(ia_web.httpx, "post", falso)
    ia_web._CACHE.clear()
    r = cliente.post("/ia/web", json={"pergunta": "O que o Senado aprovou?"})
    assert r.status_code == 200
    d = r.json()
    assert d["resposta"].startswith("O Senado aprovou")
    assert [f["url"] for f in d["fontes"]] == ["https://www12.senado.leg.br/noticias/x", "https://agenciabrasil.ebc.com.br/y"]
    assert "não dos dados oficiais" in d["aviso"]
    url, headers, corpo = chamadas[0]
    assert url.endswith("/v1/responses") and headers["Authorization"] == "Bearer chave-de-teste" and corpo["preset"] == "low"
    # a mesma pergunta vem da memória, sem nova chamada paga
    cliente.post("/ia/web", json={"pergunta": "O que o Senado aprovou?"})
    assert len(chamadas) == 1


def test_ia_web_limite_diario(monkeypatch):
    monkeypatch.setattr(settings, "perplexity_api_key", "chave-de-teste")
    monkeypatch.setattr(settings, "perplexity_limite_dia", 1)
    monkeypatch.setattr(ia_web.httpx, "post", lambda *a, **k: _Resp(RESPOSTA))
    ia_web._CACHE.clear()
    ia_web._USO.update(dia=None, n=0)
    assert cliente.post("/ia/web", json={"pergunta": "pergunta um"}).status_code == 200
    assert cliente.post("/ia/web", json={"pergunta": "pergunta dois"}).status_code == 429


def test_texto_output_text_direto():
    assert ia_web._texto({"output_text": " oi "}) == "oi"
