"""Valor de obra que parece erro de cadastro: fica visível, mas marcado e fora das somas."""
from datetime import date
from types import SimpleNamespace

import pytest

from app.obras_gestao import CAMPOS_LISTA, lista_compacta, resumir
from app.obras_valor import valor_suspeito

BI = 1e9


@pytest.mark.parametrize("nome,tipo,valor,esperado", [
    ("Dragagem do Porto de Paranaguá.", None, 403.6 * BI, True),                      # 403 bi: sempre
    ("Construção do novo bloco de centro cirúrgico do Hospital Universitário", "Saúde", 81.3 * BI, True),
    ("Construção da nova sede da 12ª Delegacia de Polícia do DF.", "Segurança Pública", 15.8 * BI, True),
    ("Aquisição de Aeronaves de Caça - Projeto FX-2", "Defesa Nacional", 26.9 * BI, False),  # defesa vale bilhões
    ("Estaleiro e Base Naval", "Defesa Nacional", 9.3 * BI, False),
    ("Implantação do Eixo Norte do PISF", None, 7.5 * BI, False),                      # grande obra real
    ("EF 334 - Ferrovia de Integração Oeste Leste - FIOL", None, 8.9 * BI, False),
    ("Bloco Administrativo Pedagógico Campus Avançado", "Educação", 8.4 * BI, True),   # obra pequena com R$ bilhões
    ("Recuperação de estradas em áreas rurais do Município de Rondonópolis", "Infraestrutura Urbana", 9.4 * BI, True),
    ("25387.000434/2020-03 - Obra de Readequação dos Vestiários", "Administrativo", 6.2 * BI, True),
    ("26.782.2087.10JQ.0042", "Rodovia", 1.6 * BI, False),                              # código de ação do DNIT: não dá para dizer
    ("Ponte sobre o Rio Madeira", "Rodovia", 1.2 * BI, False),
    ("Escola municipal", "Educação", 30e6, False),                                      # abaixo de R$ 1 bi nunca é marcada
    ("Obra sem valor", None, None, False),
])
def test_regra_de_valor_suspeito(nome, tipo, valor, esperado):
    assert valor_suspeito(nome, None, tipo, valor) is esperado


def _o(i, sit, valor, nome="Obra", tipo=None, fim=date(2030, 1, 1)):
    return SimpleNamespace(id=i, situacao=sit, valor_previsto=valor, fim_previsto=fim, nome=nome, descricao=None, executor="Prefeitura Municipal de X (SP)", tipo=tipo)


def test_resumo_tira_o_suspeito_das_somas_mas_conta_a_obra():
    obras = [_o(1, "Em execução", 100e6), _o(2, "Em execução", 300e6),
             _o(3, "Em execução", 403e9, nome="Dragagem do Porto de Paranaguá."), _o(4, "Concluída", 100e6)]
    r = resumir(obras, hoje=date(2026, 10, 29))
    assert r["total"] == 4                                    # a obra continua contada
    assert r["valor_total"] == pytest.approx(500e6)           # mas os R$ 403 bi não entram
    execucao = next(s for s in r["situacoes"] if s["chave"] == "execucao")
    assert execucao["quantidade"] == 3 and execucao["valor"] == pytest.approx(400e6)
    assert r["valor_suspeito"]["obras"] == 1 and r["valor_suspeito"]["valor"] == pytest.approx(403e9) and r["valor_suspeito"]["aviso"]


def test_obra_atrasada_suspeita_aparece_sem_valor():
    obras = [_o(1, "Em execução", 50e6, fim=date(2020, 1, 1)),
             _o(2, "Em execução", 500e9, nome="Dragagem do Porto", fim=date(2019, 1, 1))]
    r = resumir(obras, hoje=date(2026, 10, 29))
    assert r["atraso"]["valor"] == pytest.approx(50e6)
    suspeita = next(x for x in r["mais_atrasadas"] if x["id"] == 2)
    assert suspeita["valor"] is None and suspeita["valor_suspeito"] is True


def test_lista_compacta_marca_e_zera_o_valor_suspeito():
    linhas = lista_compacta([_o(1, "Em execução", 100e6), _o(2, "Cadastrada", 81e9, nome="Bloco do centro cirúrgico", tipo="Saúde")])
    por_id = {l[0]: dict(zip(CAMPOS_LISTA, l)) for l in linhas}
    assert por_id[1]["suspeito"] == 0 and por_id[1]["valor"] == 100000000
    assert por_id[2]["suspeito"] == 1 and por_id[2]["valor"] == 0


def test_rotas_marcam_e_excluem_o_valor_suspeito():
    from fastapi.testclient import TestClient

    from app.db import SessionLocal, criar_tabelas
    from app.main import app
    from app.models import Obra, Registro
    criar_tabelas()
    cliente = TestClient(app)
    db = SessionLocal()
    db.query(Obra).filter(Obra.uf == "QQ").delete()
    db.query(Registro).filter(Registro.uf == "QQ").delete()
    db.commit()
    ids = {}
    for chave, nome, valor in (("qq1", "Obra de rotina", 200e6), ("qq2", "Dragagem do Porto de Paranaguá.", 403e9)):
        r = Registro(fonte="obrasgov", tipo="obra", chave=chave, dados={}, uf="QQ")
        db.add(r)
        db.flush()
        o = Obra(registro_id=r.id, id_unico=chave, nome=nome, uf="QQ", situacao="Em execução", valor_previsto=valor)
        db.add(o)
        db.flush()
        ids[chave] = o.id
    db.commit()
    lista = {i["nome"]: i for i in cliente.get("/obras", params={"uf": "QQ"}).json()["itens"]}
    assert lista["Obra de rotina"]["valor_suspeito"] is False and lista["Dragagem do Porto de Paranaguá."]["valor_suspeito"] is True
    detalhe = cliente.get(f"/obras/{ids['qq2']}").json()
    assert detalhe["valor_suspeito"] is True and detalhe["aviso_valor"] and detalhe["valor_previsto"] == 403e9  # o número declarado continua visível
    assert cliente.get(f"/obras/{ids['qq1']}").json()["aviso_valor"] is None
    resumo = cliente.get("/obras-resumo/QQ").json()
    assert resumo[0]["valor_previsto"] == pytest.approx(200e6) and resumo[0]["valor_suspeito_excluido"] == pytest.approx(403e9)
    db.query(Obra).filter(Obra.uf == "QQ").delete()
    db.query(Registro).filter(Registro.uf == "QQ").delete()
    db.commit()
    db.close()
