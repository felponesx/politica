"""Empresas punidas: leitura do CEIS/CNEP/acordos (formato real do Portal da Transparência) e o cruzamento com contratos."""
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.collectors import sancoes as col
from app.db import SessionLocal, criar_tabelas
from app.main import app
from app.models import Contrato, Registro

CEIS = ("CADASTRO;CÓDIGO DA SANÇÃO;TIPO DE PESSOA;CPF OU CNPJ DO SANCIONADO;NOME DO SANCIONADO;NOME INFORMADO PELO ÓRGÃO SANCIONADOR;RAZÃO SOCIAL - CADASTRO RECEITA;"
        "NOME FANTASIA - CADASTRO RECEITA;NÚMERO DO PROCESSO;CATEGORIA DA SANÇÃO;DATA INÍCIO SANÇÃO;DATA FINAL SANÇÃO;DATA PUBLICAÇÃO;PUBLICAÇÃO;DETALHAMENTO DO MEIO DE PUBLICAÇÃO;"
        "DATA DO TRÂNSITO EM JULGADO;ABRAGÊNCIA DA SANÇÃO;ÓRGÃO SANCIONADOR;UF ÓRGÃO SANCIONADOR;ESFERA ÓRGÃO SANCIONADOR;FUNDAMENTAÇÃO LEGAL;DATA ORIGEM INFORMAÇÃO;ORIGEM INFORMAÇÕES;OBSERVAÇÕES\n"
        "CEIS;349678;F;03536018882;JOSE AMARILDO MARTELLI;JOSE;;;0000358;Impedimento/proibição de contratar com poder público;22/10/2024;22/10/2029;;Sem Informação;;22/10/2024;Sem Informação;TJSP;SP;ESTADUAL;LEI 8429;12/05/2025;CNJ;\n"
        "CEIS;1;J;12.345.678/0001-90;CONSTRUTORA X LTDA;CONSTRUTORA X;CONSTRUTORA X LTDA;X;123;Inidoneidade;01/01/2020;;;Sem Informação;;;Sem Informação;CGU;DF;FEDERAL;LEI 8666;01/02/2020;CGU;\n"
        "CEIS;2;J;98765432000100;OUTRA SA;OUTRA;OUTRA S/A;;124;Suspensão;01/01/2018;01/01/2020;;Sem Informação;;;Sem Informação;Prefeitura de Rio Branco;AC;MUNICIPAL;LEI 8666;01/02/2018;PMRB;\n")
CNEP = ("CADASTRO;CÓDIGO DA SANÇÃO;TIPO DE PESSOA;CPF OU CNPJ DO SANCIONADO;NOME DO SANCIONADO;NOME INFORMADO PELO ÓRGÃO SANCIONADOR;RAZÃO SOCIAL - CADASTRO RECEITA;"
        "NOME FANTASIA - CADASTRO RECEITA;NÚMERO DO PROCESSO;CATEGORIA DA SANÇÃO;VALOR DA MULTA;DATA INÍCIO SANÇÃO;DATA FINAL SANÇÃO;DATA PUBLICAÇÃO;PUBLICAÇÃO;DETALHAMENTO DO MEIO DE PUBLICAÇÃO;"
        "DATA DO TRÂNSITO EM JULGADO;ABRAGÊNCIA DA SANÇÃO;ÓRGÃO SANCIONADOR;UF ÓRGÃO SANCIONADOR;ESFERA ÓRGÃO SANCIONADOR;FUNDAMENTAÇÃO LEGAL;DATA ORIGEM INFORMAÇÃO;ORIGEM INFORMAÇÕES;OBSERVAÇÕES\n"
        "CNEP;106565;J;12345678000190;CONSTRUTORA X LTDA;X;CONSTRUTORA X LTDA;;058;Multa;9102,27;18/09/2019;;;Sem Informação;;;No órgão;PREF LAJEADO;RS;MUNICIPAL;LEI 12846;20/12/2019;PM;\n")
ACORDOS = ("ID DO ACORDO;CNPJ DO SANCIONADO;RAZÃO SOCIAL \x96 CADASTRO RECEITA;NOME FANTASIA \x96 CADASTRO RECEITA;DATA DE INÍCIO DO ACORDO;DATA DE FIM DO ACORDO;SITUAÇÃO DO ACORDO DE LENIÊNICA;DATA DA INFORMAÇÃO;NÚMERO DO PROCESSO;TERMOS DO ACORDO;ÓRGÃO SANCIONADOR\n"
           "900001;42150391000170;BRASKEM S.A;BRASKEM;31/05/2019;30/01/2025;Em Execução;;00190;O acordo;Controladoria-Geral da União\n")


def _linhas(texto):
    return col.ler_linhas(texto, 1, "teste")


def test_agregar_so_empresas_com_vigencia_e_multa():
    e = col.agregar({"CEIS": _linhas(CEIS), "CNEP": _linhas(CNEP)}, hoje=date(2026, 10, 30))
    assert set(e) == {"12345678000190", "98765432000100"}  # CPF fica de fora; CNPJ com pontuação é normalizado
    x = e["12345678000190"]
    assert x["cadastros"] == ["CEIS", "CNEP"] and x["vigente"] and x["multa_total"] == 9102.27 and x["n"] == 2 and x["nome"] == "CONSTRUTORA X LTDA"
    assert x["sancoes"][0]["inicio"] == "2020-01-01" or x["sancoes"][0]["inicio"] == "2019-09-18"
    assert not e["98765432000100"]["vigente"]  # terminou em 2020


def test_resumo_e_acordos(monkeypatch):
    monkeypatch.setitem(col.MINIMO, "acordos-leniencia", 1)
    e = col.agregar({"CEIS": _linhas(CEIS), "CNEP": _linhas(CNEP)}, hoje=date(2026, 10, 30))
    a = col.ler_acordos({"20261029_Acordos.csv": ACORDOS.replace("O acordo;Controladoria", "O acordo;Controladoria")})
    assert a[0]["cnpj"] == "42150391000170" and a[0]["inicio"] == "2019-05-31" and a[0]["situacao"] == "Em Execução"
    r = col.resumir(e, a, {"CEIS": "2026-10-29"})
    assert r["empresas"] == 2 and r["vigentes"] == 1 and r["por_cadastro"] == {"CEIS": 2, "CNEP": 1} and r["multa_total_cnep"] == 9102.27
    assert r["maiores_multas"][0]["cnpj"] == "12345678000190"


def test_arquivo_cortado_ou_mudado_nao_grava():
    with pytest.raises(RuntimeError, match="nada foi gravado"):
        col.ler_linhas(CEIS, 10_000, "CEIS")
    with pytest.raises(ValueError, match="mudou"):
        col.agregar({"CEIS": (["A", "B"], [["1", "2"]])})


def test_rotas_e_cruzamento_com_contratos():
    criar_tabelas()
    cliente = TestClient(app)
    with SessionLocal() as db:
        db.query(Contrato).filter(Contrato.numero_controle.like("SANC-%")).delete(synchronize_session=False)
        db.query(Registro).filter(Registro.fonte == "cgu").delete()
        db.commit()
    from app.utils import _MEMO
    _MEMO.clear()
    assert cliente.get("/sancoes").status_code == 404
    e = col.agregar({"CEIS": _linhas(CEIS), "CNEP": _linhas(CNEP)}, hoje=date(2026, 10, 30))
    with SessionLocal() as db:
        for cnpj, x in e.items():
            db.add(Registro(fonte="cgu", tipo="sancao_empresa", chave=cnpj, titulo=x["nome"], dados=x))
        db.add(Registro(fonte="cgu", tipo="sancoes_resumo", chave="BR", dados=col.resumir(e, [], {})))
        for i, (cnpj, d) in enumerate([("12345678000190", date(2021, 5, 1)), ("12345678000190", date(2019, 1, 1)), ("98765432000100", date(2018, 6, 1))]):
            r = Registro(fonte="pncp", tipo="contrato", chave=f"SANC-{i}", dados={})
            db.add(r)
            db.flush()
            db.add(Contrato(registro_id=r.id, fonte="pncp", numero_controle=f"SANC-{i}", fornecedor="X", cnpj_fornecedor=cnpj, valor=1000.0 * (i + 1), data_assinatura=d, ano=d.year))
        db.commit()
    try:
        _MEMO.clear()
        assert cliente.get("/sancoes").json()["empresas"] == 2
        d = cliente.get("/sancoes/contratos").json()
        por = {x["cnpj"]: x for x in d["itens"]}
        assert d["empresas_com_contrato"] == 2 and por["12345678000190"]["contratos"] == 2 and por["12345678000190"]["contratos_durante_sancao"] == 1
        assert por["98765432000100"]["contratos_durante_sancao"] == 1 and "aviso" in d
        assert cliente.get("/sancoes/12.345.678%2F0001-90").json()["multa_total"] == 9102.27
        assert cliente.get("/sancoes/11111111000111").status_code == 404
        assert [x["cnpj"] for x in cliente.get("/sancoes/busca?q=construtora").json()["itens"]] == ["12345678000190"]
    finally:
        with SessionLocal() as db:
            db.query(Contrato).filter(Contrato.numero_controle.like("SANC-%")).delete(synchronize_session=False)
            db.query(Registro).filter(Registro.fonte.in_(["cgu", "pncp"]), Registro.chave.like("SANC-%") | (Registro.fonte == "cgu")).delete(synchronize_session=False)
            db.commit()
        _MEMO.clear()


def test_tcu_inabilitados_resumo_so_totais_e_guarda():
    from datetime import date

    from app.collectors import tcu
    itens = [{"nome": "FULANO", "cpf": "1", "uf": "MA", "data_final": "2027-07-16T03:00:00Z", "data_acordao": "2022-04-06T17:30:00Z"},
             {"nome": "BELTRANO", "cpf": "2", "uf": "MA", "data_final": "2020-01-01T03:00:00Z", "data_acordao": "2015-04-06T17:30:00Z"},
             {"nome": "CICLANO", "cpf": "3", "uf": "SP", "data_final": None, "data_acordao": None}]
    r = tcu.resumir(itens, hoje=date(2026, 10, 30))
    assert r["total"] == 3 and r["ativos"] == 1 and r["por_uf"]["MA"] == {"total": 2, "ativos": 1} and r["por_ano"] == {"2015": 1, "2022": 1}
    assert "FULANO" not in str(r) and "cpf" not in str(r).lower()


def test_cnj_jn_le_tribunais_por_ano_e_acha_o_zip_certo():
    from app.collectors import cnj
    csv_jn = "ano;justica;sigla;cn;cp;tbaix;tc;mag\n2023;Estadual;TJAC;1000;5.000,5;900;55,2;nd\n2024;Estadual;TJAC;1100;5000;1200;48,0;30\n2024;Federal;TRF1;7;8;9;nd;1\n"
    r = cnj.ler_jn(csv_jn)
    assert r["TJAC"]["anos"]["2023"] == {"cn": 1000.0, "cp": 5000.5, "tbaix": 900.0, "tc": 55.2} and r["TJAC"]["anos"]["2024"]["mag"] == 30.0
    assert r["TRF1"]["justica"] == "Federal" and "tc" not in r["TRF1"]["anos"]["2024"]
    html = '<a href="/wp-content/uploads/2026/06/dea-jn2026.zip">x</a><a href="https://www.cnj.jus.br/wp-content/uploads/2026/09/17-set-2026.zip">y</a><a href="/wp-content/uploads/2024/08/basejn-03-jun-2024.zip">z</a>'
    assert cnj.links_de_zip(html)[0].endswith("2026/09/17-set-2026.zip") and not any("dea-jn" in u for u in cnj.links_de_zip(html))
    import pytest
    with pytest.raises(ValueError):
        cnj.ler_jn("a;b\n1;2\n")
