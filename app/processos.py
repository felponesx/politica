"""Processos e casos ligados a um parlamentar, só com fonte oficial ou curada e sem ligar por nome quando há dúvida.

Fontes usadas (nenhuma é agregador privado):
- Representações por quebra de decoro na Câmara (tipo REP nos dados abertos da Câmara; a ementa nomeia o deputado);
- Situação do registro de candidatura no TSE (indeferida, cancelada, renúncia...);
- Casos curados do BRASIL+ (`app/escandalos.py`), ligados só quando o nome COMPLETO da candidatura no TSE é igual ao da pessoa do caso.
Inquéritos e ações penais no STF e processos em geral NÃO entram aqui: não há base aberta confirmada (ver docs/FONTES.md). Processo em
sigilo não aparece em nenhuma fonte pública e nunca é inferido.
"""
from __future__ import annotations

import re

from sqlalchemy import func, select

from app import escandalos
from app.models import Candidato, Parlamentar, Proposicao
from app.utils import sem_acento

AVISO = ("Ter registro aqui não é condenação: representação, denúncia, investigação ou processo não significa culpa. Só aparece o que uma fonte "
         "oficial publica; processos em sigilo não são públicos e não aparecem. A ligação com o nome da pessoa é feita só quando não há dúvida de homônimo.")

_DESFAVOR = re.compile(r"em desfavor d[oa]s?\s+(?:senhor[a]?|sr[a]?\.?)\s+(?:deputad[oa]|senador[a]?)\s+(.+?)(?:,|\.|\s+protocolizad|\s+\(|$)", re.I)


def _n(s) -> str:
    return " ".join(sem_acento(str(s or "")).lower().split())


def nome_na_representacao(ementa: str | None) -> str | None:
    """Nome do deputado citado na ementa de uma Representação ("... em desfavor do Senhor Deputado FULANO, protocolizada ...")."""
    m = _DESFAVOR.search(ementa or "")
    return _n(m.group(1)) if m else None


def _representacoes(db, p: Parlamentar) -> list[dict]:
    if p.casa != "camara":
        return []
    alvo = _n(p.nome)
    # só liga quando ninguém mais da Câmara tem exatamente o mesmo nome parlamentar (homônimo: não liga)
    iguais = [x.nome for x in db.scalars(select(Parlamentar).where(Parlamentar.casa == "camara")) if _n(x.nome) == alvo]
    if len(iguais) != 1:
        return []
    out = []
    for r in db.scalars(select(Proposicao).where(Proposicao.casa == "camara", Proposicao.sigla_tipo == "REP").order_by(Proposicao.ano.desc(), Proposicao.id.desc())):
        if nome_na_representacao(r.ementa) == alvo:
            out.append({"id": r.id, "titulo": f"REP {r.numero}/{r.ano}", "ementa": r.ementa, "ano": r.ano, "situacao": r.situacao,
                        "data_apresentacao": r.data_apresentacao.isoformat() if r.data_apresentacao else None,
                        "fonte": f"https://www.camara.leg.br/proposicoesWeb/fichadetramitacao?idProposicao={r.id_externo}"})
    return out


def _registros(db, p: Parlamentar) -> tuple[list[dict], list[str]]:
    """(candidaturas com registro que não foi simplesmente deferido, nomes completos das candidaturas)."""
    irregulares, nomes = [], []
    for c in db.scalars(select(Candidato).where(Candidato.parlamentar_id == p.id).order_by(Candidato.ano.desc())):
        if c.nome:
            nomes.append(c.nome)
        sit = (c.situacao_candidatura or "").strip()
        if sit and not _n(sit).startswith("deferido"):
            irregulares.append({"ano": c.ano, "cargo": c.cargo, "situacao": sit, "resultado": c.resultado, "uf": c.uf,
                                "fonte": "TSE — dados abertos de candidaturas (consulta_cand)"})
    return irregulares, nomes


def _casos(nomes: list[str], db, p: Parlamentar) -> list[dict]:
    completos = {_n(x) for x in nomes if len(_n(x).split()) >= 2}
    if not completos:
        return []
    out = []
    for c in escandalos.casos().values():
        for pessoa in c["pessoas"]:
            if _n(pessoa["nome"]) in completos:
                # outro parlamentar com o mesmo nome completo na base: homônimo, não liga
                outros = db.scalar(select(func.count()).select_from(Candidato).where(
                    func.lower(Candidato.nome) == pessoa["nome"].lower(), Candidato.parlamentar_id.isnot(None),
                    Candidato.parlamentar_id != p.id))
                if outros:
                    continue
                out.append({"slug": c["slug"], "caso": c["nome"], "pessoa": pessoa["nome"], "cargo_na_epoca": pessoa["cargo_na_epoca"],
                            "situacao": pessoa["situacao"], "detalhe": pessoa["detalhe"], "data_situacao": pessoa["data_situacao"],
                            "fonte": pessoa["fonte"], "ligacao": "nome completo igual ao da candidatura no TSE"})
    return out


def do_parlamentar(db, p: Parlamentar) -> dict:
    registros, nomes = _registros(db, p)
    return {"parlamentar_id": p.id, "casos_curados": _casos(nomes, db, p), "representacoes_decoro": _representacoes(db, p),
            "registro_de_candidatura": registros,
            "stf": {"disponivel": False, "motivo": "Não há base aberta confirmada de inquéritos e ações penais no STF; não é mostrado nada que não tenha fonte."},
            "aviso": AVISO}
