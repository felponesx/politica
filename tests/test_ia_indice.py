"""Índice da IA: rankings feitos a partir das respostas guardadas na cópia estática."""
from app.ia_indice import CARGOS, montar


def _eleicao(ano, uf, cargo, turno, eleitos, mais=None):
    return {"ano": ano, "uf": uf, "cargo": cargo, "turno": turno, "eleitos": eleitos, "mais_votados": mais or eleitos}


def _e(sq, nome, votos, partido="PT", situacao="ELEITO", unidade=None):
    return {"sq_candidato": sq, "nome": nome, "partido": partido, "votos": votos, "situacao": situacao, "unidade": unidade}


def test_indice_ia():
    dados = {
        "/parlamentares": {"itens": [{"id": 1, "nome": "Ana", "partido": "PT", "uf": "SP", "casa": "camara"},
                                     {"id": 2, "nome": "Bia", "partido": "PL", "uf": "RJ", "casa": "senado"},
                                     {"id": 3, "nome": "Caio", "partido": "PL", "uf": "SP", "casa": "al-sp"}]},
        "/parlamentares/1": {"total_gasto": 100.0, "gastos_por_tipo": [{"ano": 2026, "tipo": "x", "total": 100.0}]},
        "/parlamentares/2": {"total_gasto": 300.0, "gastos_por_tipo": [{"ano": 2025, "tipo": "x", "total": 120.0},
                                                                       {"ano": 2026, "tipo": "y", "total": 180.0}]},
        # mesma pessoa com nome de urna e nome completo; 2002 (arquivo do TSE marca todos como eleitos) fica de fora
        "/eleicoes/1994/SP?cargo=DEPUTADO FEDERAL&turno=1": _eleicao(1994, "SP", "DEPUTADO FEDERAL", 1, [_e("a1", "JOSÉ CARLOS SILVA", 10)]),
        "/eleicoes/1998/SP?cargo=DEPUTADO FEDERAL&turno=1": _eleicao(1998, "SP", "DEPUTADO FEDERAL", 1, [_e("a2", "JOSÉ SILVA", 20)]),
        "/eleicoes/2002/SP?cargo=DEPUTADO FEDERAL&turno=1": _eleicao(2002, "SP", "DEPUTADO FEDERAL", 1, [_e("a3", "JOSÉ SILVA", 5), _e("x", "QUALQUER UM", 1)]),
        "/eleicoes/2000/SP?cargo=PREFEITO&turno=1": _eleicao(2000, "SP", "PREFEITO", 1, [_e("p1", "MARIA SOUZA", 50, unidade="SANTOS")]),
        # homônimos no mesmo ano, cargo e estado não são unidos
        "/eleicoes/2004/SP?cargo=PREFEITO&turno=1": _eleicao(2004, "SP", "PREFEITO", 1, [_e("h1", "JOÃO LIMA", 9, unidade="A"), _e("h2", "JOÃO LIMA", 8, unidade="B")]),
        # presidente: só a lista do país conta (a dos estados repete)
        "/eleicoes/2022/BR?cargo=PRESIDENTE&turno=2": _eleicao(2022, "BR", "PRESIDENTE", 2, [_e("l", "LULA", 600)]),
        "/eleicoes/2022/SP?cargo=PRESIDENTE&turno=2": _eleicao(2022, "SP", "PRESIDENTE", 2, [_e("l", "LULA", 60)]),
        "/eleicoes/2022/SP?cargo=SENADOR&turno=1": _eleicao(2022, "SP", "SENADOR", 1, [_e("s", "NAO ELEITO", 9, situacao="SUPLENTE")]),
    }
    ix = montar(dados)
    g = ix["gastos"]["itens"]
    assert [x[1] for x in g] == ["Bia", "Ana"] and g[0][6] == {"2025": 120.0, "2026": 180.0}
    assert ix["gastos"]["anos"] == [2025, 2026]
    pessoas = {(p[0], p[1]): p for p in ix["mandatos"]["itens"]}
    jose = pessoas[("JOSÉ CARLOS SILVA", "SP")]
    assert jose[4] == 2 and [m[0] for m in jose[5]] == [1994, 1998] and jose[3] == 8
    assert ("QUALQUER UM", "SP") not in pessoas
    assert pessoas[("MARIA SOUZA", "SP")][5][0][4] == "SANTOS" and CARGOS[pessoas[("MARIA SOUZA", "SP")][5][0][1]] == "PREFEITO"
    assert len([p for p in ix["mandatos"]["itens"] if p[0] == "JOÃO LIMA"]) == 2
    lula = pessoas[("LULA", "BR")]
    assert lula[4] == 1
    assert ("NAO ELEITO", "SP") not in pessoas
    mv = ix["mais_votados"]["por_cargo"]
    assert mv["PRESIDENTE"]["2022"][0][0] == "LULA" and len(mv["PRESIDENTE"]["2022"]) == 1
    assert "2002" not in mv["DEPUTADO FEDERAL"]
