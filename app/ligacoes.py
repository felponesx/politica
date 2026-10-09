"""Ligações cruzadas entre bases.

1. Votação -> proposição: pela matéria ("PL 42/2024") contra sigla/número/ano das proposições.
2. Parlamentar -> candidatura (TSE): nome de urna + UF + cargo compatível com a casa.
   Só liga quando há UM candidato compatível (nomes repetidos ficam sem ligação, por segurança).
3. Fornecedores: CNPJ (só dígitos) em contratos públicos e na cota parlamentar — consultado na hora (API).
"""
import logging
import re

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Candidato, Parlamentar, Proposicao, Votacao
from app.utils import sem_acento

log = logging.getLogger("brasilplus.ligacoes")
CARGO_DA_CASA = {"camara": "DEPUTADO FEDERAL", "senado": "SENADOR"}


def cargo_da_casa(casa: str) -> str | None:
    """Assembleias (casa al-xx) elegem deputados estaduais; a do DF, deputados distritais."""
    if casa and casa.startswith("al-"):
        return "DEPUTADO DISTRITAL" if casa == "al-df" else "DEPUTADO ESTADUAL"
    return CARGO_DA_CASA.get(casa)
_MATERIA = re.compile(r"([A-Z]{2,4})\s+(\d+)/(\d{4})")


def vincular_votacoes(db) -> int:
    props = {}
    for p in db.execute(select(Proposicao.id, Proposicao.casa, Proposicao.sigla_tipo, Proposicao.numero, Proposicao.ano)):
        if p.sigla_tipo and p.numero and p.ano:
            props.setdefault((p.sigla_tipo.upper(), str(int(p.numero)) if p.numero.isdigit() else p.numero, p.ano), {})[p.casa] = p.id
    ligadas = 0
    for v in db.scalars(select(Votacao).where(Votacao.proposicao_id.is_(None), Votacao.materia.isnot(None))):
        m = _MATERIA.search(v.materia.upper())
        if not m:
            continue
        por_casa = props.get((m.group(1), str(int(m.group(2))), int(m.group(3))))
        if por_casa:  # prefere a proposição da mesma casa
            v.proposicao_id = por_casa.get(v.casa) or next(iter(por_casa.values()))
            ligadas += 1
    db.commit()
    return ligadas


def vincular_candidaturas(db) -> int:
    candidatos = {}
    for c in db.scalars(select(Candidato).where(Candidato.cargo.in_([*CARGO_DA_CASA.values(), "DEPUTADO ESTADUAL", "DEPUTADO DISTRITAL"]))):
        for nome in {c.nome_urna, c.nome}:
            if nome:
                candidatos.setdefault((sem_acento(nome), c.uf, c.cargo), []).append(c)
    ligadas = 0
    for p in db.scalars(select(Parlamentar)):
        achados = candidatos.get((sem_acento(p.nome), p.uf, cargo_da_casa(p.casa)), [])
        # um parlamentar pode ter várias candidaturas (eleições diferentes), mas só uma por ano
        por_ano = {}
        for c in achados:
            por_ano.setdefault(c.ano, set()).add(c.id)
        for ano, ids in por_ano.items():
            if len(ids) == 1:
                cand = next(c for c in achados if c.id in ids)
                if cand.parlamentar_id != p.id:
                    cand.parlamentar_id = p.id
                    ligadas += 1
    db.commit()
    return ligadas


def ligar_tudo() -> dict:
    db = SessionLocal()
    try:
        r = {"votacoes_proposicoes": vincular_votacoes(db), "parlamentares_candidaturas": vincular_candidaturas(db)}
        log.info("Ligações: %s", r)
        return r
    finally:
        db.close()
