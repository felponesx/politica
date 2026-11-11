"""Fontes cadastradas em CSV, XML e ZIP: o BRASIL+ lê cada formato pelo mesmo adaptador genérico e grava em `registros`."""
import hashlib
import io
import json
import zipfile

import pytest

from app.collectors import coletor_externo
from app.db import SessionLocal
from app.models import Coleta, Registro


def _publicar(pasta, fonte, corpo: bytes, arquivo: str, formato: str, mapa: dict):
    d = pasta / "dados" / fonte
    d.mkdir(parents=True, exist_ok=True)
    (d / arquivo).write_bytes(corpo)
    meta = {"fonte": fonte, "vinculo": "BRASIL+", "url": "https://dados.exemplo.gov.br/x", "sha256": hashlib.sha256(corpo).hexdigest(),
            "sha256_original": hashlib.sha256(corpo).hexdigest(), "corrigido": False, "regras": [], "alteracoes": 0,
            "bytes": len(corpo), "coletado_em": "2026-11-11T12:00:00+00:00", "veredito": "ok", "decisao": "auto",
            "arquivo": arquivo, "adaptador": "linhas", "mapa": mapa, "formato": formato}
    (d / "meta.json").write_text(json.dumps(meta))


def _limpar(fontes):
    db = SessionLocal()
    try:
        db.query(Registro).filter(Registro.fonte.in_(fontes)).delete(synchronize_session=False)
        db.query(Coleta).filter(Coleta.fonte == "coletor", Coleta.tarefa == "ingestao").delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


def _registros(fonte):
    db = SessionLocal()
    try:
        return {r.chave: r for r in db.query(Registro).filter(Registro.fonte == fonte).all()}
    finally:
        db.close()


@pytest.fixture(autouse=True)
def limpo():
    _limpar(["exemplo-csv", "exemplo-xml", "exemplo-zip"])
    yield
    _limpar(["exemplo-csv", "exemplo-xml", "exemplo-zip"])


MAPA = {"tipo": "exemplo", "chave": "id", "valor": "valor", "titulo": "descricao", "uf": "uf"}


def test_csv_com_ponto_e_virgula_e_acentos(tmp_path):
    corpo = "id;descricao;valor;uf\n1;Conceição Ação;12,5;SP\n2;Município;3;RJ\n".encode("utf-8")
    _publicar(tmp_path, "exemplo-csv", corpo, "atual.csv", "csv", MAPA)
    assert coletor_externo.coletar_ingestao(str(tmp_path)) == 2
    r = _registros("exemplo-csv")
    assert set(r) == {"1", "2"} and r["1"].titulo == "Conceição Ação" and r["2"].uf == "RJ"


def test_xml_com_lista_dentro_do_arquivo(tmp_path):
    corpo = ("<registros><registro id=\"10\"><descricao>Obra A</descricao><valor>7</valor><uf>MG</uf></registro>"
             "<registro id=\"11\"><descricao>Obra B</descricao><valor>8</valor><uf>PR</uf></registro></registros>").encode("utf-8")
    mapa = {**MAPA, "lista": "registro"}
    _publicar(tmp_path, "exemplo-xml", corpo, "atual.xml", "xml", mapa)
    assert coletor_externo.coletar_ingestao(str(tmp_path)) == 2
    r = _registros("exemplo-xml")
    assert set(r) == {"10", "11"} and r["11"].uf == "PR"


def test_zip_com_csv_dentro(tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("dados.csv", "id,descricao,valor,uf\n5,Algo,1,BA\n6,Outro,2,CE\n")
    _publicar(tmp_path, "exemplo-zip", buf.getvalue(), "atual.zip", "zip", MAPA)
    assert coletor_externo.coletar_ingestao(str(tmp_path)) == 2
    assert set(_registros("exemplo-zip")) == {"5", "6"}


def test_zip_que_explode_e_recusado(tmp_path, monkeypatch):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("grande.csv", "id\n" + "1\n" * 1000)
    monkeypatch.setattr(coletor_externo, "LIMITE_ARQUIVO", 100)
    _publicar(tmp_path, "exemplo-zip", buf.getvalue(), "atual.zip", "zip", MAPA)
    with pytest.raises(RuntimeError, match="grande demais"):
        coletor_externo.coletar_ingestao(str(tmp_path))
    assert _registros("exemplo-zip") == {}
