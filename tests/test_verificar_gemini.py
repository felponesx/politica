"""Verificador Gemini: divide a cópia em pedaços, lê a resposta e grava só sugestões (sem alterar dados)."""
import json
from pathlib import Path

import httpx

from scripts import verificar_gemini as vg


def test_pedacos_respeitam_limite_e_nao_cortam_json(tmp_path):
    grande = [{"n": i, "texto": "x" * 500} for i in range(300)]
    (tmp_path / "a.json").write_text(json.dumps(grande), encoding="utf-8")
    (tmp_path / "b.json").write_text(json.dumps({"ok": 1}), encoding="utf-8")
    pec = list(vg.pedacos(tmp_path))
    assert len(pec) > 2
    for arq, texto in pec:
        json.loads(texto)  # cada pedaço é JSON válido
        assert len(texto) <= vg.TAMANHO_PEDACO + 600
    assert sum(len(json.loads(t)) for a, t in pec if a == "a.json") == 300


def test_grava_sugestoes_sem_tocar_nos_dados(tmp_path, monkeypatch):
    pasta = tmp_path / "dados"
    pasta.mkdir()
    original = {"valor": 10}
    (pasta / "x.json").write_text(json.dumps(original), encoding="utf-8")

    def fake_post(self, url, json=None, headers=None, timeout=None):
        assert headers["x-goog-api-key"] == "chave-falsa"
        resp = {"candidates": [{"content": {"parts": [{"text": json_mod.dumps([{
            "caminho": "valor", "problema": "valor baixo", "valor_atual": "10", "sugestao": "conferir",
            "fonte": "fonte oficial", "confianca": "baixa"}])}]}}]}
        return httpx.Response(200, json=resp, request=httpx.Request("POST", url))

    import json as json_mod
    monkeypatch.setattr(httpx.Client, "post", fake_post)
    monkeypatch.setenv("GEMINI_API_KEY", "chave-falsa")
    saida = tmp_path / "saida.csv"
    assert vg.main([str(pasta), str(saida)]) == 0
    texto = saida.read_text(encoding="utf-8-sig")
    assert "valor baixo" in texto and "x.json" in texto
    assert json.loads((pasta / "x.json").read_text(encoding="utf-8")) == original


def test_sem_chave_nao_chama_api(tmp_path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    (tmp_path / "x.json").write_text("{}", encoding="utf-8")
    assert vg.main([str(tmp_path), str(tmp_path / "s.csv")]) == 2
