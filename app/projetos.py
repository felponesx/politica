"""Lista de projetos (proposições) já com autor, relator, placar da votação e fase (para votar / em votação / já votado).

Tudo vem do que já foi coletado: autores e passos da tramitação (`Registro` tipo tramitacao), votações ligadas à proposição (`Votacao`,
placar oficial da casa ou contagem dos votos nominais) e a pauta dos eventos de hoje (`Registro` tipo evento). Onde o dado não foi coletado,
o campo vem vazio: nada é inventado.
"""
from __future__ import annotations

import re
from datetime import date

from sqlalchemy import func, or_, select

from app.models import Parlamentar, Proposicao, Registro, Votacao, Voto

CONGRESSO = ("PLN", "MPV", "PLV")  # tramitam no Congresso Nacional (sessão conjunta e comissão mista)
FASES = ("a_votar", "em_votacao", "votado")
# tipos que são projetos/propostas de lei (o resto, como requerimentos e indicações, não entra na lista de projetos)
LEGISLATIVAS = ("PL", "PLP", "PEC", "MPV", "PDL", "PDC", "PLN", "PRC", "PLS", "PLC", "PDS", "PLV")
# situações em que o projeto está pronto/aguardando ir a voto (texto da Câmara e do Senado)
_A_VOTAR = ("pronta para pauta", "pronto para pauta", "aguardando delibera", "aguardando vota", "aguardando apreciação", "aguardando apreciacao",
            "aguardando discuss", "em pauta", "aguardando inclusão na ordem do dia", "aguardando inclusao na ordem do dia",
            "pronta para a pauta", "pronto para delibera", "incluída na pauta", "incluida na pauta", "aguardando turno suplementar",
            "aguardando inclusão ordem do dia", "aguardando inclusao ordem do dia")
_ID = re.compile(r"\b(PL|PLP|PEC|MPV|PDL|PDC|PLN|PRC|PLS|PLC|PDS|PLV)\s*n?[ºo°.]?\s*(\d{1,5})\s*/\s*(\d{4})", re.I)
_RELATOR = re.compile(r"relator(?:a)?\b[\s,:\-–]*(?:dep(?:utad[oa])?\.?\s*|sen(?:ador[a]?)?\.?\s*)?([A-ZÁÉÍÓÚÂÊÔÃÕÇ][^(,.;\n]{3,60})", re.I)


def prioridade(p) -> str | None:
    """alta / media / baixa a partir do regime de tramitação da Câmara (Urgência, Prioridade, Ordinária). Medida provisória tranca a pauta: alta.
    Sem regime coletado (ou fora da Câmara), vem vazio: nada é inventado."""
    if p.sigla_tipo == "MPV":
        return "alta"
    r = (p.regime or "").lower()
    if r.startswith("urg"):
        return "alta"
    if r.startswith("prior"):
        return "media"
    if r.startswith("ordin"):
        return "baixa"
    return None


def filtrar_por_prioridade(stmt, prio: str | None):
    if not prio:
        return stmt
    reg = func.lower(func.coalesce(Proposicao.regime, ""))
    if prio == "alta":
        return stmt.where(or_(reg.like("urg%"), Proposicao.sigla_tipo == "MPV"))
    if prio == "media":
        return stmt.where(reg.like("prior%"), Proposicao.sigla_tipo != "MPV")
    return stmt.where(or_(reg.like("ordin%")), Proposicao.sigla_tipo != "MPV")


def _pauta_de_hoje(db, hoje: date) -> dict[tuple, str]:
    """{(sigla, numero, ano): 'em_andamento' | 'convocada'} dos eventos de hoje cuja pauta cita a proposição."""
    out: dict[tuple, str] = {}
    for r in db.scalars(select(Registro).where(Registro.tipo == "evento").order_by(Registro.id.desc()).limit(400)):
        d = r.dados or {}
        if d.get("dia") != hoje.isoformat():
            continue
        sit = str(d.get("situacao") or "").lower()
        estado = "em_andamento" if "andamento" in sit else "convocada" if ("convoc" in sit or "agendad" in sit or not sit) else None
        if not estado:
            continue
        for item in d.get("pauta") or []:
            for m in _ID.finditer(" ".join(str(v) for v in item.values() if v)):
                k = (m.group(1).upper(), str(int(m.group(2))), int(m.group(3)))
                if out.get(k) != "em_andamento":
                    out[k] = estado
    return out


def _ids_na_pauta(db, pauta: dict) -> dict[int, str]:
    out: dict[int, str] = {}
    for (sigla, numero, ano), estado in pauta.items():
        for p in db.scalars(select(Proposicao).where(Proposicao.sigla_tipo == sigla, Proposicao.numero == numero, Proposicao.ano == ano)):
            out[p.id] = estado
    return out


def filtrar_por_fase(db, stmt, fase: str | None):
    if not fase:
        return stmt
    if fase not in FASES:
        raise ValueError("fase inválida")
    votados = select(Votacao.proposicao_id).where(Votacao.proposicao_id.isnot(None))
    pauta = _ids_na_pauta(db, _pauta_de_hoje(db, date.today()))
    em_vot = [i for i, e in pauta.items() if e == "em_andamento"]
    na_pauta = [i for i, e in pauta.items() if e == "convocada"]
    if fase == "votado":
        return stmt.where(Proposicao.id.in_(votados))
    if fase == "em_votacao":
        return stmt.where(Proposicao.id.in_(em_vot or [-1]))
    sit = or_(*[func.lower(Proposicao.situacao).like(f"%{t}%") for t in _A_VOTAR])
    return stmt.where(or_(Proposicao.id.in_(na_pauta or [-1]), sit), Proposicao.id.notin_(em_vot or [-1]), Proposicao.id.notin_(votados))


def _relator(passos: list[dict]) -> str | None:
    for p in reversed(passos or []):
        txt = f"{p.get('descricao') or ''} {p.get('despacho') or ''}"
        if "relator" not in txt.lower():
            continue
        if not re.search(r"design|nomead|avocad|substitu", txt, re.I):
            continue
        m = _RELATOR.search(txt)
        if m:
            nome = " ".join(m.group(1).split()).strip(" -–")
            if len(nome.split()) >= 2 or len(nome) > 5:
                return nome
    return None


def _placar(v: Votacao, contagem: dict[int, dict]) -> dict | None:
    po = v.placar_oficial or {}
    if po.get("sim") or po.get("nao") or po.get("abstencao"):
        base = {"sim": po.get("sim", 0), "nao": po.get("nao", 0), "abstencao": po.get("abstencao", 0), "obstrucao": po.get("obstrucao", 0)}
    elif v.secreta:
        return {"secreta": True, "resultado": v.resultado, "data": v.data.isoformat() if v.data else None, "votacao_id": v.id}
    else:
        c = contagem.get(v.id)
        if not c:
            return {"resultado": v.resultado, "data": v.data.isoformat() if v.data else None, "votacao_id": v.id} if v.resultado else None
        base = c
    return {**base, "resultado": v.resultado, "data": v.data.isoformat() if v.data else None, "votacao_id": v.id}


def enriquecer(db, props: list[Proposicao]) -> list[dict]:
    ids = [p.id for p in props]
    if not ids:
        return []
    hoje = date.today()
    votacoes: dict[int, list[Votacao]] = {}
    for v in db.scalars(select(Votacao).where(Votacao.proposicao_id.in_(ids)).order_by(Votacao.data, Votacao.id)):
        votacoes.setdefault(v.proposicao_id, []).append(v)
    ultimas = {pid: vs[-1] for pid, vs in votacoes.items()}
    # contagem dos votos nominais só das votações sem placar oficial
    sem_placar = [v.id for v in ultimas.values() if not (v.placar_oficial or {}).get("sim") and not v.secreta]
    contagem: dict[int, dict] = {}
    if sem_placar:
        for vid, voto, n in db.execute(select(Voto.votacao_id, Voto.voto, func.count()).where(Voto.votacao_id.in_(sem_placar)).group_by(Voto.votacao_id, Voto.voto)):
            c = contagem.setdefault(vid, {"sim": 0, "nao": 0, "abstencao": 0, "obstrucao": 0})
            t = (voto or "").lower()
            k = "sim" if t.startswith("sim") else "nao" if t.startswith(("n", "não")) else "abstencao" if t.startswith("abst") else "obstrucao" if t.startswith("obstr") else None
            if k:
                c[k] += n
    tram = {r.chave: r.dados or {} for r in db.scalars(select(Registro).where(Registro.tipo == "tramitacao", Registro.chave.in_([str(i) for i in ids])))}
    pauta = _ids_na_pauta(db, _pauta_de_hoje(db, hoje))
    out = []
    for p in props:
        t = tram.get(str(p.id), {})
        autores = t.get("autores") or []
        autor = None
        if autores:
            a = autores[0]
            par = db.scalar(select(Parlamentar).where(Parlamentar.casa == (a.get("casa") or p.casa), Parlamentar.id_externo == str(a.get("id_externo")))) if a.get("id_externo") else None
            autor = {"nome": a.get("nome"), "tipo": a.get("tipo"), "partido": par.partido if par else None, "uf": par.uf if par else None,
                     "parlamentar_id": par.id if par else None, "outros": max(0, len(autores) - 1)}
        pl = _placar(ultimas[p.id], contagem) if p.id in ultimas else None
        sit = (p.situacao or "").lower()
        na_pauta = pauta.get(p.id)
        if p.id in ultimas or re.search(r"norma jur|transformad[oa] em (lei|norma)", sit):
            fase = "votado"
        elif na_pauta == "em_andamento":
            fase = "em_votacao"
        elif na_pauta == "convocada" or any(x in sit for x in _A_VOTAR):
            fase = "a_votar"
        else:
            fase = None
        out.append({"prioridade": prioridade(p), "regime": p.regime, "id": p.id, "casa": p.casa, "sigla_tipo": p.sigla_tipo, "numero": p.numero, "ano": p.ano, "ementa": p.ementa,
                    "data_apresentacao": p.data_apresentacao.isoformat() if p.data_apresentacao else None, "situacao": p.situacao,
                    "autor": autor, "relator": _relator(t.get("passos") or []), "placar": pl, "fase": fase, "na_pauta": na_pauta,
                    "virou_lei": bool(p.urn_final) or bool(re.search(r"norma jur|transformad[oa] em (lei|norma)", sit))})
    return out
