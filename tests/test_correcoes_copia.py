"""Correções das falhas da planilha de diagnóstico (31/10/2026): espera em 429 no SICONFI, slug de polícia sem acento na cópia."""
import httpx

from app import policias
from app.collectors import siconfi


def _erro_429():
    req = httpx.Request("GET", "https://x")
    return httpx.HTTPStatusError("HTTP 429", request=req, response=httpx.Response(429, request=req))


def test_siconfi_espera_em_429_e_tenta_de_novo(monkeypatch):
    chamadas = []
    esperas = []
    def fake(url, params=None):
        chamadas.append(1)
        if len(chamadas) < 3:
            raise _erro_429()
        return {"items": [{"conta": "x"}], "hasMore": False}
    monkeypatch.setattr(siconfi.http, "get_json", fake)
    monkeypatch.setattr("time.sleep", lambda s: esperas.append(s))
    itens = list(siconfi.paginar("rreo", {"an_exercicio": 2025}))
    assert itens == [{"conta": "x"}]
    assert len(chamadas) == 3 and esperas == [60, 120]


def test_siconfi_desiste_depois_de_varias_tentativas(monkeypatch):
    import pytest
    monkeypatch.setattr(siconfi.http, "get_json", lambda url, params=None: (_ for _ in ()).throw(_erro_429()))
    monkeypatch.setattr("time.sleep", lambda s: None)
    with pytest.raises(httpx.HTTPStatusError):
        list(siconfi.paginar("rreo", {}))


def test_slug_de_policia_com_acento_bate_com_a_rota():
    from scripts.exportar_snapshot import _slug_policia
    assert _slug_policia("u-SP-Águia") == policias.slug("u-SP-Águia") == "u-SP-Aguia"
