from app.routers import profissoes as r


def test_lista_sem_dados_nao_quebra(monkeypatch, tmp_path):
    monkeypatch.setattr(r, "ARQUIVO", tmp_path / "nao_existe.json")
    r._carregar.cache_clear(); r._historico.cache_clear()
    d = r.profissoes()
    assert d["disponivel"] is False and d["profissoes"] == []
    r._carregar.cache_clear(); r._historico.cache_clear()


def test_lista_ordenada_pela_media(monkeypatch, tmp_path):
    import json
    arq = tmp_path / "p.json"
    arq.write_text(json.dumps({
        "fonte": "RAIS", "ano_referencia": 2025, "vinculos_validos": 100,
        "profissoes": {
            "111": {"vinculos": 40, "media": 3000.456, "minimo": 1, "maximo": 9, "p10": 1000, "p90": 5000, "horas": []},
            "222": {"vinculos": 50, "media": 9000, "minimo": 1, "maximo": 99, "p10": 2000, "p90": 20000, "horas": []},
        },
    }), encoding="utf-8")
    monkeypatch.setattr(r, "ARQUIVO", arq)
    r._carregar.cache_clear(); r._historico.cache_clear()
    d = r.profissoes()
    r._carregar.cache_clear(); r._historico.cache_clear()
    assert d["disponivel"] is True
    assert [x["cbo"] for x in d["profissoes"]] == ["222", "111"]
    assert d["profissoes"][1]["media"] == 3000.46
    assert set(d["profissoes"][0]) == {"cbo", "nome", "vinculos", "media", "minimo", "maximo", "p10", "p90", "horas", "historico"}


def test_arquivo_real_carrega():
    r._carregar.cache_clear(); r._historico.cache_clear()
    d = r.profissoes()
    r._carregar.cache_clear(); r._historico.cache_clear()
    assert d["disponivel"] is True
    assert d["total_profissoes"] > 2000
    assert d["ano_referencia"] == 2025


def test_nomes_de_cbo_aparecem():
    r._carregar.cache_clear(); r._historico.cache_clear(); r._nomes.cache_clear()
    d = r.profissoes()
    r._carregar.cache_clear(); r._historico.cache_clear(); r._nomes.cache_clear()
    por = {x["cbo"]: x for x in d["profissoes"]}
    assert por["121010"]["nome"]
    assert d["com_nome"] > 2000


def test_historico_entre_anos(monkeypatch, tmp_path):
    import json
    base = {"fonte": "RAIS", "vinculos_validos": 100}
    (tmp_path / "profissoes_rais.json").write_text(json.dumps({**base, "ano_referencia": 2025, "profissoes": {
        "111": {"vinculos": 40, "media": 3300, "horas": []}, "222": {"vinculos": 40, "media": 9000, "horas": []}}}), encoding="utf-8")
    (tmp_path / "profissoes_rais_2024.json").write_text(json.dumps({**base, "ano_referencia": 2024, "profissoes": {
        "111": {"vinculos": 38, "media": 3000}}}), encoding="utf-8")
    monkeypatch.setattr(r, "ARQUIVO", tmp_path / "profissoes_rais.json")
    r._carregar.cache_clear(); r._historico.cache_clear()
    d = r.profissoes()
    r._carregar.cache_clear(); r._historico.cache_clear()
    por = {x["cbo"]: x for x in d["profissoes"]}
    assert d["anos"] == [2024, 2025] and d["aviso_historico"]
    assert por["111"]["historico"] == {"2024": 3000.0, "2025": 3300.0}
    assert por["222"]["historico"] == {"2025": 9000.0}  # profissão sem o ano anterior: só o atual
