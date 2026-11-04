"""Ingestão dos dados liberados pelo coletor do celular (app/collectors/coletor_externo.py)."""
import hashlib
import json

import pytest

from app.collectors import coletor_externo
from app.db import SessionLocal
from app.models import Coleta, Registro

URL_IPCA = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.433/dados?formato=json"
# formato real do SGS: datas dd/mm/aaaa e valores como texto
IPCA = [{"data": "01/01/2026", "valor": "0.33"}, {"data": "01/02/2026", "valor": "0.70"}, {"data": "01/03/2026", "valor": "0.88"}]


def _publicar(pasta, fonte, dados, url=URL_IPCA, veredito="ok", decisao="auto", **extra):
    """Escreve a pasta como o coletor do celular escreve: dados/<fonte>/atual.json + meta.json."""
    corpo = json.dumps(dados, ensure_ascii=False).encode()
    d = pasta / "dados" / fonte
    d.mkdir(parents=True, exist_ok=True)
    (d / "atual.json").write_bytes(corpo)
    meta = {"fonte": fonte, "vinculo": "BRASIL+", "url": url, "sha256": hashlib.sha256(corpo).hexdigest(),
            "sha256_original": hashlib.sha256(corpo).hexdigest(), "corrigido": False, "regras": [], "alteracoes": 0,
            "bytes": len(corpo), "coletado_em": "2026-11-04T12:00:00+00:00", "veredito": veredito, "decisao": decisao,
            "arquivo": "atual.json", **extra}
    (d / "meta.json").write_text(json.dumps(meta))
    return meta


def _limpar():
    db = SessionLocal()
    try:
        db.query(Registro).filter(Registro.fonte == "bcb", Registro.tipo == "serie:ipca_mes").delete()
        db.query(Coleta).filter(Coleta.fonte == "coletor").delete()
        db.commit()
    finally:
        db.close()


@pytest.fixture(autouse=True)
def limpo():
    _limpar()
    yield
    _limpar()


def _pontos():
    db = SessionLocal()
    try:
        return {r.chave: r for r in db.query(Registro).filter_by(fonte="bcb", tipo="serie:ipca_mes").all()}
    finally:
        db.close()


def _coletas():
    db = SessionLocal()
    try:
        return db.query(Coleta).filter(Coleta.fonte == "coletor", Coleta.tarefa == "ingestao").order_by(Coleta.id).all()
    finally:
        db.close()


def test_ingere_serie_liberada(tmp_path):
    _publicar(tmp_path, "bcb", IPCA)
    assert coletor_externo.coletar_ingestao(str(tmp_path)) == 3
    p = _pontos()
    assert set(p) == {"2026-01-01", "2026-02-01", "2026-03-01"}
    assert p["2026-02-01"].valor == 0.70 and p["2026-02-01"].ano == 2026
    assert p["2026-01-01"].dados["codigo"] == 433 and p["2026-01-01"].dados["unidade"] == "%"
    [c] = _coletas()
    assert c.status == "ok" and c.itens == 3 and c.parametros["bot"] == "bcb"


def test_mesmo_arquivo_nao_e_ingerido_duas_vezes(tmp_path):
    _publicar(tmp_path, "bcb", IPCA)
    coletor_externo.coletar_ingestao(str(tmp_path))
    assert coletor_externo.coletar_ingestao(str(tmp_path)) == 0
    assert len(_coletas()) == 1 and len(_pontos()) == 3


def test_arquivo_novo_atualiza_sem_duplicar(tmp_path):
    _publicar(tmp_path, "bcb", IPCA)
    coletor_externo.coletar_ingestao(str(tmp_path))
    _publicar(tmp_path, "bcb", IPCA[:2] + [{"data": "01/03/2026", "valor": "0.90"}, {"data": "01/04/2026", "valor": "0.40"}])
    assert coletor_externo.coletar_ingestao(str(tmp_path)) == 4
    p = _pontos()
    assert len(p) == 4 and p["2026-03-01"].valor == 0.90


def test_atualiza_linha_que_o_robo_ja_gravou(tmp_path):
    db = SessionLocal()
    db.add(Registro(fonte="bcb", tipo="serie:ipca_mes", chave="2026-01-01", ano=2026, titulo="x", valor=9.99, dados={}))
    db.commit()
    db.close()
    _publicar(tmp_path, "bcb", IPCA)
    coletor_externo.coletar_ingestao(str(tmp_path))
    p = _pontos()
    assert len(p) == 3 and p["2026-01-01"].valor == 0.33


def test_so_entra_o_que_o_corretor_liberou(tmp_path):
    _publicar(tmp_path, "bcb", IPCA, veredito="suspeito", decisao="auto")
    assert coletor_externo.coletar_ingestao(str(tmp_path)) == 0 and not _pontos()
    _publicar(tmp_path, "bcb", IPCA, veredito="suspeito", decisao="rejeitado")
    assert coletor_externo.coletar_ingestao(str(tmp_path)) == 0 and not _pontos()
    _publicar(tmp_path, "bcb", IPCA, veredito="suspeito", decisao="aprovado")   # você aprovou
    assert coletor_externo.coletar_ingestao(str(tmp_path)) == 3


def test_arquivo_adulterado_ou_incompleto_nao_entra(tmp_path):
    _publicar(tmp_path, "bcb", IPCA)
    arq = tmp_path / "dados" / "bcb" / "atual.json"
    arq.write_bytes(arq.read_bytes()[:-5])   # cortado depois do hash
    with pytest.raises(RuntimeError, match="hash"):
        coletor_externo.coletar_ingestao(str(tmp_path))
    assert not _pontos()
    [c] = _coletas()
    assert c.status == "erro" and "hash" in c.erro
    with pytest.raises(RuntimeError):   # a mesma falha não vira uma linha nova a cada rodada
        coletor_externo.coletar_ingestao(str(tmp_path))
    assert len(_coletas()) == 1


def test_serie_desconhecida_falha_sem_derrubar_as_outras(tmp_path):
    _publicar(tmp_path, "bcb", IPCA)
    _publicar(tmp_path, "outra", IPCA, url="https://api.bcb.gov.br/dados/serie/bcdata.sgs.99999/dados")
    # "outra" não tem adaptador: é ignorada, não é erro
    assert coletor_externo.coletar_ingestao(str(tmp_path)) == 3
    # um adaptador que falha por dentro (série fora do cadastro) é erro, e as demais fontes seguem
    coletor_externo.ADAPTADORES["outra"] = coletor_externo._adaptar_bcb
    try:
        with pytest.raises(RuntimeError, match="99999"):
            coletor_externo.coletar_ingestao(str(tmp_path))
    finally:
        del coletor_externo.ADAPTADORES["outra"]
    assert [c.status for c in _coletas() if c.parametros["bot"] == "outra"] == ["erro"]


def test_fonte_sem_adaptador_e_ignorada(tmp_path):
    _publicar(tmp_path, "camara", [{"id": 1}], url="https://dadosabertos.camara.leg.br/api/v2/deputados")
    assert coletor_externo.coletar_ingestao(str(tmp_path)) == 0 and not _coletas()


def test_aceita_copia_corrigida_so_no_formato(tmp_path):
    corrigida = [{"data": "2026-01-01", "valor": "0.33"}, {"data": "2026-02-01", "valor": "0.70"}]   # data_iso aplicada pelo coletor
    _publicar(tmp_path, "bcb", corrigida, corrigido=True, regras=["data_iso:data"], alteracoes=2)
    assert coletor_externo.coletar_ingestao(str(tmp_path)) == 2
    assert _pontos()["2026-02-01"].valor == 0.70
    assert _coletas()[0].parametros["corrigido"] == "True"


def test_meta_de_outra_fonte_ou_com_caminho_perigoso_e_recusado(tmp_path):
    _publicar(tmp_path, "bcb", IPCA, arquivo="../../etc/passwd")
    with pytest.raises(RuntimeError, match="inválido"):
        coletor_externo.coletar_ingestao(str(tmp_path))
    assert not _pontos()


def test_pasta_inexistente(tmp_path):
    with pytest.raises(FileNotFoundError):
        coletor_externo.coletar_ingestao(str(tmp_path / "nao-existe"))


def test_tarefa_esta_no_registro_e_na_tela_de_situacao():
    from app.collectors import TAREFAS
    from app.collectors.registro import registro_das_tarefas
    assert "coletor-ingestao" in TAREFAS
    assert registro_das_tarefas()["coletor-ingestao"] == ("coletor", "ingestao")
