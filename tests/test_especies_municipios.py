"""Espécies ameaçadas por município (scripts/especies_municipios.py): soma por grupo, sem inventar registro, e a rota."""
import json

from fastapi.testclient import TestClient

from app.main import app
from scripts import especies_municipios as em


def _nomes_reais(tipo, n=3):
    d, _, g_idx = em._arquivo_lista(tipo)
    return [(e[0], e[g_idx]) for e in d["especies"][:n]], d


def test_conta_especies_diferentes_por_municipio_e_grupo(tmp_path, monkeypatch):
    monkeypatch.setattr(em, "CACHE", tmp_path)
    (a, b, c), d = _nomes_reais("animais")[0], _nomes_reais("animais")[1]
    cache = {
        a[0]: {"BRA.1.1_2": 10, "BRA.1.2_2": 1},      # dois municípios
        b[0]: {"BRA.1.1_2": 3},                        # um dos mesmos municípios
        c[0]: {},                                      # sem nenhum registro: não vira zero escondido nem entra na conta
    }
    (tmp_path / "animais.json").write_text(json.dumps(cache), encoding="utf-8")
    mapa = {"BRA.1.1_2": "1100015", "BRA.1.2_2": "1100023"}
    r = em._bloco("animais", mapa, {"1100015": ("Alta Floresta D'Oeste", "RO"), "1100023": ("Ariquemes", "RO")})
    assert r["especies"] == len(d["especies"])
    assert r["com_registro"] == 2                      # só as duas que têm registro
    assert set(r["municipios"]) == {"1100015", "1100023"}
    pos = {g: i for i, g in enumerate(r["grupos"])}
    # a primeira espécie conta uma vez em cada município; o município 1100015 tem as duas espécies somadas
    assert sum(r["municipios"]["1100015"]) == 2 and sum(r["municipios"]["1100023"]) == 1
    assert r["municipios"]["1100015"][pos[a[1]]] >= 1
    assert r["top"][""][0] == ["1100015", "Alta Floresta D'Oeste", "RO", 2]


def test_gid_sem_par_no_ibge_nao_entra(tmp_path, monkeypatch):
    monkeypatch.setattr(em, "CACHE", tmp_path)
    (a,), _ = _nomes_reais("plantas", 1)
    (tmp_path / "plantas.json").write_text(json.dumps({a[0]: {"BRA.9.9_2": 5}}), encoding="utf-8")
    r = em._bloco("plantas", {}, {})
    assert r["com_registro"] == 0 and r["municipios"] == {}


def test_rota_devolve_404_sem_o_arquivo_ou_o_arquivo_com_aviso():
    r = TestClient(app).get("/ambiente/especies-municipios")
    if r.status_code == 404:
        return
    assert r.status_code == 200
    d = r.json()
    assert "GBIF" in d["metodo"] and "animais" in d and "plantas" in d
    assert d["animais"]["com_registro"] <= d["animais"]["especies"]


def test_registro_de_centroide_nao_conta(tmp_path, monkeypatch):
    """Município com só registros de centroide (coordenada sem local real) não ganha a espécie; com registro de verdade, ganha."""
    monkeypatch.setattr(em, "CACHE", tmp_path)
    (a, b), _ = _nomes_reais("animais", 2)
    (tmp_path / "animais.json").write_text(json.dumps({
        a[0]: {"BRA.1.1_2": 5, "BRA.1.2_2": 4},      # 5 no primeiro (todos de centroide), 4 no segundo (1 de centroide)
        b[0]: {"BRA.1.1_2": 2},
    }), encoding="utf-8")
    (tmp_path / "animais_centroide.json").write_text(json.dumps({a[0]: {"BRA.1.1_2": 5, "BRA.1.2_2": 1}}), encoding="utf-8")
    mapa = {"BRA.1.1_2": "1100015", "BRA.1.2_2": "1100023"}
    r = em._bloco("animais", mapa, {"1100015": ("A", "RO"), "1100023": ("B", "RO")})
    assert sum(r["municipios"]["1100015"]) == 1       # só a espécie b tem registro de verdade ali
    assert sum(r["municipios"]["1100023"]) == 1       # a espécie a sobra com 3 registros
    assert r["com_registro"] == 2


def test_os_dois_descontos_nao_se_somam(tmp_path, monkeypatch):
    """Centroide do GBIF e caixa do centroide do Brasil pegam os mesmos registros: vale o maior desconto, não a soma."""
    monkeypatch.setattr(em, "CACHE", tmp_path)
    (a,), _ = _nomes_reais("animais", 1)
    (tmp_path / "animais.json").write_text(json.dumps({a[0]: {"BRA.1.1_2": 10}}), encoding="utf-8")
    (tmp_path / "animais_centroide.json").write_text(json.dumps({a[0]: {"BRA.1.1_2": 6}}), encoding="utf-8")
    (tmp_path / "animais_caixa.json").write_text(json.dumps({a[0]: {"BRA.1.1_2": 6}}), encoding="utf-8")
    r = em._bloco("animais", {"BRA.1.1_2": "1100015"}, {"1100015": ("A", "RO")})
    assert "1100015" in r["municipios"]                 # 10 - max(6, 6) = 4 > 0 (com soma seria 10 - 12 < 0)
    (tmp_path / "animais_caixa.json").write_text(json.dumps({a[0]: {"BRA.1.1_2": 10}}), encoding="utf-8")
    r = em._bloco("animais", {"BRA.1.1_2": "1100015"}, {"1100015": ("A", "RO")})
    assert r["municipios"] == {}                         # tudo era coordenada de centroide
