import json
import os

import pytest

from app import profissoes as P
from app.collectors import rais_profissoes as C

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "rais_ni_2025_amostra.csv")


def _lista(ano_arquivos):
    """Simula a pasta de cada ano no FTP."""
    return lambda pasta: ano_arquivos.get(pasta, [])


def test_escolhe_2025_quando_completo():
    completo = list(C.ARQUIVOS_REGIONAIS)
    ano = C.escolher_ano(["2024", "2025"], _lista({"2025": completo, "2024": completo}))
    assert ano == 2025


def test_cai_para_2024_quando_2025_incompleto():
    incompleto = list(C.ARQUIVOS_REGIONAIS)[:-1]
    completo = list(C.ARQUIVOS_REGIONAIS)
    ano = C.escolher_ano(["2024", "2025"], _lista({"2025": incompleto, "2024": completo}))
    assert ano == 2024


def test_falha_sem_nenhum_ano_completo():
    with pytest.raises(C.ColetaIncompleta):
        C.escolher_ano(["2025"], _lista({"2025": []}))


def test_percentis_do_acumulador_com_nearest_rank():
    acc = P.Acumulador()
    for i in range(100):
        acc.add("1234", 1000 + i, 5)  # 1000..1099
    r = acc.resultado()["1234"]
    assert r["minimo"] == 1000 and r["maximo"] == 1099
    assert abs(r["media"] - 1049.5) < 1e-9
    # precisão de R$ 10: o valor do degrau do percentil
    assert abs(r["p10"] - 1000) <= P.PASSO_FAIXA_REM
    assert abs(r["p90"] - 1080) <= P.PASSO_FAIXA_REM


def test_acumulador_suprime_profissao_pequena_e_ignora_invalidos():
    acc = P.Acumulador()
    for _ in range(P.MINIMO_VINCULOS - 1):
        acc.add("9999", 1500.0, 5)
    acc.add(None, 1500.0, 5)
    acc.add("8888", -10.0, 5)
    assert acc.resultado() == {}


def test_recusa_documento_com_poucos_vinculos():
    acc = P.Acumulador()
    acc.add("717020", 1500.0, 5)
    with pytest.raises(C.ColetaIncompleta):
        C.montar_documento(2025, acc, {"x.7z": 1})


def test_nao_troca_ano_novo_por_antigo(tmp_path):
    destino = tmp_path / "p.json"
    destino.write_text(json.dumps({"ano_referencia": 2025}), encoding="utf-8")
    doc = {"ano_referencia": 2024, "profissoes": {}}
    with pytest.raises(C.ColetaIncompleta):
        C.gravar_se_valido(doc, destino)
    assert json.loads(destino.read_text(encoding="utf-8"))["ano_referencia"] == 2025


def test_grava_de_forma_atomica(tmp_path):
    destino = tmp_path / "p.json"
    doc = {"ano_referencia": 2025, "profissoes": {}}
    C.gravar_se_valido(doc, destino)
    assert json.loads(destino.read_text(encoding="utf-8"))["ano_referencia"] == 2025
    assert not (tmp_path / "p.json.tmp").exists()


def test_arquivo_real_de_amostra_passa_pelo_acumulador(tmp_path):
    py7zr = pytest.importorskip("py7zr")
    caminho = tmp_path / "RAIS_VINC_PUB_NI.7z"
    with open(FIXTURE, "rb") as fh:
        conteudo = fh.read()
    with py7zr.SevenZipFile(caminho, "w") as z:
        z.writestr(conteudo, "RAIS_VINC_PUB_NI.COMT")
    acc = P.Acumulador()
    trouxe = C.agregar_arquivo(caminho, acc)
    assert trouxe == 6
    assert set(acc.prof) == {"717020", "621005", "715505", "724315"}
