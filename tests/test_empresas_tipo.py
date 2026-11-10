"""Tipo das empresas (pública, economia mista, privada, concessão) e CNPJ da matriz."""
from app import empresas_tipo as T


def test_tipo_por_natureza_juridica():
    assert T.tipo_por_natureza(2011) == "empresa_publica"      # Caixa, Correios
    assert T.tipo_por_natureza("2038") == "economia_mista"     # Petrobras, Banco do Brasil
    assert T.tipo_por_natureza(2046) == "privada"              # S.A. aberta (Sabesp depois de 2024)
    assert T.tipo_por_natureza(2062) == "privada"              # Ltda
    assert T.tipo_por_natureza(2143) == "cooperativa"
    assert T.tipo_por_natureza(1104) == "entidade_publica"     # autarquia federal
    assert T.tipo_por_natureza(3999) == "sem_fins_lucrativos"
    assert T.tipo_por_natureza(None) is None and T.tipo_por_natureza("x") is None


def test_concessao_pela_atividade():
    assert T.concessao("3600601") == "Água e esgoto"
    assert T.concessao(3514000) == "Energia (distribuição)"
    assert T.concessao("5221-4/00") == "Rodovias"
    assert T.concessao("4711301") is None  # supermercado


def test_controle_e_governo():
    assert T.controle_cvm("Estatal Holding") == "estatal" and T.controle_cvm("PRIVADO") == "privado" and T.controle_cvm("Estrangeiro") == "estrangeiro"
    assert T.do_governo({"tipo": "privada", "controle": "estatal"})  # S.A. controlada por estatal (ex.: BB Seguridade)
    assert not T.do_governo({"tipo": "privada", "controle": "privado"})


def test_cnpj_matriz_com_digitos():
    assert T.cnpj_matriz("33000167") == "33000167000101"   # Petrobras
    assert T.cnpj_matriz("00000000") == "00000000000191"   # Banco do Brasil
    assert T.cnpj_matriz("43776517") == "43776517000180"   # Sabesp
