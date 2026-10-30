"""Saúde: atenção básica (UBS e Mais Médicos, Ministério da Saúde) e quanto cada governo gasta em saúde (SICONFI), por estado e por município.

UBS: tarefa `saude-ubs`; Mais Médicos: `saude-mais-medicos` (app/collectors/saude.py). Gasto: despesa liquidada na função "Saúde" do RREO Anexo 02
(`despesa_funcao`), no último ano com o 6º bimestre fechado em quase todos os estados, para os estados poderem ser comparados. Contas por habitante usam a
população dos municípios (IBGE). As limitações vão junto da resposta.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Municipio, Registro
from app.utils import UFS

NOTAS = [
    "UBS são as Unidades Básicas de Saúde cadastradas no CNES (Ministério da Saúde): a porta de entrada do SUS. Contar unidades não mede a qualidade do atendimento, "
    "nem quantas equipes ou médicos há em cada uma.",
    "Mais Médicos mostra só as vagas desse programa (ativas, ocupadas e desocupadas) na data indicada; não são todos os médicos do SUS.",
    "Gasto em saúde do estado = despesa liquidada na função Saúde (SICONFI, RREO Anexo 02) no último ano fechado; não inclui o gasto das prefeituras nem o da União no estado.",
    "Leitos hospitalares ainda não entram: a API do Ministério não entrega um mês só (ver docs/FONTES.md).",
]
FONTES = ["CNES e Mais Médicos / Ministério da Saúde — https://apidadosabertos.saude.gov.br", "SICONFI / Tesouro Nacional — RREO Anexo 02",
          "IBGE — população dos municípios"]


def _por(v, pop, base):
    return round(v / pop * base, 2) if v is not None and pop else None


def _pct(a, b):
    return round(100 * a / b, 1) if b else None


def _gasto_saude(db: Session):
    """Devolve (ano, {UF: {saude, total}}, uniao) do último ano com o 6º bimestre em pelo menos 20 estados."""
    linhas = db.execute(select(Registro.uf, Registro.ano, Registro.titulo, Registro.dados).where(Registro.tipo == "despesa_funcao")).all()
    por: dict[tuple, dict] = {}
    for uf, ano, titulo, d in linhas:
        d = d or {}
        if d.get("esfera") not in ("E", "U") or int(d.get("bimestre") or 0) != 6:
            continue
        e = por.setdefault((d["esfera"], uf, ano), {"saude": 0.0, "total": 0.0})
        v = d.get("liquidado") or 0
        e["total"] += v
        if (titulo or "").strip().lower() == "saúde":
            e["saude"] += v
    anos = sorted({k[2] for k in por if k[0] == "E"}, reverse=True)
    ano = next((a for a in anos if sum(1 for k in por if k[0] == "E" and k[2] == a) >= 20), None)
    if ano is None:
        return None, {}, None
    return ano, {k[1]: v for k, v in por.items() if k[0] == "E" and k[2] == ano}, por.get(("U", None, ano))


def _municipios_por_uf(db: Session):
    pop, n_mun, uf_de = {}, {}, {}
    for cod, uf, p in db.execute(select(Municipio.codigo_ibge, Municipio.uf, Municipio.populacao)):
        pop[uf] = pop.get(uf, 0) + (p or 0)
        n_mun[uf] = n_mun.get(uf, 0) + 1
        uf_de[cod[:6]] = uf
    return pop, n_mun, uf_de


def painel(db: Session) -> dict | None:
    pop_uf, n_mun, uf_de = _municipios_por_uf(db)
    ubs = {c: d.get("ubs", 0) for c, d in db.execute(select(Registro.chave, Registro.dados).where(Registro.fonte == "saude", Registro.tipo == "ubs_municipio"))}
    mm = {c: d for c, d in db.execute(select(Registro.chave, Registro.dados).where(Registro.fonte == "saude", Registro.tipo == "mais_medicos_municipio"))}
    resumo_mm = db.scalar(select(Registro.dados).where(Registro.fonte == "saude", Registro.tipo == "mais_medicos_resumo", Registro.chave == "BR")) or {}
    ano_gasto, gasto, uniao = _gasto_saude(db)
    if not ubs and not mm and not gasto:
        return None
    estados = {}
    for uf in UFS:
        pop = pop_uf.get(uf) or None
        e = {"populacao": pop}
        tem_ubs = {c for c in ubs if uf_de.get(c) == uf}
        if ubs:
            q = sum(ubs[c] for c in tem_ubs)
            e.update(ubs=q, ubs_por_100mil=_por(q, pop, 100000), municipios=n_mun.get(uf), municipios_sem_ubs=max(0, (n_mun.get(uf) or 0) - len(tem_ubs)))
        if mm:
            d = [v for c, v in mm.items() if uf_de.get(c) == uf]
            vagas, oc = sum(v["vagas"] for v in d), sum(v["ocupadas"] for v in d)
            e.update(mm_vagas=vagas, mm_ocupadas=oc, mm_desocupadas=sum(v["desocupadas"] for v in d), mm_pct_ocupadas=_pct(oc, vagas),
                     mm_por_100mil=_por(oc, pop, 100000))
        g = gasto.get(uf)
        if g:
            e.update(gasto_saude=round(g["saude"], 2), gasto_total=round(g["total"], 2), gasto_saude_por_hab=_por(g["saude"], pop, 1),
                     pct_do_gasto=_pct(g["saude"], g["total"]))
        if len(e) > 1:
            estados[uf] = e
    pop_br = sum(pop_uf.values()) or None
    soma = lambda k: sum(e.get(k) or 0 for e in estados.values())  # noqa: E731
    br = {"populacao": pop_br, "municipios": sum(n_mun.values()) or None}
    if ubs:
        br.update(ubs=soma("ubs"), ubs_por_100mil=_por(soma("ubs"), pop_br, 100000), municipios_sem_ubs=soma("municipios_sem_ubs"))
    if mm:
        br.update(mm_vagas=soma("mm_vagas"), mm_ocupadas=soma("mm_ocupadas"), mm_desocupadas=soma("mm_desocupadas"),
                  mm_pct_ocupadas=_pct(soma("mm_ocupadas"), soma("mm_vagas")), mm_por_100mil=_por(soma("mm_ocupadas"), pop_br, 100000),
                  mm_fora_de_municipio=resumo_mm, mm_data=resumo_mm.get("data_referencia") or next(iter(mm.values())).get("data_referencia"))
    if gasto:
        tot = sum(g["saude"] for g in gasto.values())
        br.update(gasto_estados_saude=round(tot, 2), gasto_estados_saude_por_hab=_por(tot, pop_br, 1))
    if uniao:
        br.update(gasto_uniao_saude=round(uniao["saude"], 2), gasto_uniao_saude_por_hab=_por(uniao["saude"], pop_br, 1), gasto_uniao_total=round(uniao["total"], 2),
                  gasto_uniao_pct=_pct(uniao["saude"], uniao["total"]))
    return {"ano_gasto": ano_gasto, "brasil": br, "estados": estados, "notas": NOTAS, "fontes": FONTES}


def municipios(db: Session, uf: str, limite: int = 60) -> list[dict]:
    mun = {m.codigo_ibge[:6]: (m.nome, m.populacao) for m in db.scalars(select(Municipio).where(Municipio.uf == uf))}
    ubs = {c: d.get("ubs", 0) for c, d in db.execute(select(Registro.chave, Registro.dados).where(Registro.fonte == "saude", Registro.tipo == "ubs_municipio", Registro.uf == uf))}
    mm = {c: d for c, d in db.execute(select(Registro.chave, Registro.dados).where(Registro.fonte == "saude", Registro.tipo == "mais_medicos_municipio", Registro.uf == uf))}
    out = []
    for cod, (nome, pop) in mun.items():
        m = mm.get(cod) or {}
        out.append({"codigo_ibge": cod, "nome": nome, "populacao": pop, "ubs": ubs.get(cod, 0), "ubs_por_10mil": _por(ubs.get(cod, 0), pop, 10000),
                    "mm_vagas": m.get("vagas"), "mm_ocupadas": m.get("ocupadas")})
    out.sort(key=lambda x: -(x["populacao"] or 0))
    return out[:limite]
