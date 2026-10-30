"""Alinhamento do parlamentar com a maioria do próprio partido nas votações nominais.

Não é fidelidade à orientação da bancada (a orientação oficial não está coletada): compara o voto da pessoa com o voto
mais comum entre os colegas do mesmo partido na mesma votação."""
from collections import Counter, defaultdict
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Votacao, Voto

VOTOS_VALIDOS = ("sim", "não", "nao")
MIN_PARTIDO = 3      # colegas do partido que votaram (sim/não) para a votação contar
MIN_VOTACOES = 10    # votações comparadas para mostrar o percentual
NOTA = ("Compara o voto com o voto mais comum entre os colegas do mesmo partido na mesma votação (só Sim e Não; votações com menos de "
        f"{MIN_PARTIDO} colegas do partido e votações secretas ficam de fora). Não é a orientação oficial da bancada e partido dividido "
        "pode produzir percentuais baixos sem que ninguém tenha 'traído' o partido.")


def _norm(v: str | None) -> str | None:
    v = (v or "").strip().lower()
    if v in VOTOS_VALIDOS:
        return "sim" if v == "sim" else "nao"
    return None


def calcular(db: Session, casa: str, meses: int = 12) -> dict[int, dict]:
    """{parlamentar_id: {comparadas, alinhadas, percentual, partido}} para a casa nos últimos `meses` meses."""
    desde = date.today() - timedelta(days=30 * meses)
    por_votacao: dict[int, list[tuple[int, str, str]]] = defaultdict(list)
    q = (select(Voto.votacao_id, Voto.parlamentar_id, Voto.voto, Voto.partido_na_data)
         .join(Votacao, Votacao.id == Voto.votacao_id)
         .where(Votacao.casa == casa, Votacao.data >= desde, Votacao.secreta.isnot(True)))
    for vid, pid, voto, partido in db.execute(q):
        v = _norm(voto)
        if v and partido:
            por_votacao[vid].append((pid, v, partido))
    comp: Counter = Counter()
    alin: Counter = Counter()
    partido_de: dict[int, str] = {}
    for votos in por_votacao.values():
        por_partido: dict[str, list[tuple[int, str]]] = defaultdict(list)
        for pid, v, partido in votos:
            por_partido[partido].append((pid, v))
        for partido, lista in por_partido.items():
            if len(lista) < MIN_PARTIDO:
                continue
            c = Counter(v for _, v in lista).most_common()
            if len(c) > 1 and c[0][1] == c[1][1]:
                continue  # empate no partido: sem maioria
            maioria = c[0][0]
            for pid, v in lista:
                comp[pid] += 1
                alin[pid] += v == maioria
                partido_de[pid] = partido
    return {pid: {"comparadas": n, "alinhadas": alin[pid], "percentual": round(alin[pid] / n * 100, 1), "partido": partido_de[pid]}
            for pid, n in comp.items()}


def do_parlamentar(db: Session, p) -> dict | None:
    r = calcular(db, p.casa).get(p.id)
    if not r or r["comparadas"] < MIN_VOTACOES:
        return None
    return {**r, "periodo": "últimos 12 meses", "nota": NOTA}


def ranking(db: Session, casa: str, limite: int = 15) -> dict:
    from app.models import Parlamentar
    dados = {k: v for k, v in calcular(db, casa).items() if v["comparadas"] >= MIN_VOTACOES}
    nomes = {p.id: p for p in db.scalars(select(Parlamentar).where(Parlamentar.id.in_(list(dados) or [0]), Parlamentar.em_exercicio.is_(True)))}
    linhas = [{"id": k, "nome": nomes[k].nome, "uf": nomes[k].uf, **v} for k, v in dados.items() if k in nomes]
    linhas.sort(key=lambda x: (x["percentual"], -x["comparadas"]))
    return {"casa": casa, "menos_alinhados": linhas[:limite], "mais_alinhados": linhas[::-1][:limite], "avaliados": len(linhas), "nota": NOTA}
