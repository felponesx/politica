import os
import zipfile

os.environ.setdefault("DATABASE_URL", "sqlite:///./teste.db")

from app.collectors import empresas_porte as ep  # noqa: E402
from app.db import criar_tabelas  # noqa: E402

criar_tabelas()


def _zip(caminho, nome, linhas):
    with zipfile.ZipFile(caminho, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(nome, "\n".join(linhas).encode("latin-1"))


def _estab(basico, matriz, sit, uf, cnae, especial=""):
    campos = [basico, "0001", "00", matriz, "FANTASIA", sit] + [""] * 5 + [cnae] + [""] * 7 + [uf, "7107"] + [""] * 7 + [especial, "20240101" if especial else ""]
    return ";".join(f'"{c}"' for c in campos)


def _emp(basico, nome, porte, capital="1000,00"):
    return ";".join(f'"{c}"' for c in [basico, nome, "2062", "49", capital, porte, ""])


def test_conta_por_porte_dividas_rj_e_falencia(tmp_path, monkeypatch):
    cnpj = tmp_path / "cnpj"
    cnpj.mkdir()
    _zip(cnpj / "Estabelecimentos0.zip", "e.csv", [
        _estab("00000001", "1", "02", "SP", "4711301"),                          # MEI ativa
        _estab("00000002", "1", "02", "RJ", "4120400"),                          # ME ativa, devedora
        _estab("00000003", "1", "02", "MG", "6422100", "RECUPERACAO JUDICIAL"),  # grande em RJ, devedora
        _estab("00000004", "1", "08", "SP", "4711301"),                          # baixada: não conta
        _estab("00000005", "1", "02", "PR", "1011201", "FALIDO"),                # EPP falida
    ])
    _zip(cnpj / "Simples.zip", "s.csv", ['"00000001";"S";"20200101";"";"S";"20200101";""'])
    _zip(cnpj / "Empresas0.zip", "m.csv", [_emp("00000001", "JOAO MEI", "01"), _emp("00000002", "PADARIA X", "01"),
                                           _emp("00000003", "GRANDE SA", "05", "5000000000,00"),
                                           _emp("00000004", "VELHA", "01"), _emp("00000005", "MEDIA LTDA", "03")])
    _zip(cnpj / "Cnaes.zip", "c.csv", ['"6422100";"Bancos múltiplos, com carteira comercial"'])
    pgfn = tmp_path / "pgfn.zip"
    cab = "CPF_CNPJ;TIPO_PESSOA;TIPO_DEVEDOR;NOME_DEVEDOR;UF_DEVEDOR;INDICADOR_AJUIZADO;VALOR_CONSOLIDADO"
    _zip(pgfn, "p.csv", [cab, "00.000.002/0001-00;Pessoa jurídica;PRINCIPAL;PADARIA X;RJ;NAO;5000,00",
                         "00.000.003/0001-00;Pessoa jurídica;PRINCIPAL;GRANDE SA;MG;SIM;2000000,00",
                         "00.000.003/0001-00;Pessoa jurídica;CORRESPONSAVEL;GRANDE SA;MG;SIM;2000000,00",
                         "123.456.789-00;Pessoa física;PRINCIPAL;FULANO;SP;NAO;100,00"])
    monkeypatch.setattr(ep, "N", 10)
    ep.coletar_empresas_porte(mes="2026-09", pasta_local=str(cnpj), pgfn_local=str(pgfn), paralelo=2)
    from app.db import SessionLocal
    from app.models import Registro
    with SessionLocal() as db:
        r = db.query(Registro).filter_by(fonte="receita", tipo="empresas_porte", chave="2026-09").one()
    p = r.dados["por_porte"]
    assert p["MEI"]["total"] == 1 and p["Microempresa"]["total"] == 1
    assert p["Microempresa"]["com_divida"] == 1 and p["Microempresa"]["divida_total"] == 5000
    assert p["Demais (médias e grandes)"] == {"total": 1, "com_divida": 1, "recuperacao_judicial": 1, "falidas": 0,
                                               "divida_total": 2000000.0}
    assert p["Empresa de pequeno porte"]["falidas"] == 1
    assert r.valor == 4  # a baixada não entra
    top = r.dados["maiores_devedoras"][0]
    assert top["nome"] == "GRANDE SA" and top["divida_uniao"] == 2000000 and top["recuperacao_judicial"]
    assert top["atividade"] == "Bancos múltiplos, com carteira comercial" and top["uf"] == "MG"
    assert r.dados["maiores_empresas"][0]["cnpj_basico"] == "00000003"
