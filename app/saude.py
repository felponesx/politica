"""Saúde: atenção básica (UBS e Mais Médicos), leitos, UTI, médicos, mortalidade infantil (Ministério da Saúde) e quanto cada governo gasta em saúde (SICONFI).

UBS: tarefa `saude-ubs`; Mais Médicos: `saude-mais-medicos` (app/collectors/saude.py); leitos, UTI, médicos e mortalidade infantil por estado: `saude-datasus`
(app/collectors/datasus.py, TabNet). Gasto: despesa liquidada na função "Saúde" do RREO Anexo 02
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
    "Leitos, UTI e médicos vêm do CNES (cadastro dos estabelecimentos) no mês indicado, por estado onde o estabelecimento fica. Leitos de internação não incluem os complementares; "
    "\"UTI\" soma só as UTI (adulto, pediátrica, neonatal, queimados e coronariana), sem as unidades intermediárias. Quem mora numa cidade pequena costuma se tratar na maior, então a conta por habitante é aproximada.",
    "Médicos são pessoas cadastradas no CNES com ocupação de médico; quem tem duas especialidades pode aparecer duas vezes e quem trabalha só no setor privado sem cadastro não entra.",
    "Mortalidade infantil = óbitos de menores de 1 ano ÷ nascidos vivos × 1.000, pela residência da mãe (SIM e SINASC). A série oficial vai até dois anos atrás; o ano mais recente ainda é preliminar. Estados pequenos têm taxa instável de um ano para o outro.",
]
FONTES = ["CNES e Mais Médicos / Ministério da Saúde — https://apidadosabertos.saude.gov.br", "DATASUS TabNet — CNES, SIM e SINASC — http://tabnet.datasus.gov.br",
          "SICONFI / Tesouro Nacional — RREO Anexo 02", "IBGE — população dos municípios"]


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


def _so_uti(d: dict) -> int:
    return sum(v for k, v in d.items() if k.startswith("UTI"))


def _datasus_uf(dsus: dict, uf: str, pop: int | None) -> dict:
    e = {}
    l = dsus["leitos_uf"].get(uf)
    if l:
        ex, sus = l["internacao"], l["internacao_sus"]
        u_ex, u_sus = _so_uti(l["uti"]), _so_uti(l["uti_sus"])
        e.update(leitos=ex["Total"], leitos_sus=sus["Total"], leitos_por_mil=_por(ex["Total"], pop, 1000), leitos_sus_por_mil=_por(sus["Total"], pop, 1000),
                 pct_leitos_sus=_pct(sus["Total"], ex["Total"]), leitos_por_especialidade={k: v for k, v in ex.items() if k != "Total"},
                 uti=u_ex, uti_sus=u_sus, uti_por_100mil=_por(u_ex, pop, 100000), pct_uti_sus=_pct(u_sus, u_ex), leitos_complementares=l["uti"].get("Total"))
    m = dsus["medicos_uf"].get(uf)
    if m:
        e.update(medicos=m["total"], medicos_por_mil=_por(m["total"], pop, 1000))
    t = dsus["mortalidade_infantil_uf"].get(uf)
    if t:
        ano = t["ultimo_ano"]
        e.update(tmi=t["serie"][ano]["taxa"], tmi_ano=ano, tmi_obitos=t["serie"][ano]["obitos"], tmi_nascidos=t["serie"][ano]["nascidos"],
                 tmi_serie={a: v["taxa"] for a, v in t["serie"].items()})
    return e


def _datasus_brasil(dsus: dict, estados: dict, pop_br) -> dict:
    out = {}
    soma = lambda k: sum(e.get(k) or 0 for e in estados.values())  # noqa: E731
    if dsus["leitos_uf"]:
        out.update(leitos=soma("leitos"), leitos_sus=soma("leitos_sus"), leitos_por_mil=_por(soma("leitos"), pop_br, 1000), leitos_sus_por_mil=_por(soma("leitos_sus"), pop_br, 1000),
                   pct_leitos_sus=_pct(soma("leitos_sus"), soma("leitos")), uti=soma("uti"), uti_sus=soma("uti_sus"), uti_por_100mil=_por(soma("uti"), pop_br, 100000),
                   pct_uti_sus=_pct(soma("uti_sus"), soma("uti")))
    if dsus["medicos_uf"]:
        out.update(medicos=soma("medicos"), medicos_por_mil=_por(soma("medicos"), pop_br, 1000))
    t = dsus["mortalidade_infantil_uf"].get("BR")
    if t:
        ano = t["ultimo_ano"]
        out.update(tmi=t["serie"][ano]["taxa"], tmi_ano=ano, tmi_obitos=t["serie"][ano]["obitos"], tmi_nascidos=t["serie"][ano]["nascidos"],
                   tmi_serie={a: v["taxa"] for a, v in t["serie"].items()}, tmi_preliminar=t.get("preliminar") or {})
    return out


def painel(db: Session) -> dict | None:
    pop_uf, n_mun, uf_de = _municipios_por_uf(db)
    ubs = {c: d.get("ubs", 0) for c, d in db.execute(select(Registro.chave, Registro.dados).where(Registro.fonte == "saude", Registro.tipo == "ubs_municipio"))}
    mm = {c: d for c, d in db.execute(select(Registro.chave, Registro.dados).where(Registro.fonte == "saude", Registro.tipo == "mais_medicos_municipio"))}
    resumo_mm = db.scalar(select(Registro.dados).where(Registro.fonte == "saude", Registro.tipo == "mais_medicos_resumo", Registro.chave == "BR")) or {}
    ano_gasto, gasto, uniao = _gasto_saude(db)
    dsus = {t: {c: d for c, d in db.execute(select(Registro.chave, Registro.dados).where(Registro.fonte == "datasus", Registro.tipo == t))}
            for t in ("leitos_uf", "medicos_uf", "mortalidade_infantil_uf")}
    if not ubs and not mm and not gasto and not any(dsus.values()):
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
        e.update(_datasus_uf(dsus, uf, pop))
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
    br.update(_datasus_brasil(dsus, estados, pop_br))
    comp = {}
    for u in UFS:
        l = dsus["leitos_uf"].get(u)
        if l:
            comp = {"leitos": l.get("competencia_internacao"), "uti": l.get("competencia_uti"), "medicos": (dsus["medicos_uf"].get(u) or {}).get("competencia")}
            break
    return {"ano_gasto": ano_gasto, "competencias": comp, "brasil": br, "estados": estados, "notas": NOTAS, "fontes": FONTES}


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
