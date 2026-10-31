"""Painéis montados a partir das coletas novas: social (Bolsa Família e BPC), trabalho, meio ambiente, viagens a serviço, fundo eleitoral e tarifa de energia."""
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import Municipio, Registro
from app.utils import UFS, sem_acento

AVISO_SOCIAL = ("Bolsa Família e BPC (Benefício de Prestação Continuada) pagos pelo governo federal, no mês indicado, pelo município onde mora o beneficiário. Contam-se as parcelas do próprio mês; "
                "o que foi pago de meses atrasados aparece à parte. Nomes e CPFs não são guardados. Beneficiários por 100 habitantes usa a população estimada dos municípios (IBGE).")
AVISO_TRABALHO = "PNAD Contínua trimestral (IBGE): desocupação é a parcela da força de trabalho sem emprego que procurou vaga; rendimento é o médio real habitual de todos os trabalhos. É pesquisa por amostra: estados pequenos oscilam."
AVISO_AMBIENTE = ("PRODES (INPE) mede o desmatamento por corte raso em cada ano (de agosto a julho) pelos satélites; os seis biomas não se sobrepõem e a soma é do estado. DETER é alerta rápido, "
                  "não é a taxa oficial, e cobre só a Amazônia e o Cerrado. Km² = quilômetros quadrados; 100 km² ≈ 10 mil campos de futebol. "
                  "Nesta cópia só entram os biomas que a coleta conseguiu ler por inteiro (hoje Amazônia e Pampa); no Pampa, anos com valor zero ou quase zero são lacunas da fonte, não desmatamento nulo.")
AVISO_VIAGENS = ("Viagens a serviço de servidores e colaboradores do governo federal (Portal da Transparência): diárias, passagens e outros gastos, menos o que foi devolvido. "
                 "Nomes e CPFs não são guardados. O ano corrente está em andamento.")
AVISO_SERVIDORES = ("Servidores civis federais do SIAPE (Portal da Transparência), por órgão e estado, no último mês publicado. Só somas: nomes, CPFs e matrículas não são guardados. "
                    "Valores acima do teto de referência não são ilegais por si só: há parcelas que a lei deixa fora do teto (indenizações, 13º, férias, decisões judiciais). "
                    "'Cortados pelo teto' são os que tiveram abate-teto no mês. Não inclui militares nem Legislativo e Judiciário que usam outro sistema.")
AVISO_FUNDOS = "Fundo Especial de Financiamento de Campanha (fundo eleitoral), distribuído pelo TSE a cada partido para as eleições; valor do partido em cada ano. Fonte: TSE, dados abertos."
AVISO_ENERGIA = ("Tarifa residencial convencional (grupo B1) em vigor de cada distribuidora, TUSD (uso da rede) + TE (energia), em R$ por kWh, antes de impostos (ICMS, PIS/Cofins) e bandeiras tarifárias. "
                 "Fonte: ANEEL, dados abertos.")


def _regs(db: Session, tipo: str, fonte: str | None = None):
    q = select(Registro.chave, Registro.dados).where(Registro.tipo == tipo)
    if fonte:
        q = q.where(Registro.fonte == fonte)
    return {c: d for c, d in db.execute(q)}


def _pop_uf(db: Session) -> dict:
    pop: dict[str, int] = {}
    for uf, p in db.execute(select(Municipio.uf, Municipio.populacao)):
        pop[uf] = pop.get(uf, 0) + (p or 0)
    return pop


def _por(v, pop, base):
    return round(v / pop * base, 2) if v is not None and pop else None


def social(db: Session) -> dict | None:
    bolsa, bpc = _regs(db, "bolsa_familia_uf", "transparencia"), _regs(db, "bpc_uf", "transparencia")
    if not bolsa and not bpc:
        return None
    pop = _pop_uf(db)
    estados = {}
    for uf in UFS:
        p = pop.get(uf) or None
        e = {"populacao": p}
        for nome, d in (("bolsa", bolsa.get(uf)), ("bpc", bpc.get(uf))):
            if d:
                e[nome] = {"mes": d["mes"], "beneficiarios": d["n"], "valor": d["valor"], "retroativo": d["retroativo"], "por_100_hab": _por(d["n"], p, 100),
                           "valor_por_hab": _por(d["valor"], p, 1), "valor_medio": round(d["valor"] / d["n"], 2) if d["n"] else None}
        if len(e) > 1:
            estados[uf] = e
    br = {"populacao": sum(pop.values()) or None}
    for nome in ("bolsa", "bpc"):
        itens = [e[nome] for e in estados.values() if nome in e]
        if itens:
            n, v = sum(x["beneficiarios"] for x in itens), sum(x["valor"] for x in itens)
            br[nome] = {"mes": itens[0]["mes"], "beneficiarios": n, "valor": round(v, 2), "retroativo": round(sum(x["retroativo"] for x in itens), 2),
                        "por_100_hab": _por(n, br["populacao"], 100), "valor_medio": round(v / n, 2) if n else None}
    return {"brasil": br, "estados": estados, "aviso": AVISO_SOCIAL, "fontes": ["Portal da Transparência — Novo Bolsa Família e BPC", "IBGE — população dos municípios"]}


def social_municipios(db: Session, uf: str, limite: int = 60) -> list[dict]:
    bolsa = db.scalar(select(Registro.dados).where(Registro.fonte == "transparencia", Registro.tipo == "bolsa_familia_uf", Registro.chave == uf)) or {}
    bpc = db.scalar(select(Registro.dados).where(Registro.fonte == "transparencia", Registro.tipo == "bpc_uf", Registro.chave == uf)) or {}
    pop = {sem_acento(m.nome): (m.populacao, m.codigo_ibge) for m in db.scalars(select(Municipio).where(Municipio.uf == uf))}
    bp = {sem_acento(m["nome"]): m for m in bpc.get("municipios", [])}
    out = []
    for m in bolsa.get("municipios", []):
        chave = sem_acento(m["nome"])
        p, cod = pop.get(chave, (None, None))
        b = bp.get(chave) or {}
        out.append({"codigo_ibge": cod, "nome": m["nome"], "populacao": p, "bolsa": m["n"], "bolsa_valor": m["valor"], "bolsa_por_100_hab": _por(m["n"], p, 100),
                    "bpc": b.get("n"), "bpc_por_100_hab": _por(b.get("n"), p, 100)})
    out.sort(key=lambda x: -(x["populacao"] or x["bolsa"] * 3))
    return out[:limite]


def trabalho(db: Session) -> dict | None:
    series = {k: _regs(db, f"trabalho_{k}", "ibge") for k in ("desocupacao", "rendimento")}
    net = _regs(db, "banda_larga_uf", "anatel")
    comb = _regs(db, "combustiveis_uf", "anp")
    if not any(series.values()) and not net and not comb:
        return None
    estados = {}
    for uf in UFS:
        e = {}
        for k, d in series.items():
            x = d.get(uf)
            if x and x.get("serie"):
                ult = x["ultimo"] if x["ultimo"] in x["serie"] else max(x["serie"])
                e[k] = x["serie"][ult]
                e[k + "_trimestre"] = ult
                e[k + "_serie"] = x["serie"]
        n = net.get(uf)
        if n:
            e["internet_mes"] = n["mes"]
            e["internet_acessos"] = n["acessos"]
            e["fibra_pct"] = round(n["fibra"] / n["acessos"] * 100, 1) if n["acessos"] else None
        c = comb.get(uf)
        if c:
            e["combustiveis_mes"] = c["mes"]
            for prod in ("gasolina", "etanol", "diesel_s10", "gnv"):
                if (c["produtos"].get(prod) or {}).get("preco"):
                    e["preco_" + prod] = c["produtos"][prod]["preco"]
        if e:
            estados[uf] = e
    pop = _pop_uf(db)
    for uf, e in estados.items():
        if e.get("internet_acessos") and pop.get(uf):
            e["internet100"] = _por(e["internet_acessos"], pop[uf], 100)
    return {"estados": estados, "rotulos": {k: (next(iter(d.values()))["rotulo"] if d else None) for k, d in series.items()}, "aviso": AVISO_TRABALHO,
            "fontes": ["IBGE — PNAD Contínua trimestral (SIDRA)", "Anatel — acessos de banda larga fixa", "ANP — levantamento de preços de combustíveis"]}


def ambiente(db: Session) -> dict | None:
    prodes, deter = _regs(db, "prodes_bioma", "inpe"), _regs(db, "deter_bioma", "inpe")
    focos = db.scalar(select(Registro.dados).where(Registro.fonte == "inpe", Registro.tipo == "focos_queimadas", Registro.chave == "BR"))
    if not prodes and not deter and not focos:
        return None
    por_uf: dict[str, dict] = {}
    biomas = {}
    for chave, d in prodes.items():
        biomas[chave] = {"nome": d["bioma"], "ultimo_ano": d["ultimo_ano"], "total": d["total"]}
        for uf, s in d["por_uf"].items():
            for a, km in s.items():
                por_uf.setdefault(uf, {})[a] = round(por_uf.setdefault(uf, {}).get(a, 0.0) + km, 2)
    anos = sorted({a for s in por_uf.values() for a in s})
    brasil = {a: round(sum(s.get(a, 0) for s in por_uf.values()), 2) for a in anos}
    estados = {}
    for uf, s in por_uf.items():
        if not s:
            continue
        ult = max(s)
        estados[uf] = {"ultimo_ano": ult, "km2": s[ult], "serie": s, "total_desde_inicio": round(sum(s.values()), 2)}
        # onde o desmatamento do estado aconteceu (bioma) no último ano
        estados[uf]["por_bioma"] = {b["nome"]: prodes[k]["por_uf"].get(uf, {}).get(ult, 0.0) for k, b in biomas.items() if prodes[k]["por_uf"].get(uf)}
    alertas = {"por_uf": {}, "mensal": {}}
    desde = None
    for d in deter.values():
        desde = d["desde"] if not desde or d["desde"] < desde else desde
        for uf, meses in d["por_uf"].items():
            for m, v in meses.items():
                x = alertas["por_uf"].setdefault(uf, {}).setdefault(m, {"desmatamento": 0.0, "degradacao": 0.0})
                x["desmatamento"] += v["desmatamento"]
                x["degradacao"] += v["degradacao"]
                t = alertas["mensal"].setdefault(m, {"desmatamento": 0.0, "degradacao": 0.0})
                t["desmatamento"] += v["desmatamento"]
                t["degradacao"] += v["degradacao"]
    meses = sorted(alertas["mensal"])
    ult12 = meses[-12:]
    for uf, mm in alertas["por_uf"].items():
        e = estados.setdefault(uf, {})
        e["deter_12m"] = round(sum(mm.get(m, {}).get("desmatamento", 0) for m in ult12), 2)
    if focos:
        for uf, serie in focos["por_uf"].items():
            e = estados.setdefault(uf, {})
            e["focos"] = serie.get(focos["ultimo_ano"])
            e["focos_serie"] = serie
    return {"brasil": brasil, "ultimo_ano": anos[-1] if anos else None, "biomas": biomas, "estados": estados,
            "focos": ({"ultimo_ano": focos["ultimo_ano"], "total": focos["total"], "por_bioma": focos["por_bioma"]} if focos else None),
            "deter": {"desde": desde, "ultimos_meses": ult12, "mensal": {m: {k: round(v, 2) for k, v in alertas["mensal"][m].items()} for m in meses}},
            "aviso": AVISO_AMBIENTE, "fontes": ["INPE — PRODES e DETER (TerraBrasilis)", "INPE — Programa Queimadas (focos de calor)"]}


def viagens(db: Session) -> dict | None:
    anos = _regs(db, "viagens_ano", "transparencia")
    if not anos:
        return None
    ordem = sorted(anos, reverse=True)
    return {"anos": [{k: v for k, v in anos[a].items() if k != "orgaos"} for a in ordem], "orgaos": {a: anos[a]["orgaos"] for a in ordem}, "aviso": AVISO_VIAGENS,
            "fontes": ["Portal da Transparência — viagens a serviço"]}


AVISO_PRF = ("Acidentes registrados pela Polícia Rodoviária Federal nas rodovias federais (arquivos 'agrupados por ocorrência'). Só somas por estado, mês, causa, tipo e rodovia; "
             "a causa é a registrada pelo policial no local, não uma conclusão de perícia. Rodovias estaduais e ruas das cidades não entram.")


def acidentes_rodovias(db: Session) -> dict | None:
    anos = _regs(db, "acidentes_ano", "prf")
    if not anos:
        return None
    ordem = sorted(anos, reverse=True)
    return {"anos": [{"ano": int(a), **anos[a]["total"], "ultimo_mes": anos[a].get("ultimo_mes")} for a in ordem], "detalhe": {a: anos[a] for a in ordem}, "aviso": AVISO_PRF,
            "fontes": ["Polícia Rodoviária Federal — dados abertos"]}


AVISO_MALHA = ("Quilômetros de via de cada capital segundo o OpenStreetMap (mapa colaborativo): é o tamanho da malha, NÃO o trânsito. Pista dupla conta um trecho por sentido; "
               "vias que cruzam a divisa entram inteiras; ciclovias, calçadas, escadas e vias em obra ficam de fora; bairros ainda não são separados.")
AVISO_TRANSITO_AGORA = ("Medição do TomTom numa AMOSTRA de poucas vias de cada capital (não a cidade toda; o campo 'amostra' diz de onde vieram os pontos), na hora indicada. Congestionamento = quanto a velocidade atual está abaixo da "
                        "velocidade com a via livre. Não é o índice anual do TomTom Traffic Index nem os quilômetros da malha.")


def transito_malha(db: Session) -> dict | None:
    r = _regs(db, "malha_capital", "osm")
    if not r:
        return None
    capitais = [{k: v for k, v in d.items() if k != "pontos_amostra"} for d in r.values()]
    capitais.sort(key=lambda x: -x["km_total"])
    return {"capitais": capitais, "total_km": round(sum(c["km_total"] for c in capitais), 1), "aviso": AVISO_MALHA, "fontes": ["OpenStreetMap (Overpass)"]}


def transito_agora(db: Session) -> dict | None:
    r = _regs(db, "transito_agora", "tomtom")
    if not r:
        return None
    dias = _regs(db, "transito_dia", "tomtom")
    historico: dict[str, list] = {}
    for k in sorted(dias):
        historico.setdefault(k.split("|")[0], []).append(dias[k])
    return {"capitais": sorted(r.values(), key=lambda x: -x["congestionamento_pct"]), "historico_diario": {u: v[-30:] for u, v in historico.items()}, "aviso": AVISO_TRANSITO_AGORA,
            "fontes": ["TomTom Traffic API"]}


AVISO_CAGED = ("Novo CAGED (Ministério do Trabalho): admissões, desligamentos e saldo de empregos com carteira (CLT) por estado e setor, a partir dos movimentos declarados no mês. "
               "Só somas; nenhum trabalhador é identificado. Os números oficiais somam também as declarações fora do prazo e tiram as excluídas, então podem diferir um pouco destes. "
               "Não inclui servidores estatutários nem trabalho informal.")


def caged(db: Session) -> dict | None:
    meses = _regs(db, "caged_mes", "caged")
    if not meses:
        return None
    ordem = sorted(meses, reverse=True)
    return {"ultimo": meses[ordem[0]], "meses": [{"competencia": m, **meses[m]["brasil"]} for m in ordem], "aviso": AVISO_CAGED, "fontes": ["Ministério do Trabalho — Novo CAGED (FTP do PDET)"]}


def iva(db: Session) -> dict:
    """Calendário do IVA dual (curado, com a lei como fonte) + o que o monitor achou nas fontes oficiais. Nunca devolve valor de arrecadação que não tenha sido publicado."""
    import json
    from pathlib import Path
    cal = json.loads((Path(__file__).resolve().parent / "dados" / "iva.json").read_text(encoding="utf-8"))
    cbs = _regs(db, "cbs_monitor", "receita").get("ultimo")
    ibs = _regs(db, "ibs_monitor", "cgibs").get("ultimo")
    mon = None
    if cbs or ibs:
        mon = {"cbs": cbs, "ibs": ibs, "arrecadacao_publicada": bool((cbs or {}).get("arrecadacao_publicada") or (ibs or {}).get("arrecadacao_publicada")),
               "checado_em": max(str(x.get("checado_em") or "") for x in (cbs, ibs) if x)}
    if mon is None:
        mensagem = "Ainda não conferimos as fontes (rode as coletas receita-cbs e cgibs-ibs)."
    elif mon["arrecadacao_publicada"]:
        mensagem = "As fontes oficiais já trazem dados de arrecadação de CBS/IBS: veja os valores abaixo."
    else:
        mensagem = "Nenhuma fonte oficial publica ainda a arrecadação de CBS ou de IBS. Não estimamos valores."
    return {**cal, "monitor": mon, "situacao": mensagem}


AVISO_ESTOQUE = ("ESTOQUE DE REFERÊNCIA: é a base anual de vínculos formais (CLT) ativos que o Ministério do Trabalho atualiza depois da RAIS e sobre a qual o Novo CAGED soma os saldos de cada mês. "
                 "Aqui a data é dezembro do ano anterior; NÃO é um estoque medido todo mês. Estabelecimento sem município definido fica em 'ignorado'. Não inclui servidores estatutários nem trabalho informal.")
AVISO_ENCADEADO = ("ESTIMATIVA encadeada por estado e setor: estoque de referência de dezembro + soma dos saldos mensais do Novo CAGED (admissões − desligamentos dos movimentos declarados no mês). "
                   "Os números oficiais também somam as declarações fora do prazo e tiram as excluídas, então podem diferir. Não existe por município: os saldos mensais só vêm por estado e setor.")


def secao_da_divisao(d: int) -> str:
    for a, b, s in ((1, 3, "A"), (5, 9, "B"), (10, 33, "C"), (35, 35, "D"), (36, 39, "E"), (41, 43, "F"), (45, 47, "G"), (49, 53, "H"), (55, 56, "I"), (58, 63, "J"), (64, 66, "K"),
                    (68, 68, "L"), (69, 75, "M"), (77, 82, "N"), (84, 84, "O"), (85, 85, "P"), (86, 88, "Q"), (90, 93, "R"), (94, 96, "S"), (97, 97, "T"), (99, 99, "U")):
        if a <= d <= b:
            return s
    return "Z"


def caged_estoque(db: Session, ibge: str | None = None, uf: str | None = None) -> dict | None:
    from sqlalchemy import func

    from app.collectors.caged import SECOES, UF_IBGE
    from app.models import CagedEstoqueRef as E
    resumo = _regs(db, "estoque_ref_resumo", "caged")
    if not resumo:
        return None
    comp = max(resumo)
    info = resumo[comp]
    base = {"competencia_referencia": comp, "total_vinculos": info["total_vinculos"], "confere_com_comunicado": info.get("confere_com_comunicado"), "aviso": AVISO_ESTOQUE,
            "fontes": ["Ministério do Trabalho e Emprego — estoque de referência do Novo CAGED"], "arquivo": info.get("arquivo")}
    if ibge:
        cod = "".join(c for c in ibge if c.isdigit())[:6]
        linhas = db.execute(select(E.subclasse, E.vinculos).where(E.competencia == comp, E.cod_municipio == cod)).all()
        if not linhas:
            return {**base, "municipio": None, "encontrado": False}
        tot = sum(v for _, v in linhas)
        por_sec: dict[str, int] = {}
        for sub, v in linhas:
            sec = secao_da_divisao(int(sub[:2]))
            por_sec[sec] = por_sec.get(sec, 0) + v
        nome = db.execute(select(Municipio.nome, Municipio.uf).where(Municipio.codigo_ibge.like(cod + "%"))).first() if hasattr(Municipio, "codigo_ibge") else None
        return {**base, "encontrado": True, "cod_municipio": cod, "municipio": nome[0] if nome else None, "uf": (nome[1] if nome else UF_IBGE.get(cod[:2])), "vinculos": tot,
                "por_secao": [{"secao": k, "setor": SECOES.get(k, k), "vinculos": v, "pct": round(v / tot * 100, 1)} for k, v in sorted(por_sec.items(), key=lambda x: -x[1])],
                "maiores_subclasses": [{"subclasse": s, "vinculos": v} for s, v in sorted(linhas, key=lambda x: -x[1])[:15]], "n_subclasses": len(linhas)}
    cod_uf = func.substr(E.cod_municipio, 1, 2).label("cod_uf")   # a mesma expressão no SELECT e no GROUP BY (o Postgres exige)
    q = select(cod_uf, func.sum(E.vinculos)).where(E.competencia == comp).group_by(cod_uf)
    por_uf = {UF_IBGE.get(c, "ignorado" if c == "99" else c): int(v) for c, v in db.execute(q)}
    out = {**base, "por_uf": dict(sorted(por_uf.items(), key=lambda x: -x[1])), "municipios": db.scalar(select(func.count(func.distinct(E.cod_municipio))).where(E.competencia == comp)) - 1}
    if uf:
        cods = [c for c, s in UF_IBGE.items() if s == uf.upper()]
        if cods:
            r = db.execute(select(E.cod_municipio, func.sum(E.vinculos).label("v")).where(E.competencia == comp, E.cod_municipio.like(cods[0] + "%")).group_by(E.cod_municipio)
                           .order_by(text("v desc")).limit(50)).all()
            out["maiores_municipios"] = [{"cod_municipio": c, "vinculos": int(v)} for c, v in r]
    out["encadeado"] = caged_encadeado(db, comp)
    return out


def caged_encadeado(db: Session, comp: str) -> dict:
    """Estoque estimado = referência (dezembro) + saldos mensais seguintes, por UF e seção; só se TODOS os meses entre a referência e o último mês coletado estiverem no banco."""
    from sqlalchemy import func

    from app.collectors.caged import UF_IBGE
    from app.models import CagedEstoqueRef as E
    meses = _regs(db, "caged_mes", "caged")
    ano, mes = int(comp[:4]), int(comp[5:])
    seguintes = sorted(m for m in meses if m > comp.replace("-", ""))
    if not seguintes:
        return {"disponivel": False, "motivo": "Ainda não há saldos mensais do Novo CAGED depois da data de referência."}
    ultimo = seguintes[-1]
    esperados, a, m = [], ano, mes
    while True:
        m += 1
        if m == 13:
            a, m = a + 1, 1
        esperados.append(f"{a}{m:02d}")
        if esperados[-1] == ultimo:
            break
    faltam = [x for x in esperados if x not in meses]
    if faltam:
        return {"disponivel": False, "motivo": "Faltam meses de saldo para encadear: " + ", ".join(faltam), "ultimo_mes_coletado": ultimo, "meses_faltando": faltam, "aviso": AVISO_ENCADEADO}
    ref: dict[tuple[str, str], int] = {}
    cod_uf, div = func.substr(E.cod_municipio, 1, 2).label("cod_uf"), func.substr(E.subclasse, 1, 2).label("div")
    q = select(cod_uf, div, func.sum(E.vinculos)).where(E.competencia == comp).group_by(cod_uf, div)
    for c, d, v in db.execute(q):
        uf = UF_IBGE.get(c)
        if uf:
            k = (uf, secao_da_divisao(int(d)))
            ref[k] = ref.get(k, 0) + int(v)
    saldo: dict[tuple[str, str], int] = {}
    for m in esperados:
        for uf, e in meses[m]["por_uf"].items():
            for sec, x in e["por_secao"].items():
                saldo[(uf, sec)] = saldo.get((uf, sec), 0) + x["saldo_mov"]
    por_uf: dict[str, dict] = {}
    for k in set(ref) | set(saldo):
        u = por_uf.setdefault(k[0], {"referencia": 0, "saldo_acumulado": 0})
        u["referencia"] += ref.get(k, 0)
        u["saldo_acumulado"] += saldo.get(k, 0)
    for u in por_uf.values():
        u["estoque_estimado"] = u["referencia"] + u["saldo_acumulado"]
    tot = {"referencia": sum(u["referencia"] for u in por_uf.values()), "saldo_acumulado": sum(u["saldo_acumulado"] for u in por_uf.values())}
    tot["estoque_estimado"] = tot["referencia"] + tot["saldo_acumulado"]
    return {"disponivel": True, "competencia_estimada": ultimo, "meses_somados": esperados, "brasil": tot, "por_uf": dict(sorted(por_uf.items(), key=lambda x: -x[1]["estoque_estimado"])), "aviso": AVISO_ENCADEADO}


AVISO_FILA = ("FILA DE REVISÃO, não é publicação de casos. São notícias de órgãos oficiais (com título, data e link da fonte) que tratam de investigação, denúncia, condenação etc. A etapa é só uma sugestão pelo título; "
              "pessoas envolvidas, local e a situação do processo ficam em branco até uma pessoa conferir a fonte. Ser citado numa notícia de investigação não é condenação, e nenhum nome é extraído automaticamente.")


def escandalos_fila(db: Session, etapa: str | None = None, orgao: str | None = None, limite: int = 50) -> dict | None:
    itens = [r.dados for r in db.execute(select(Registro).where(Registro.fonte == "escandalos", Registro.tipo == "fila_item")).scalars()]
    fontes = _regs(db, "fila_fontes", "escandalos").get("ultimo")
    if not itens and not fontes:
        return None
    por_etapa: dict[str, int] = {}
    for i in itens:
        por_etapa[i["etapa_sugerida"]] = por_etapa.get(i["etapa_sugerida"], 0) + 1
    sel = [i for i in itens if (not etapa or i["etapa_sugerida"] == etapa) and (not orgao or i["orgao_id"] == orgao)]
    sel.sort(key=lambda i: i.get("data") or "", reverse=True)
    return {"total": len(sel), "por_etapa": por_etapa, "itens": sel[:limite], "fontes": (fontes or {}).get("fontes", []), "verificado_em": (fontes or {}).get("verificado_em"), "aviso": AVISO_FILA}


AVISO_IGC_MUN = ("O IGC é a nota da INSTITUIÇÃO de ensino superior, não do município. Aqui aparecem as instituições com sede ou cursos presenciais no município (Censo da Educação Superior), cada uma com a sua nota "
                 "institucional. Uma instituição com cursos em vários municípios mostra a MESMA nota em todos eles. Cursos a distância sem polo não têm município e não entram. Instituição sem IGC publicado aparece sem nota.")


def _igc_por_ies(db: Session) -> dict[int, dict]:
    """Nota mais recente de cada instituição entre as edições do IGC coletadas."""
    out: dict[int, dict] = {}
    for ano, d in sorted(_regs(db, "igc_edicao", "inep").items()):
        for x in (d or {}).get("lista", []):
            out[int(x["codigo"])] = {"igc": x.get("igc"), "faixa": x.get("faixa"), "edicao": int(ano), "categoria": x.get("categoria"), "organizacao": x.get("organizacao")}
    return out


def igc_municipio(db: Session, ibge: str) -> dict | None:
    from app.models import IesMunicipio as M
    cod = "".join(c for c in ibge if c.isdigit())
    if len(cod) == 6:   # sem o dígito verificador: casa pelo começo
        linhas = db.execute(select(M).where(M.cod_municipio.like(cod + "%"))).scalars().all()
    else:
        linhas = db.execute(select(M).where(M.cod_municipio == cod)).scalars().all()
    if not linhas:
        return None
    igc = _igc_por_ies(db)
    ano = max(x.ano_censo for x in linhas)
    itens = []
    for x in sorted((l for l in linhas if l.ano_censo == ano), key=lambda l: (-l.matriculas, -l.n_cursos)):
        n = igc.get(x.co_ies, {})
        itens.append({"co_ies": x.co_ies, "nome": x.nome, "sigla": x.sigla, "sede_no_municipio": x.sede, "cursos_no_municipio": x.n_cursos, "vagas": x.vagas, "matriculas": x.matriculas,
                      "igc_da_instituicao": n.get("igc"), "faixa_igc": n.get("faixa"), "edicao_igc": n.get("edicao")})
    return {"municipio": linhas[0].municipio, "uf": linhas[0].uf, "cod_municipio": linhas[0].cod_municipio, "ano_censo": ano, "instituicoes": itens, "n_instituicoes": len(itens),
            "com_igc": sum(1 for i in itens if i["igc_da_instituicao"] is not None), "aviso": AVISO_IGC_MUN, "fontes": ["INEP — Censo da Educação Superior", "INEP — IGC"]}


def igc_instituicao(db: Session, co_ies: int) -> dict | None:
    from app.models import IesMunicipio as M
    linhas = db.execute(select(M).where(M.co_ies == co_ies)).scalars().all()
    if not linhas:
        return None
    ano = max(x.ano_censo for x in linhas)
    n = _igc_por_ies(db).get(co_ies, {})
    muns = sorted((l for l in linhas if l.ano_censo == ano), key=lambda l: (-l.matriculas, -l.n_cursos))
    return {"co_ies": co_ies, "nome": muns[0].nome, "sigla": muns[0].sigla, "igc": n.get("igc"), "faixa_igc": n.get("faixa"), "edicao_igc": n.get("edicao"), "ano_censo": ano,
            "municipios": [{"cod_municipio": m.cod_municipio, "municipio": m.municipio, "uf": m.uf, "sede": m.sede, "cursos": m.n_cursos, "vagas": m.vagas, "matriculas": m.matriculas} for m in muns],
            "aviso": AVISO_IGC_MUN}


AVISO_MAPBIOMAS = ("ALERTAS validados pelo MapBiomas Alerta, contados por bioma e mês. NÃO é a taxa oficial de desmatamento do PRODES/INPE: a metodologia, o período e a unidade (aqui, quantidade de alertas, não área) são outros, "
                   "e os números não devem ser somados nem comparados com os do PRODES. A área e o detalhe de cada alerta exigem login na plataforma e não são coletados.")


def alertas_mapbiomas(db: Session) -> dict | None:
    d = _regs(db, "alertas_bioma", "mapbiomas").get("ultimo")
    return {**d, "aviso": AVISO_MAPBIOMAS, "fontes": ["MapBiomas Alerta (API pública)"]} if d else None


def servidores(db: Session) -> dict | None:
    meses = _regs(db, "servidores_mes", "transparencia")
    if not meses:
        return None
    ordem = sorted(meses, reverse=True)
    atual = meses[ordem[0]]
    return {**atual, "meses": [{"competencia": m, "servidores": meses[m]["servidores"], **meses[m]["total"]} for m in ordem], "aviso": AVISO_SERVIDORES,
            "fontes": ["Portal da Transparência — servidores (SIAPE)"]}


def fundos(db: Session) -> dict | None:
    anos = _regs(db, "fefc_ano", "tse")
    if not anos:
        return None
    return {"anos": {a: anos[a] for a in sorted(anos, reverse=True)}, "aviso": AVISO_FUNDOS, "fontes": ["TSE — dados abertos (FEFC e Fundo Partidário)"]}


def energia(db: Session) -> dict | None:
    d = db.scalar(select(Registro.dados).where(Registro.fonte == "aneel", Registro.tipo == "tarifas_residencial", Registro.chave == "BR"))
    return {**d, "aviso": AVISO_ENERGIA, "fontes": ["ANEEL — dados abertos (tarifas homologadas)"]} if d else None


AVISO_CPIS = ("CPI (Comissão Parlamentar de Inquérito) investiga um fato certo por um prazo; CPMI reúne deputados e senadores. Abrir uma CPI não prova irregularidade nem culpa de ninguém: "
              "o relatório final é recomendação e só a Justiça condena. A lista do Senado traz só as em atividade.")


def cpis(db: Session) -> dict | None:
    regs = {r.chave: (r.dados or {}).get("itens") or [] for r in db.scalars(select(Registro).where(Registro.fonte == "congresso", Registro.tipo == "cpis_casa"))}
    if not regs.get("camara") and not regs.get("senado"):
        return None
    itens = sorted(regs.get("camara", []) + regs.get("senado", []), key=lambda x: x.get("inicio") or x.get("instalacao") or "", reverse=True)
    return {"itens": itens, "total": len(itens), "aviso": AVISO_CPIS, "fontes": ["Câmara dos Deputados — dados abertos", "Senado Federal — dados abertos"]}


AVISO_AEROPORTOS = "Aeródromos públicos registrados na ANAC (cadastro oficial). Inclui aeroportos grandes e pistas pequenas; 'operação noturna' é a que o cadastro informa para o aeródromo, não o horário de voos."


def aeroportos(db: Session) -> dict | None:
    d = db.scalar(select(Registro.dados).where(Registro.fonte == "anac", Registro.tipo == "aerodromos", Registro.chave == "BR"))
    return {**d, "aviso": AVISO_AEROPORTOS, "fontes": ["ANAC — dados abertos (lista de aeródromos públicos)"]} if d else None


AVISO_IBAMA = ("Autos de infração ambiental lavrados pelo IBAMA, sem os cancelados. O valor é o da multa APLICADA no auto, não o que foi pago: muitas são contestadas, reduzidas ou nunca pagas. "
               "Nomes e documentos dos autuados não são guardados aqui. Ser autuado não é condenação definitiva.")
AVISO_LISTA_SUJA = ("Cadastro de Empregadores que submeteram trabalhadores a condições análogas à de escravo (Ministério do Trabalho), após decisão administrativa definitiva. "
                    "Mostramos só totais por estado e ano da ação fiscal; nomes ficam na fonte oficial.")
AVISO_RENUNCIA = ("Estimativa da Receita Federal de quanto o governo deixa de arrecadar por benefícios tributários (isenções, deduções, regimes especiais), em valores nominais do ano-base. "
                  "Não é gasto efetivo nem prova de irregularidade: são regras previstas em lei.")


def _dados(db: Session, fonte: str, tipo: str):
    return db.scalar(select(Registro.dados).where(Registro.fonte == fonte, Registro.tipo == tipo, Registro.chave == "BR"))


def multas_ambientais(db: Session) -> dict | None:
    d = _dados(db, "ibama", "multas_ambientais")
    return {**d, "aviso": AVISO_IBAMA, "fontes": ["IBAMA — dados abertos (autos de infração)"]} if d else None


def lista_suja(db: Session) -> dict | None:
    d = _dados(db, "mte", "lista_suja")
    return {**d, "aviso": AVISO_LISTA_SUJA, "fontes": ["Ministério do Trabalho e Emprego — Cadastro de Empregadores"]} if d else None


def renuncia_fiscal(db: Session) -> dict | None:
    d = _dados(db, "receita", "renuncia_fiscal")
    return {**d, "aviso": AVISO_RENUNCIA, "fontes": ["Receita Federal — gastos tributários (bases efetivas)"]} if d else None


AVISO_IRREGULARES = ("Contas julgadas irregulares pelo TCU com decisão que não cabe mais recurso (trânsito em julgado). A lista pública inclui pessoas e empresas; aqui entram só totais, sem nomes nem documentos. "
                     "Conta irregular é decisão de controle externo sobre uso de dinheiro público: não é, por si, condenação penal.")


def tcu_irregulares(db: Session) -> dict | None:
    d = db.scalar(select(Registro.dados).where(Registro.fonte == "tcu", Registro.tipo == "tcu_irregulares", Registro.chave == "BR"))
    return {**d, "aviso": AVISO_IRREGULARES, "fontes": ["Tribunal de Contas da União — responsáveis com contas julgadas irregulares"]} if d else None
