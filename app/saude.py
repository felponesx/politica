"""Saúde: atenção básica (UBS e Mais Médicos), leitos, UTI, médicos, mortalidade infantil (Ministério da Saúde) e quanto cada governo gasta em saúde (SICONFI).

UBS: tarefa `saude-ubs`; Mais Médicos: `saude-mais-medicos` (app/collectors/saude.py); leitos, UTI, médicos e mortalidade infantil por estado: `saude-datasus`
(app/collectors/datasus.py, TabNet). Gasto: despesa liquidada na função "Saúde" do RREO Anexo 02
(`despesa_funcao`), no último ano com o 6º bimestre fechado em quase todos os estados, para os estados poderem ser comparados. Contas por habitante usam a
população dos municípios (IBGE). As limitações vão junto da resposta.
"""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Coleta, Municipio, Registro
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
CAPITULOS = {"Cap I": "Doenças infecciosas e parasitárias", "Cap II": "Tumores (câncer)", "Cap III": "Doenças do sangue", "Cap IV": "Doenças endócrinas e metabólicas (diabetes)",
             "Cap V": "Transtornos mentais", "Cap VI": "Doenças do sistema nervoso", "Cap VII": "Doenças do olho", "Cap VIII": "Doenças do ouvido",
             "Cap IX": "Doenças do coração e da circulação", "Cap X": "Doenças respiratórias", "Cap XI": "Doenças do aparelho digestivo", "Cap XII": "Doenças da pele",
             "Cap XIII": "Doenças dos ossos e músculos", "Cap XIV": "Doenças dos rins e do aparelho urinário", "Cap XV": "Gravidez, parto e puerpério",
             "Cap XVI": "Problemas do período do nascimento", "Cap XVII": "Malformações de nascença", "Cap XVIII": "Sintomas e causas mal definidas",
             "Cap XX": "Causas externas (acidentes e violência)"}
NOTAS += [
    "Causas de morte: todos os óbitos do SIM pela residência, no último ano fechado (o Ministério fecha cerca de dois anos depois), por capítulo da CID-10. A taxa por 100 mil é bruta "
    "(sem ajustar pela idade): estados com mais idosos têm mais mortes por doenças do coração e câncer sem que a saúde seja pior. Causas externas incluem acidentes, homicídios e suicídios.",
    "Internações do SUS: AIH aprovadas no SIH, pela residência do paciente, no último ano com os 12 meses processados. O valor é o que o SUS pagou aos hospitais pelos serviços; "
    "quem se trata em outro estado conta no estado onde mora. Não inclui hospitais particulares sem convênio.",
    "Dengue: casos prováveis (notificados, sem os descartados) por ano de notificação e estado de residência, no SINAN. Mostra a série dos anos fechados; o ano corrente é parcial. "
    "Mudanças na notificação e em testes entre anos dificultam comparar anos distantes. A taxa usa a população atual dos municípios.",
]
FONTES = ["CNES e Mais Médicos / Ministério da Saúde — https://apidadosabertos.saude.gov.br", "DATASUS TabNet — CNES, SIM, SINASC, SIH e SINAN — http://tabnet.datasus.gov.br",
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
    c = dsus["causas_morte_uf"].get(uf)
    if c:
        e.update(_causas(c, pop))
    i = dsus["internacoes_uf"].get(uf)
    if i:
        e.update(_internacoes(i, pop))
    g = dsus["dengue_uf"].get(uf)
    if g:
        e.update(_dengue(g, pop))
    return e


def _causas(c: dict, pop) -> dict:
    tot = c["total"]
    caps = sorted(c["capitulos"].items(), key=lambda kv: -kv[1])
    taxa = lambda k: _por(c["capitulos"].get(k), pop, 100000)  # noqa: E731
    return {"mortes": tot, "mortes_ano": c["ano"], "mortes_por_100mil": _por(tot, pop, 100000),
            "mortes_causas": [{"capitulo": k, "nome": CAPITULOS.get(k, k), "mortes": n, "pct": _pct(n, tot), "por_100mil": _por(n, pop, 100000)} for k, n in caps[:8]],
            "mortes_coracao_100mil": taxa("Cap IX"), "mortes_cancer_100mil": taxa("Cap II"), "mortes_externas_100mil": taxa("Cap XX"),
            "mortes_respiratorias_100mil": taxa("Cap X"), "mortes_infecciosas_100mil": taxa("Cap I"), "mortes_mal_definidas_pct": _pct(c["capitulos"].get("Cap XVIII", 0), tot)}


def _internacoes(i: dict, pop) -> dict:
    n = i["internacoes"]
    return {"internacoes": n, "internacoes_ano": i["ano"], "internacoes_por_mil": _por(n, pop, 1000), "internacoes_valor": round(i["valor_total"], 2),
            "internacoes_valor_medio": round(i["valor_total"] / n, 2) if n else None, "internacoes_valor_por_hab": _por(i["valor_total"], pop, 1),
            "internacoes_obitos": i["obitos"], "internacoes_letalidade": _pct(i["obitos"], n), "internacoes_dias_medios": round(i["dias"] / n, 1) if n else None}


def _dengue(g: dict, pop) -> dict:
    serie = g["serie"]
    if not serie:
        return {}
    ano = max(serie)
    return {"dengue": serie[ano], "dengue_ano": ano, "dengue_por_100mil": _por(serie[ano], pop, 100000), "dengue_serie": serie,
            "dengue_parcial": g.get("parcial") or {}}


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
    for chave, f in (("causas_morte_uf", _causas), ("internacoes_uf", _internacoes), ("dengue_uf", _dengue)):
        if dsus[chave].get("BR"):
            out.update(f(dsus[chave]["BR"], pop_br))
    return out


def painel(db: Session) -> dict | None:
    pop_uf, n_mun, uf_de = _municipios_por_uf(db)
    ubs = {c: d.get("ubs", 0) for c, d in db.execute(select(Registro.chave, Registro.dados).where(Registro.fonte == "saude", Registro.tipo == "ubs_municipio"))}
    mm = {c: d for c, d in db.execute(select(Registro.chave, Registro.dados).where(Registro.fonte == "saude", Registro.tipo == "mais_medicos_municipio"))}
    resumo_mm = db.scalar(select(Registro.dados).where(Registro.fonte == "saude", Registro.tipo == "mais_medicos_resumo", Registro.chave == "BR")) or {}
    ano_gasto, gasto, uniao = _gasto_saude(db)
    dsus = {t: {c: d for c, d in db.execute(select(Registro.chave, Registro.dados).where(Registro.fonte == "datasus", Registro.tipo == t))}
            for t in ("leitos_uf", "medicos_uf", "mortalidade_infantil_uf", "causas_morte_uf", "internacoes_uf", "dengue_uf")}
    if not ubs and not mm and not gasto and not any(dsus.values()) and not db.scalar(
            select(Registro.id).where(Registro.tipo.in_(("vacinacao_uf", "saude_minimo"))).limit(1)):
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
    ext_uf, ext_br = extras_painel(db)
    for uf, x in ext_uf.items():
        estados.setdefault(uf, {"populacao": pop_uf.get(uf) or None}).update(x)
    estados = {uf: e for uf, e in estados.items() if len(e) > 1}
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
    br.update(ext_br)
    return {"ano_gasto": ano_gasto, "competencias": comp, "brasil": br, "estados": estados, "notas": NOTAS + list(NOTAS_MUN.values()), "fontes": FONTES,
            "fontes_novas": fontes_municipais(db)}


# ---------- leitos, vacinação e mínimo constitucional por município (saude-leitos-municipios, saude-vacinacao, siconfi-saude-minimo) ----------
LEITOS_LINK = "https://dadosabertos.saude.gov.br/dataset/hospitais-e-leitos"
VACINA_LINK = "http://tabnet.datasus.gov.br/cgi/dhdat.exe?bd_pni/cpnibr.def"
MINIMO_LINK = "https://siconfi.tesouro.gov.br/siconfi/pages/public/consulta_finbra_rreo/finbra_rreo_list.jsf"
NOTAS_MUN = {
    "leitos": "Leitos EXISTENTES cadastrados no CNES no mês indicado (arquivo Hospitais e Leitos do Ministério da Saúde), pelo município onde o hospital fica. "
              "Existente não quer dizer livre nem em funcionamento no dia: a ocupação não é publicada em base aberta. \"SUS\" é a parte do leito oferecida ao SUS. "
              "Município sem hospital cadastrado aparece com 0 leitos; município sem dado aparece como \"sem dado\".",
    "vacinacao": "Cobertura vacinal OFICIAL do Programa Nacional de Imunizações (TabNet/DATASUS) pelo município de residência. A base aberta vai até 2022; de 2023 em diante o "
                 "Ministério publica só em painel interativo, sem arquivo aberto, e nada é estimado aqui. Cobertura acima de 100% acontece (vacinados de fora, estimativa de população).",
    "minimo": "Mínimo constitucional em saúde: parte da receita de impostos aplicada em ações e serviços públicos de saúde (LC 141/2012: 15% para municípios e 12% para estados), "
              "no demonstrativo que o próprio governo entrega ao Tesouro (RREO Anexo 14 do SICONFI, o mesmo cálculo do SIOPS). Quem não entregou aparece como \"não entregou\", nunca como 0%.",
}


def _ultima_coleta(db: Session, fonte: str, tarefa: str) -> dict:
    """Situação da coleta para a tela: ok/parcial (com a data), falhou (última tentativa deu erro) ou nunca coletada."""
    ultima = db.scalars(select(Coleta).where(Coleta.fonte == fonte, Coleta.tarefa == tarefa).order_by(Coleta.inicio.desc()).limit(1)).first()
    boa = db.scalars(select(Coleta).where(Coleta.fonte == fonte, Coleta.tarefa == tarefa, Coleta.status.in_(("ok", "parcial")))
                     .order_by(Coleta.fim.desc()).limit(1)).first()
    status = "nunca_coletada" if not ultima else (ultima.status if ultima.status in ("ok", "parcial", "rodando") else "falhou")
    return {"status": status, "atualizado_em": boa.fim.isoformat(timespec="minutes") if boa and boa.fim else None}


def _dados(db: Session, fonte: str, tipo: str, uf: str | None = None) -> dict:
    q = select(Registro.chave, Registro.dados).where(Registro.fonte == fonte, Registro.tipo == tipo)
    if uf:
        q = q.where(Registro.uf == uf)
    return {c: d for c, d in db.execute(q)}


def _minimo(db: Session, esfera: str, uf: str | None = None) -> tuple[int | None, dict]:
    """{id_ente(6 ou 2 dígitos): dados} do ano mais recente com dado do mínimo em saúde."""
    q = select(Registro.ano, Registro.dados).where(Registro.fonte == "siconfi", Registro.tipo == "saude_minimo", Registro.chave.like(f"{esfera}-%"))
    if uf:
        q = q.where(Registro.uf == uf)
    por_ano: dict = {}
    for ano, d in db.execute(q):
        por_ano.setdefault(ano, {})[str(d.get("id_ente"))[:6]] = d
    if not por_ano:
        return None, {}
    ano = max(por_ano, key=lambda a: (len(por_ano[a]) >= 0.5 * max(len(v) for v in por_ano.values()), a))
    return ano, por_ano[ano]


def fontes_municipais(db: Session) -> dict:
    leitos_br = db.scalar(select(Registro.dados).where(Registro.fonte == "cnes", Registro.tipo == "leitos_resumo", Registro.chave == "BR")) or {}
    vac_br = db.scalar(select(Registro.dados).where(Registro.fonte == "datasus", Registro.tipo == "vacinacao_uf", Registro.chave == "BR")) or {}
    ano_m, _ = _minimo(db, "M")
    return {
        "leitos": {"fonte": "CNES — Hospitais e Leitos (Ministério da Saúde)", "link": LEITOS_LINK, "periodo": leitos_br.get("competencia"),
                   **_ultima_coleta(db, "cnes", "leitos_municipios"), "nota": NOTAS_MUN["leitos"]},
        "vacinacao": {"fonte": "PNI — TabNet/DATASUS", "link": VACINA_LINK, "periodo": str(vac_br["ano"]) if vac_br.get("ano") else None,
                      "periodo_indisponivel": f"{vac_br['ano'] + 1} em diante" if vac_br.get("ano") else None,
                      **_ultima_coleta(db, "datasus", "vacinacao"), "nota": NOTAS_MUN["vacinacao"]},
        "minimo": {"fonte": "SICONFI — RREO Anexo 14 (Tesouro Nacional)", "link": MINIMO_LINK, "periodo": str(ano_m) if ano_m else None,
                   **_ultima_coleta(db, "siconfi", "saude_minimo"), "nota": NOTAS_MUN["minimo"]},
    }


def extras_painel(db: Session) -> tuple[dict, dict]:
    """Mínimo constitucional e cobertura vacinal no painel: ({uf: campos}, campos do Brasil)."""
    mi = minimo(db)
    vac = _dados(db, "datasus", "vacinacao_uf")
    est: dict = {}
    for uf in UFS:
        e = {}
        m = (mi or {}).get("estados", {}).get(uf)
        if m:
            e.update(saude_minimo_pct=m["pct_aplicado"], saude_minimo_exigido=m["pct_minimo"], saude_minimo_cumpriu=m["cumpriu"])
        v = vac.get(uf)
        if v and v.get("ano"):
            e.update(vacinacao_ano=v["ano"], vacinacao={va: x for va, s in (v.get("serie") or {}).items() if (x := s.get(str(v["ano"]))) is not None})
        if e:
            est[uf] = e
    br = {}
    vbr = vac.get("BR")
    if vbr and vbr.get("ano"):
        br.update(vacinacao_ano=vbr["ano"], vacinacao={va: x for va, s in (vbr.get("serie") or {}).items() if (x := s.get(str(vbr["ano"]))) is not None})
    if mi:
        br.update(saude_minimo_municipios=mi["municipios"], saude_minimo_ano=mi["ano_estados"], saude_minimo_ano_municipios=mi["ano_municipios"])
    return est, br


def municipios(db: Session, uf: str, limite: int = 60) -> list[dict]:
    mun = {m.codigo_ibge[:6]: (m.nome, m.populacao) for m in db.scalars(select(Municipio).where(Municipio.uf == uf))}
    ubs = {c: d.get("ubs", 0) for c, d in db.execute(select(Registro.chave, Registro.dados).where(Registro.fonte == "saude", Registro.tipo == "ubs_municipio", Registro.uf == uf))}
    mm = {c: d for c, d in db.execute(select(Registro.chave, Registro.dados).where(Registro.fonte == "saude", Registro.tipo == "mais_medicos_municipio", Registro.uf == uf))}
    leitos = _dados(db, "cnes", "leitos_municipio", uf)
    leitos_coletados = bool(leitos) or db.scalar(select(Registro.id).where(Registro.fonte == "cnes", Registro.tipo == "leitos_resumo").limit(1)) is not None
    vac = _dados(db, "datasus", "vacinacao_municipio", uf)
    _, minimo = _minimo(db, "M", uf)
    out = []
    for cod, (nome, pop) in mun.items():
        m = mm.get(cod) or {}
        u = ubs.get(cod, 0) if ubs else None  # UBS não coletadas: sem dado (None), nunca 0
        item = {"codigo_ibge": cod, "nome": nome, "populacao": pop, "ubs": u, "ubs_por_10mil": _por(u, pop, 10000),
                "mm_vagas": m.get("vagas"), "mm_ocupadas": m.get("ocupadas")}
        if leitos_coletados:  # coletado e sem hospital no arquivo = 0 leitos cadastrados (não é falta de dado)
            l = leitos.get(cod) or {}
            item.update(leitos=l.get("existentes", 0), leitos_sus=l.get("sus", 0), leitos_uti=l.get("uti_exist", 0), leitos_uti_sus=l.get("uti_sus", 0),
                        hospitais=l.get("hospitais", 0), leitos_por_mil=_por(l.get("existentes", 0), pop, 1000), leitos_competencia=l.get("competencia"))
        v = vac.get(cod)
        if v:
            item.update(vacinacao_ano=v.get("ano"), vacinacao=v.get("cobertura"))
        mi = minimo.get(cod)
        if mi:
            item.update(saude_minimo_pct=mi.get("pct_aplicado"), saude_minimo_exigido=mi.get("pct_minimo"), saude_minimo_cumpriu=mi.get("cumpriu"),
                        saude_minimo_valor=mi.get("valor_asps"))
        out.append(item)
    out.sort(key=lambda x: -(x["populacao"] or 0))
    return out[:limite]


def vacinacao(db: Session) -> dict | None:
    """Série da cobertura vacinal por estado e do Brasil (todas as vacinas coletadas)."""
    d = _dados(db, "datasus", "vacinacao_uf")
    if not d:
        return None
    br = d.pop("BR", {})
    return {"ano": br.get("ano"), "anos": br.get("anos"), "vacinas": br.get("vacinas"), "brasil": br.get("serie") or {},
            "estados": {uf: x.get("serie") or {} for uf, x in sorted(d.items())}, "aviso": br.get("aviso"), "fonte": fontes_municipais(db)["vacinacao"]}


def minimo(db: Session) -> dict | None:
    """Mínimo constitucional em saúde: estados e resumo dos municípios (quantos cumpriram, quantos não entregaram)."""
    ano_e, est = _minimo(db, "E")
    ano_m, mun = _minimo(db, "M")
    if not est and not mun:
        return None
    from app.utils import UF_POR_CODIGO_IBGE
    estados = {UF_POR_CODIGO_IBGE.get(int(k)): {"pct_aplicado": v.get("pct_aplicado"), "pct_minimo": v.get("pct_minimo"), "cumpriu": v.get("cumpriu"),
                                                "valor": v.get("valor_asps")} for k, v in est.items() if k.isdigit() and int(k) in UF_POR_CODIGO_IBGE}
    resumo = db.scalar(select(Registro.dados).where(Registro.fonte == "siconfi", Registro.tipo == "saude_minimo_resumo", Registro.ano == ano_m)
                       .order_by(Registro.id.desc()).limit(1)) if ano_m else None
    total_mun = db.scalar(select(func.count()).select_from(Municipio)) or None
    por_uf: dict = {}
    for v in mun.values():
        u = por_uf.setdefault(UF_POR_CODIGO_IBGE.get(int(str(v.get("id_ente"))[:2]), "?"), {"entregaram": 0, "cumpriram": 0, "pcts": []})
        u["entregaram"] += 1
        u["cumpriram"] += bool(v.get("cumpriu"))
        u["pcts"].append(v.get("pct_aplicado"))
    for u in por_uf.values():
        p = sorted(x for x in u.pop("pcts") if x is not None)
        u["mediana_pct"] = p[len(p) // 2] if p else None
    return {"ano_estados": ano_e, "ano_municipios": ano_m, "estados": estados,
            "municipios": {"entregaram": len(mun), "cumpriram": sum(1 for v in mun.values() if v.get("cumpriu")),
                           "nao_cumpriram": sum(1 for v in mun.values() if v.get("cumpriu") is False),
                           "sem_dado": (total_mun - len(mun)) if total_mun else None, "por_uf": por_uf,
                           "sem_entrega_coletados": (resumo or {}).get("sem_entrega")},
            "fonte": fontes_municipais(db)["minimo"]}
