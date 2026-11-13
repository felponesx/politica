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


class _FTPQueCai:
    """Simula um FTP que cai na primeira transferência e retoma com REST na segunda."""

    def __init__(self, dados):
        self.dados = dados
        self.chamadas = 0

    def cwd(self, _):
        pass

    def size(self, _):
        return len(self.dados)

    def retrbinary(self, _cmd, escreve, blocksize=0, rest=None):
        self.chamadas += 1
        inicio = rest or 0
        if self.chamadas == 1:
            escreve(self.dados[inicio:inicio + 100])
            raise TimeoutError("caiu no meio")
        escreve(self.dados[inicio:])

    def quit(self):
        pass

    def close(self):
        pass


def test_download_retoma_do_ponto_em_que_parou(tmp_path, monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    dados = bytes(range(256)) * 2000
    ftp = _FTPQueCai(dados)
    monkeypatch.setattr(C, "conectar", lambda: ftp)  # a nova tentativa usa a mesma "conexão" simulada
    destino = tmp_path / "RAIS_VINC_PUB_TESTE.7z"
    C.baixar_regional(ftp, 2025, "RAIS_VINC_PUB_TESTE.7z", destino)
    assert destino.read_bytes() == dados
    assert ftp.chamadas == 2


def test_nova_conexao_recusada_nao_quebra_a_retomada(tmp_path, monkeypatch):
    """O servidor recusou a reconexão na vida real: o laço tem de tentar de novo, não estourar."""
    monkeypatch.setattr("time.sleep", lambda s: None)
    dados = bytes(range(256)) * 1000
    ftp_ok = _FTPQueCai(dados)
    chamadas = {"n": 0}

    def conectar_instavel():
        chamadas["n"] += 1
        if chamadas["n"] == 1:
            raise ConnectionResetError("recusada")
        return ftp_ok

    monkeypatch.setattr(C, "conectar", conectar_instavel)
    destino = tmp_path / "RAIS_VINC_PUB_TESTE.7z"
    C.baixar_regional(ftp_ok, 2025, "RAIS_VINC_PUB_TESTE.7z", destino)
    assert destino.read_bytes() == dados


def test_fechar_aceita_conexao_morta():
    class Morta:
        def quit(self):
            raise AttributeError("sock None")

        def close(self):
            raise OSError("já fechada")

    C._fechar(Morta())  # não pode levantar
    C._fechar(None)


def test_ano_novo_completo_entra_e_parcial_nao():
    completo = list(C.ARQUIVOS_REGIONAIS)
    lista = _lista({"2026": completo, "2025": completo, "2027": completo[:3]})
    assert C.escolher_ano(["2025", "2026", "2027", "Layouts"], lista) == 2026  # 2027 pela metade fica de fora
