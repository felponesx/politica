"""Catástrofes e acidentes: cadastro com fonte, contagem por ocorrência na PRF e notícias de catástrofes."""
import csv
import io
import json

from app import catastrofes
from app.collectors import noticias, prf
from app.db import SessionLocal, criar_tabelas
from app.models import Registro


def test_cadastro_todo_com_fonte_https_e_sem_fonte_e_descartado(tmp_path, monkeypatch):
    arq = tmp_path / "c.json"
    arq.write_text(json.dumps([
        {"id": "a", "data": "2020-01-01", "titulo": "Com fonte", "local": "X", "uf": "SP", "tipo": "aviao", "mortos": 3, "fontes": [{"nome": "x", "url": "https://x.gov.br/a"}]},
        {"id": "b", "data": "2021-01-01", "titulo": "Sem fonte", "local": "Y", "uf": "RJ", "tipo": "aviao", "mortos": 9, "fontes": []},
    ]), encoding="utf-8")
    monkeypatch.setattr(catastrofes, "CADASTRO", arq)
    d = catastrofes.tragedias()
    assert [x["id"] for x in d["itens"]] == ["a"] and d["descartados"] == 1


def test_cadastro_real_tem_so_fontes_validas():
    d = catastrofes.tragedias()
    assert d["total"] >= 8 and d["descartados"] == 0
    for x in d["itens"]:
        assert x["mortos"] is not None and x["fontes"] and all(f["url"].startswith("https://") for f in x["fontes"])


def _csv(linhas):
    cab = ["id", "uf", "data_inversa", "tipo_veiculo", "tipo_envolvido", "mortos", "feridos_leves", "feridos_graves", "ilesos"]
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(cab)
    w.writerows(linhas)
    buf.seek(0)
    r = csv.reader(buf, delimiter=";")
    return r, [c.strip().lower() for c in next(r)]


def test_agregar_conta_ocorrencia_uma_vez_por_categoria():
    linhas = [
        # ocorrência 1: moto e pedestre (conta em motociclista e em pedestre; 1 morto no pedestre)
        ["1", "SP", "2025-01-01", "Motocicleta", "Condutor", "0", "0", "0", "1"],
        ["1", "SP", "2025-01-01", "NA", "Pedestre", "1", "0", "0", "0"],
        # ocorrência 1 de novo com passageiro de moto: não duplica a ocorrência na categoria
        ["1", "SP", "2025-01-01", "Motocicleta", "Passageiro", "0", "0", "0", "1"],
        # ocorrência 2: só carro
        ["2", "SP", "2025-01-02", "Automóvel", "Condutor", "0", "0", "0", "1"],
        # ocorrência 3 em MG: caminhão-trator
        ["3", "MG", "2025-01-03", "Caminhão-trator", "Condutor", "2", "0", "0", "0"],
    ]
    r, cab = _csv(linhas)
    ag = prf.agregar_pessoas(r, cab)
    sp = ag["por_uf"]["SP"]
    assert sp["acidentes"] == 2
    assert sp["categorias"]["motociclista"]["ocorrencias"] == 1 and sp["categorias"]["motociclista"]["pessoas"] == 1
    assert sp["categorias"]["pedestre"]["ocorrencias"] == 1 and sp["categorias"]["pedestre"]["mortos"] == 1
    assert sp["categorias"]["motorista_carro"]["ocorrencias"] == 1
    mg = ag["por_uf"]["MG"]
    assert mg["categorias"]["caminhao_carreta"]["ocorrencias"] == 1 and mg["categorias"]["caminhao_carreta"]["mortos"] == 2
    assert ag["acidentes"] == 3


def test_rodovias_porcentagem_sobre_acidentes_do_estado():
    criar_tabelas()
    dados = {"ano": 2025, "acidentes": 4, "por_uf": {"SP": {"acidentes": 4, "pessoas": 8, "mortos": 1, "feridos": 3, "ilesos": 4, "categorias": {
        "pedestre": {"ocorrencias": 1, "pessoas": 1, "mortos": 1},
        "motociclista": {"ocorrencias": 2, "pessoas": 2, "mortos": 0},
        "motorista_carro": {"ocorrencias": 3, "pessoas": 3, "mortos": 0},
        "caminhao_carreta": {"ocorrencias": 0, "pessoas": 0, "mortos": 0},
        "onibus": {"ocorrencias": 0, "pessoas": 0, "mortos": 0},
        "bicicleta": {"ocorrencias": 0, "pessoas": 0, "mortos": 0}}}}}
    with SessionLocal() as db:
        db.query(Registro).filter(Registro.fonte == "prf", Registro.tipo.in_(["pessoas_ano", "acidentes_ano"])).delete()
        db.add(Registro(fonte="prf", tipo="pessoas_ano", chave="2025", titulo="t", valor=4.0, dados=dados))
        db.commit()
        try:
            d = catastrofes.rodovias(db)
        finally:
            db.query(Registro).filter(Registro.fonte == "prf", Registro.tipo.in_(["pessoas_ano", "acidentes_ano"])).delete()
            db.commit()
    sp = [e for e in d["estados"] if e["uf"] == "SP"][0]
    assert sp["acidentes"] == 4 and sp["mortos"] == 1 and sp["feridos"] == 3 and sp["ilesos"] == 4
    assert sp["categorias"]["motorista_carro"]["pct"] == 75.0 and sp["categorias"]["pedestre"]["pct"] == 25.0
    assert d["parcial"] is False


def test_feeds_de_catastrofe_tem_nome_proprio_e_veiculo_do_source():
    nomes = [f[0] for f in noticias.FEEDS if f[3] == "catastrofe"]
    assert len(nomes) >= 4 and len(set(nomes)) == len(nomes)
    xml = ('<rss><item><title>Avião cai em Minas - UOL</title><link>https://x.com/a</link>'
           '<source url="https://uol.com.br">UOL</source><pubDate>Mon, 01 Jan 2026 10:00:00 GMT</pubDate></item></rss>')
    itens = noticias.ler_feed(xml, "Catástrofes 0", True, "catastrofe")
    assert itens[0]["veiculo"] == "UOL" and itens[0]["titulo"] == "Avião cai em Minas" and itens[0]["tema"] == "catastrofe"


def test_repasses_filtra_defesa_civil_e_soma_valores_com_virgula():
    from app.collectors import defesa_civil_transf as dc
    cab = ["ANO / MÊS", "TIPO TRANSFERÊNCIA", "UF", "NOME SUBFUNÇÃO", "NOME AÇÃO", "VALOR TRANSFERIDO"]
    linhas = [
        ["202410", "Legais", "RS", "Defesa civil", "ACOES DE PROTECAO E DEFESA CIVIL", "1000,50"],
        ["202410", "Legais", "RS", "Saúde", "ATENCAO BASICA", "999,00"],               # fora: não é defesa civil
        ["202410", "Voluntárias", "RS", "Segurança pública", "RESPOSTA A DESASTRES", "-300,25"],  # estorno real
        ["202410", "Legais", "SC", "Segurança pública", "OUTRA ACAO", "50"],           # fora: sem palavra-chave
        ["202410", "Legais", "XX", "Defesa civil", "ACOES DE PROTECAO E DEFESA CIVIL", "10"],     # UF inválida
    ]
    ag = dc.agregar(linhas, cab)
    assert list(ag) == ["RS"]
    assert ag["RS"]["valor"] == 700.25 and ag["RS"]["linhas"] == 2
    assert ag["RS"]["por_tipo"] == {"Legais": 1000.5, "Voluntárias": -300.25}


def test_transferencias_sem_dado_do_ano_devolve_nulo_nao_zero(db=None):
    from app.catastrofes import tragedias
    d = tragedias(None, None)  # sem banco: nenhum ano coletado
    assert all(x["repasse_federal"] is None for x in d["itens"])
