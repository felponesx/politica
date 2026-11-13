"""Busca de nomes escritos errado, sem IA: pronúncia do português + erro de digitação (app/nomes.py)."""
import random
import time

import pytest

from app import busca
from app.db import SessionLocal, criar_tabelas
from app.models import Parlamentar
from app.nomes import IndiceNomes, distancia, fonetica, normalizar

NOMES = [(1, "Nikolas Ferreira"), (2, "Nicolau Mattos"), (3, "Maria da Silva"), (4, "João Paulo"), (5, "João Paulo Silva"),
         (6, "Ferreira Lima"), (7, "Conceição Ação"), (8, "Zulmira Costa"), (9, "Wellington Dias"), (10, "Hélio Lopes")]


def test_normalizar_tira_acento_e_cedilha():
    assert normalizar("  Conceição  D'Ávila ") == "conceisao d avila"


def test_pronuncia_do_portugues():
    assert fonetica("nicolas") == fonetica("nikolas") == "nikolas"
    assert fonetica("ferreira") == "fereira" and fonetica("hélio".replace("é", "e")) == "elio"
    assert fonetica("wellington") == fonetica("velington") and fonetica("yasmin") == fonetica("iasmin")
    assert distancia("fereira", "ferera") == 1


@pytest.mark.parametrize("digitado", ["Nicolas Ferreira", "Nikolas Ferrera", "nicolas feriera", "FERREIRA NIKOLAS", "nikol ferr"])
def test_acha_o_nikolas_ferreira_de_varias_formas_erradas(digitado):
    achados = IndiceNomes(NOMES).buscar(digitado)
    assert achados and achados[0][0] == 1, achados


def test_erro_na_primeira_letra_tambem_acha():
    assert IndiceNomes(NOMES).buscar("Micolas Ferreira")[0][0] == 1


def test_nome_completo_vale_mais_que_nome_parcial_e_ligacao_nao_conta():
    ids = [i for i, _, _ in IndiceNomes(NOMES).buscar("joao paulo")]
    assert ids[:2] == [4, 5]
    assert IndiceNomes(NOMES).buscar("Maria Silva")[0][0] == 3     # "da" é ligação
    assert IndiceNomes(NOMES).buscar("velington dias")[0][0] == 9  # Wellington com V


def test_nome_sem_parecido_nao_volta_nada():
    assert IndiceNomes(NOMES).buscar("xyzabc") == []
    assert IndiceNomes(NOMES).buscar("Roberto Carlos") == []


def test_rapido_com_muitos_nomes():
    rng = random.Random(7)
    silabas = ["ma", "jo", "ni", "co", "la", "fer", "rei", "ra", "si", "lva", "pa", "ul", "ca", "to", "re", "mar", "ana", "pe"]
    nomes = [(i, " ".join("".join(rng.choices(silabas, k=rng.randint(2, 4))).capitalize() for _ in range(rng.randint(2, 4))))
             for i in range(60000)]
    nomes.append((99999, "Nikolas Ferreira"))
    t0 = time.monotonic()
    indice = IndiceNomes(nomes)
    t_indice = time.monotonic() - t0
    t0 = time.monotonic()
    achados = indice.buscar("Nicolas Ferrera")
    t_busca = time.monotonic() - t0
    assert achados and achados[0][0] == 99999
    assert t_busca < 2.0 and t_indice < 15.0, (t_indice, t_busca)


# ---------- dentro da busca do BRASIL+ (com banco) ----------

@pytest.fixture
def parlamentares():
    criar_tabelas()
    busca._INDICES.clear()
    ids = ["9601", "9602"]
    with SessionLocal() as db:
        db.query(Parlamentar).filter(Parlamentar.id_externo.in_(ids)).delete(synchronize_session=False)
        db.add_all([Parlamentar(casa="camara", id_externo="9601", nome="Nikolas Ferreira", partido="PL", uf="MG"),
                    Parlamentar(casa="camara", id_externo="9602", nome="Maria da Silva", partido="PT", uf="SP")])
        db.commit()
    yield
    busca._INDICES.clear()
    with SessionLocal() as db:
        db.query(Parlamentar).filter(Parlamentar.id_externo.in_(ids)).delete(synchronize_session=False)
        db.commit()


def test_busca_do_site_acha_nome_escrito_errado(parlamentares):
    with SessionLocal() as db:
        errado = busca.buscar(db, "Nicolas Ferrera", ["parlamentares"])
        exato = busca.buscar(db, "Nikolas Ferreira", ["parlamentares"])
    assert errado["parlamentares"][0]["titulo"] == "Nikolas Ferreira" and errado["parlamentares"][0]["aproximado"] is True
    assert exato["parlamentares"][0]["titulo"] == "Nikolas Ferreira" and "aproximado" not in exato["parlamentares"][0]


def test_busca_exata_nao_perde_nem_duplica(parlamentares):
    with SessionLocal() as db:
        r = busca.buscar(db, "silva", ["parlamentares"])["parlamentares"]
    assert [x["titulo"] for x in r].count("Maria da Silva") == 1


def test_cedilha_digitada_ou_nao_e_a_mesma_pronuncia():
    """"Conceição" e "Conceicao" (sem cedilha) são o mesmo nome, e "-ção" sem cedilha também."""
    indice = IndiceNomes([(1, "Conceição Ação"), (2, "Cláudia Souza")])
    assert indice.buscar("Conceicao Acao")[0][0] == 1 and indice.buscar("Conceição Ação")[0][0] == 1
    assert fonetica("conceicao") == fonetica("conceisao")
