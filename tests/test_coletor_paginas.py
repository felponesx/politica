"""Coletor (coletor/coletor.py): fontes paginadas viram UM arquivo com todas as páginas, e uma página falha = nada parcial é gravado."""
import importlib.util
import json
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("coletor_mod", RAIZ / "coletor" / "coletor.py")
col = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(col)

PAGINAS = {
    "http://api/p1": {"dados": [{"id": 1}, {"id": 2}], "links": [{"rel": "next", "href": "http://api/p2"}]},
    "http://api/p2": {"dados": [{"id": 3}], "links": [{"rel": "next", "href": "http://api/p3"}]},
    "http://api/p3": {"dados": [{"id": 4}], "links": []},
}


@pytest.fixture
def pasta(tmp_path, monkeypatch):
    monkeypatch.setattr(col, "DADOS", tmp_path)
    monkeypatch.setattr(col, "RAW", tmp_path / "raw")
    monkeypatch.setattr(col, "DB", tmp_path / "manifesto.db")
    return tmp_path


def _baixar_falso(paginas, falha_em=None):
    def baixar(url, headers, tentativas=3):
        if url == falha_em:
            raise RuntimeError("falha simulada")
        tmp = col.DADOS / f".tmp-falso-{abs(hash(url))}"
        tmp.write_text(json.dumps(paginas[url]), encoding="utf-8")
        return 200, tmp, "application/json", {}
    return baixar


def _arquivos_guardados(pasta, nome):
    return [p for p in (pasta / "raw" / nome).rglob("*") if p.is_file()]


def test_paginas_viram_um_arquivo_so(pasta, monkeypatch):
    monkeypatch.setattr(col, "baixar", _baixar_falso(PAGINAS))
    db = col.abrir_db()
    col.coletar_fonte(db, "camara-deputados", {"url": "http://api/p1", "paginacao": "camara"})
    arquivos = _arquivos_guardados(pasta, "camara-deputados")
    assert len(arquivos) == 1
    corpo = json.loads(arquivos[0].read_text(encoding="utf-8"))
    assert [d["id"] for d in corpo["dados"]] == [1, 2, 3, 4]


def test_pagina_com_falha_nao_grava_nada_parcial(pasta, monkeypatch):
    monkeypatch.setattr(col, "baixar", _baixar_falso(PAGINAS, falha_em="http://api/p3"))
    db = col.abrir_db()
    col.coletar_fonte(db, "camara-deputados", {"url": "http://api/p1", "paginacao": "camara"})
    assert _arquivos_guardados(pasta, "camara-deputados") == []


def test_fonte_sem_paginacao_continua_gravando_como_antes(pasta, monkeypatch):
    unica = {"http://api/unica": {"lista": [1, 2, 3]}}
    monkeypatch.setattr(col, "baixar", _baixar_falso(unica))
    db = col.abrir_db()
    col.coletar_fonte(db, "outra", {"url": "http://api/unica"})
    [arq] = _arquivos_guardados(pasta, "outra")
    assert json.loads(arq.read_text(encoding="utf-8")) == {"lista": [1, 2, 3]}


def test_pagina_sem_lista_dados_e_erro(tmp_path):
    ruim = tmp_path / "ruim.json"
    ruim.write_text(json.dumps({"erro": "fora do ar"}), encoding="utf-8")
    with pytest.raises(ValueError, match="dados"):
        col.itens_da_pagina(ruim)


def test_304_nao_e_erro_e_nao_repete(monkeypatch):
    """O servidor diz que não mudou: baixar devolve 304 na hora (sem tentar de novo) e a fonte não registra falha."""
    import urllib.error

    chamadas = []

    def abrir_falso(req, timeout=60):
        chamadas.append(1)
        raise urllib.error.HTTPError(req.full_url, 304, "Not Modified", {}, None)

    monkeypatch.setattr(col.urllib.request, "urlopen", abrir_falso)
    status, tmp, tipo, _ = col.baixar("http://api/x", {}, tentativas=3)
    assert status == 304 and tmp is None
    assert len(chamadas) == 1


def test_304_em_coletar_fonte_nao_grava_arquivo(pasta, monkeypatch):
    monkeypatch.setattr(col, "baixar", lambda url, headers, tentativas=3: (304, None, None, {}))
    db = col.abrir_db()
    col.coletar_fonte(db, "bcb-teste", {"url": "http://api/y"})
    assert _arquivos_guardados(pasta, "bcb-teste") == []


def test_proxima_pagina_com_acentos_em_utf8(tmp_path):
    """Regressão: no Windows o padrão de leitura é cp1252; a página da Câmara tem acentos em UTF-8.
    A leitura precisa ser UTF-8 explícita, senão o próximo link some e a fonte para na primeira página."""
    pagina = tmp_path / "pagina.json"
    corpo = {"dados": [{"id": 1, "nome": "Conceição Ação"}], "links": [{"rel": "next", "href": "http://api/p2"}]}
    pagina.write_bytes(json.dumps(corpo, ensure_ascii=False).encode("utf-8"))
    assert col.proxima_pagina({"paginacao": "camara"}, pagina) == "http://api/p2"
