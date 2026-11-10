"""Como votou cada ministro do STJ (certidões dos acórdãos) e as relatorias do TSE. API GET /votos-tribunais.

Posição individual só quando a certidão do julgamento a escreve; resultado do colegiado à parte; TSE sem voto individual (não há base aberta).
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.collectors.stj import POSICOES
from app.models import Coleta, Registro

AVISO = ("Posição de cada ministro tirada do texto oficial do acórdão (certidão do julgamento): só vale o que está escrito — votou com o relator, "
         "vencido, ausente, impedido, não participou. Quem não aparece fica sem registro; nada é deduzido. O resultado do colegiado (unânime ou por maioria) "
         "é diferente da posição de cada julgador. Os espelhos de acórdão do STJ não cobrem todos os julgamentos: só os que a Secretaria de Jurisprudência trata.")


def _coleta(db: Session, fonte: str, tarefa: str) -> dict:
    c = db.scalars(select(Coleta).where(Coleta.fonte == fonte, Coleta.tarefa == tarefa).order_by(Coleta.inicio.desc()).limit(1)).first()
    boa = db.scalars(select(Coleta).where(Coleta.fonte == fonte, Coleta.tarefa == tarefa, Coleta.status.in_(("ok", "parcial")))
                     .order_by(Coleta.fim.desc()).limit(1)).first()
    return {"status": "nunca_coletada" if not c else c.status if c.status in ("ok", "parcial", "rodando") else "falhou",
            "atualizado_em": boa.fim.isoformat(timespec="minutes") if boa and boa.fim else None}


def dados(db: Session, maioria: int = 100) -> dict | None:
    res = db.scalar(select(Registro.dados).where(Registro.fonte == "stj", Registro.tipo == "stj_resumo", Registro.chave == "ultimo"))
    mins = [d for d in db.scalars(select(Registro.dados).where(Registro.fonte == "stj", Registro.tipo == "stj_ministro"))]
    tse = {int(a): d for a, d in db.execute(select(Registro.ano, Registro.dados).where(Registro.fonte == "tse", Registro.tipo == "tse_relatorias"))}
    if not res and not tse:
        return None
    out = {"aviso": AVISO, "posicoes": POSICOES}
    if res:
        lista = []
        for m in mins:
            votou = m.get("votos_registrados") or 0
            lista.append({"nome": m["nome"], "votos_registrados": votou, "relator": m.get("relator", 0) + m.get("relator_acordao", 0),
                          "acompanhou": m.get("acompanhou", 0), "unanime": m.get("participou_unanime", 0), "participou": m.get("participou", 0),
                          "vencido": m.get("vencido", 0) + m.get("vencido_parte", 0), "vencido_parte": m.get("vencido_parte", 0),
                          "ausente": m.get("ausente", 0), "impedido": m.get("impedido", 0), "nao_participou": m.get("nao_participou", 0),
                          "maioria_vencedor": m.get("maioria_vencedor", 0), "maioria_vencido": m.get("maioria_vencido", 0),
                          "pct_vencido": round(100 * (m.get("vencido", 0) + m.get("vencido_parte", 0)) / votou, 2) if votou else None,
                          "orgaos": m.get("orgaos") or {}})
        lista.sort(key=lambda x: -x["votos_registrados"])
        o = res.get("orgaos") or {}
        out["stj"] = {"acordaos": res.get("acordaos"), "periodo": res.get("periodo"), "publicados": res.get("publicados"), "meses": res.get("meses"), "orgaos": o,
                      "unanimes": sum(x.get("unanimidade", 0) for x in o.values()), "por_maioria": sum(x.get("maioria", 0) for x in o.values()),
                      "ministros": lista, "decisoes_por_maioria": [{**x, "ementa": (x.get("ementa") or "")[:240]} for x in (res.get("maioria") or [])[:maioria]], "total_por_maioria": res.get("maioria_total"),
                      "fonte": "STJ — Dados Abertos, Espelhos de Acórdãos", "link": "https://dadosabertos.web.stj.jus.br/", **_coleta(db, "stj", "votos")}
    if tse:
        ult = max(tse)
        d = tse[ult]
        out["tse"] = {"ano_eleicao": ult, "anos": sorted(tse), "votos_individuais": False, "motivo": d.get("motivo"),
                      "relatores": sorted(({"nome": k.title(), **v} for k, v in d.get("relatores", {}).items() if v.get("acordaos")), key=lambda x: -x["acordaos"]),
                      "fonte": "TSE — Dados Abertos, Processual (decisões)", "link": d.get("fonte"), **_coleta(db, "tse", "relatorias")}
    return out
