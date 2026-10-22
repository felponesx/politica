"""Contadores do Impostômetro e do Gasto Brasil: respostas reais (22/10/2026, resumidas) e conferência dos números."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from app.collectors import contadores_externos as ce
from scripts import contadores_rapido

AGORA = datetime(2026, 10, 22, 14, 57, tzinfo=timezone.utc)
SPENDING = {"result": {"data": {"year": 2026, "currency": "BRL", "as_of": "2026-10-22T14:55:19.141Z", "entities": [
    {"cod_ente": 0, "label": "Governo Geral", "base_value": 4630886032904.415, "rate_per_second": 183772.89395574393},
    {"cod_ente": 1, "label": "União", "base_value": 2181614666828.9155, "rate_per_second": 86575.5792672775},
    {"cod_ente": 2, "label": "Estados", "base_value": 1243846126077.4382, "rate_per_second": 49361.00793686056},
    {"cod_ente": 3, "label": "Municípios", "base_value": 1205425239998.0603, "rate_per_second": 47836.306751605356}],
    "previdencia": {"base_value": 1333559819182.8076, "rate_per_second": 52976.73567299077}}}}
BRASIL = {"Nome": "Brasil", "Data": "2026-10-22T11:55:12.267", "ValorInicial": 3277040088329.1284, "Incremento": 136990.07859135413,
          "Ano": 3282918606581.6406, "Segundo": 129022.6544, "Habitante": 16191.3123}
UNIAO = {"Nome": "Uniao", "Data": "2026-10-22T11:56:04.723", "ValorInicial": 2173850070506.0078, "Incremento": 90873.43577669698,
         "Ano": 2177754356800.7175, "Segundo": 85588.1937, "Habitante": 10740.6565}


@pytest.fixture
def fonte(monkeypatch):
    respostas = {"/api/trpc/counters.spending": SPENDING, "/api/impostometro/brasil": BRASIL, "/api/impostometro/uniao": UNIAO}
    monkeypatch.setattr(ce, "_json", lambda caminho: respostas[caminho])
    return respostas


def test_leitura_converte_hora_de_brasilia_para_utc(fonte):
    imp = ce.ler_impostometro()
    assert imp["brasil"]["como_de"] == "2026-10-22T14:55:12.267000+00:00"  # 11:55 em Brasília
    assert imp["brasil"]["total"] == pytest.approx(3282918606581.64) and imp["brasil"]["por_segundo"] == pytest.approx(136990.08, abs=0.01)
    gas = ce.ler_gastometro()
    assert gas["como_de"] == "2026-10-22T14:55:19.141000+00:00"
    assert gas["uniao"]["total"] + gas["estados"]["total"] + gas["municipios"]["total"] == pytest.approx(gas["total"]["total"], rel=1e-3)


def test_montar_no_formato_do_contadores(fonte):
    out = ce.montar(ce.ler_impostometro(), ce.ler_gastometro(), AGORA)
    i, g = out["impostometro"], out["gastometro"]
    assert i["total_base"] == pytest.approx(3282918606581.64, abs=1) and i["data_base"] == "2026-10-22" and i["ano"] == 2026
    assert i["partes_pct"] == {"federal": 66.3, "estados_municipios": 33.7} and i["partes_ano"] is None
    assert i["ao_vivo"]["taxa"] == pytest.approx(136990.0786) and "3,28 tri" in i["base"] and "11:55" in i["base"]
    assert g["total_base"] == pytest.approx(4630886032904.42, abs=1) and set(g["por_esfera"]) == {"U", "E", "M"}
    assert g["referencia_url"] == "https://gastobrasil.com.br/" and "4,63 tri" in g["base"]
    json.dumps(out)


def test_conferir_aceita_leitura_boa_e_barra_numero_estranho(fonte):
    imp, gas = ce.ler_impostometro(), ce.ler_gastometro()
    assert ce.conferir(imp, gas, AGORA) == []
    assert any("a mais de" in e for e in ce.conferir(imp, gas, AGORA + timedelta(hours=8)))  # hora publicada velha
    imp["uniao"]["total"] = imp["brasil"]["total"] * 2
    assert any("União aparece" in e for e in ce.conferir(imp, gas, AGORA))
    gas["estados"]["total"] *= 3  # soma não fecha com o total
    assert any("não fecha" in e for e in ce.conferir(None, gas, AGORA))


def test_numero_invalido_da_fonte_e_recusado(fonte):
    fonte["/api/impostometro/brasil"] = {**BRASIL, "Incremento": 0}
    with pytest.raises(ValueError):
        ce.ler_impostometro()


def test_robo_grava_e_mantem_a_ultima_leitura_da_fonte_que_falhou(tmp_path, fonte, monkeypatch):
    agora = datetime.now(timezone.utc)
    quando = agora.astimezone(ce.BRASILIA).replace(tzinfo=None).isoformat()
    fonte["/api/impostometro/brasil"] = {**BRASIL, "Data": quando}
    fonte["/api/impostometro/uniao"] = {**UNIAO, "Data": quando}
    fonte["/api/trpc/counters.spending"] = {"result": {"data": {**SPENDING["result"]["data"], "as_of": agora.isoformat()}}}
    contadores_rapido.main([str(tmp_path)])
    arq = tmp_path / "contadores_externos.json"
    primeiro = json.loads(arq.read_text(encoding="utf-8"))
    assert primeiro["impostometro"] and primeiro["gastometro"] and primeiro["avisos"] == []
    def fora():
        raise ConnectionError("fora do ar")
    monkeypatch.setattr(ce, "ler_gastometro", fora)
    contadores_rapido.main([str(tmp_path)])
    segundo = json.loads(arq.read_text(encoding="utf-8"))
    assert segundo["gastometro"] == primeiro["gastometro"] and segundo["avisos"] and "ConnectionError" in segundo["avisos"][0]
    monkeypatch.setattr(ce, "ler_impostometro", fora)
    with pytest.raises(SystemExit):  # as duas fontes fora: nada é gravado
        contadores_rapido.main([str(tmp_path)])
    assert json.loads(arq.read_text(encoding="utf-8")) == segundo


def test_api_usa_a_leitura_recente_e_ignora_a_velha(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app
    from app.routers import v03
    arq = tmp_path / "contadores_externos.json"
    monkeypatch.setenv("CONTADORES_EXTERNOS", str(arq))
    ext = {"atualizado_em": datetime.now(timezone.utc).isoformat(), "impostometro": {"total_base": 123.0, "por_segundo": 4.5, "fonte": "teste"},
           "gastometro": {"total_base": 678.0, "por_segundo": 9.0}}
    arq.write_text(json.dumps(ext), encoding="utf-8")
    c = TestClient(app).get("/contadores").json()
    assert c["impostometro"]["total_base"] == 123.0 and c["impostometro"]["fonte"] == "teste" and c["gastometro"]["por_segundo"] == 9.0
    assert v03._externos(datetime.now(timezone.utc) + timedelta(hours=13)) is None  # leitura velha não vale
    arq.write_text("{ quebrado", encoding="utf-8")
    assert v03._externos() is None
