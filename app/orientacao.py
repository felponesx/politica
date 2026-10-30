"""Orientação de bancada (Câmara) cruzada com a votação e com o voto de cada deputado.

Orientação vazia = "Sem orientação registrada" (não é o mesmo que "Liberado"). Só se compara o voto com a orientação do PRÓPRIO partido
quando ele tem bancada com o nome da sigla; deputado de bloco/federação sem linha própria fica de fora (os nomes dos blocos vêm cortados na fonte)."""
from collections import Counter, defaultdict
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Registro, Votacao, Voto

SEM = "Sem orientação registrada"
ALIAS = {"PODEMOS": "PODE", "REPUBLICAN": "REPUBLICANOS", "SOLIDARIED": "SOLIDARIEDADE", "UNIÃO": "UNIÃO"}
LIDERANCAS = ("GOVERNO", "MAIORIA", "MINORIA", "OPOSIÇÃO")
NOTA = ("A orientação é a indicação do líder da bancada; o deputado não é obrigado a segui-la. 'Sem orientação registrada' quer dizer que a fonte "
        "não trouxe orientação, e não que a bancada liberou o voto (liberação aparece como 'Liberado'). Blocos e federações são mostrados como a "
        "Câmara os escreve (os nomes vêm cortados) e não são ligados ao voto de cada partido.")
MIN_VOTACOES = 10


def _chave(s: str) -> str:
    s = (s or "").strip().upper()
    return ALIAS.get(s, s)


def _voto(v: str | None) -> str | None:
    v = (v or "").strip().lower()
    return {"sim": "Sim", "não": "Não", "nao": "Não"}.get(v)


def da_votacao(db: Session, v: Votacao) -> dict:
    r = db.execute(select(Registro).where(Registro.fonte == "camara", Registro.tipo == "orientacao", Registro.chave == v.id_externo)).scalar_one_or_none()
    if v.casa != "camara" or r is None:
        return {"disponivel": False, "mensagem": SEM, "aviso": NOTA}
    bancadas = (r.dados or {}).get("bancadas", {})
    votos = db.execute(select(Voto.voto, Voto.partido_na_data).where(Voto.votacao_id == v.id)).all()
    por_partido: dict[str, Counter] = defaultdict(Counter)
    for voto, partido in votos:
        por_partido[_chave(partido or "")][voto] += 1
    linhas = []
    for nome, ori in sorted(bancadas.items()):
        c = por_partido.get(_chave(nome))
        seguiram = None
        if c and _voto(ori):
            tot = sum(c[k] for k in ("Sim", "Não"))
            seguiram = {"votaram_sim_nao": tot, "seguiram": c[_voto(ori)], "percentual": round(c[_voto(ori)] / tot * 100, 1)} if tot else None
        linhas.append({"bancada": nome, "orientacao": ori or SEM, "lideranca": nome.upper() in LIDERANCAS, "votos_do_partido": dict(c) if c else None, "seguiram": seguiram})
    return {"disponivel": True, "bancadas": linhas, "aviso": NOTA, "fonte": "Câmara dos Deputados (votacoesOrientacoes)"}


def do_parlamentar(db: Session, p, meses: int = 12) -> dict | None:
    """Em quantas votações com orientação do próprio partido (Sim/Não) o deputado votou como orientado."""
    if p.casa != "camara":
        return None
    desde = date.today() - timedelta(days=30 * meses)
    ori = {r.chave: (r.dados or {}).get("bancadas", {}) for r in db.scalars(select(Registro).where(Registro.fonte == "camara", Registro.tipo == "orientacao"))}
    if not ori:
        return {"disponivel": False, "mensagem": SEM, "aviso": NOTA}
    comp = seg = sem = 0
    q = (select(Votacao.id_externo, Voto.voto, Voto.partido_na_data).join(Votacao, Votacao.id == Voto.votacao_id)
         .where(Voto.parlamentar_id == p.id, Votacao.data >= desde, Votacao.casa == "camara"))
    for ide, voto, partido in db.execute(q):
        meu = _voto(voto)
        if not meu or not partido:
            continue
        bancadas = ori.get(ide)
        o = next((x for k, x in (bancadas or {}).items() if _chave(k) == _chave(partido)), None) if bancadas else None
        o = _voto(o)
        if not o:
            sem += 1
            continue
        comp += 1
        seg += meu == o
    if comp < MIN_VOTACOES:
        return {"disponivel": False, "mensagem": SEM, "comparadas": comp, "sem_orientacao": sem, "aviso": NOTA}
    return {"disponivel": True, "comparadas": comp, "seguiu": seg, "percentual": round(seg / comp * 100, 1), "sem_orientacao": sem, "aviso": NOTA}
