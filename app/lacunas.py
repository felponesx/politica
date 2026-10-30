"""Painéis montados a partir das coletas novas: social (Bolsa Família e BPC), trabalho, meio ambiente, viagens a serviço, fundo eleitoral e tarifa de energia."""
from sqlalchemy import select
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
AVISO_TRANSITO_AGORA = ("Medição do TomTom numa AMOSTRA de poucas vias principais de cada capital (não a cidade toda), na hora indicada. Congestionamento = quanto a velocidade atual está abaixo da "
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
