"""Consultas da IA própria: cada função responde UM tipo de pergunta com o que está no banco, citando a fonte e dizendo o que o dado NÃO cobre.

Regras que valem para todas (as mesmas do projeto):
- nunca inventar; se não há dado, dizer isso;
- ausência de registro no banco NÃO é prova de que algo não existe (a resposta diz de onde vêm os dados e o que ficou de fora);
- investigação, processo e condenação são coisas diferentes e nunca se misturam;
- nome parecido não é identidade: a pessoa só é ligada quando não há dúvida (app/ia_propria.py confere).
Sem rede, sem modelo de linguagem, sem custo.
"""
import re
from datetime import date, timedelta

from sqlalchemy import and_, distinct, func, select

from app import escandalos, processos
from app.ia_base import (FONTE_CADASTRO, FONTE_COTA, FONTE_EMENDAS, FONTE_TRAMITACAO, FONTE_TSE, FONTE_VOTACOES, brl, cargo, entendi,
                         plural, resposta)
from app.models import Candidato, CandidatoFinancas, Despesa, Parlamentar, Proposicao, Registro, Voto, Votacao
from app.nomes import nota_nome, palavras

# palavra da pergunta -> trechos que procuramos no tipo da despesa (a cota tem nomes de categoria diferentes na Câmara e no Senado)
CATEGORIAS = {
    "passag": ["passag"], "hosped": ["hosped"], "viag": ["passag", "hosped", "locomo"], "combust": ["combust"],
    "divulg": ["divulg"], "alug": ["alug", "locac"], "telefon": ["telefon", "correio"], "aliment": ["aliment"],
}
SITUACAO_LEI = re.compile(r"transformad\w* em norma|norma jur[ií]dica", re.I)
SITUACAO_ARQUIVADA = re.compile(r"arquivad", re.I)
SITUACAO_REJEITADA = re.compile(r"rejeitad", re.I)

SEM_DADO = {
    "governo": ("Não consigo listar quem ocupa os principais cargos do governo federal: a lista de ministros fica só no site, não no banco, "
                "e não existe uma base aberta única e atualizada de cargos do Executivo."),
    "tribunais": "Não existe base aberta que diga em quais tribunais uma pessoa responde a processos. O BRASIL+ não tem esse dado por pessoa.",
    "tempo_processo": "Não existe base aberta com o tempo de tramitação de processos por pessoa. O BRASIL+ não tem esse dado.",
    "impacto": "O BRASIL+ não tem o impacto financeiro previsto de cada projeto de lei: essa estimativa não é publicada como dado aberto por proposição.",
    "votos_ministros": ("Não há base aberta com o voto de cada ministro do STF, STJ e TSE. O BRASIL+ só tem 6 julgamentos do STF curados, com o placar "
                        "e a fonte (aba Julgamentos dos tribunais)."),
    "remuneracao": ("O BRASIL+ não guarda a remuneração recebida por cada parlamentar. O que há por pessoa é a cota parlamentar (gastos), "
                    "que não é salário."),
    "empresas_emendas": ("Não consigo dizer quais empresas receberam recursos ligados às emendas de uma pessoa: o BRASIL+ não tem o vínculo entre "
                         "cada emenda e a empresa que recebeu."),
}


def _p(db, e: dict) -> Parlamentar:
    return db.get(Parlamentar, e["pessoas"][0][0])


# ---------- quem representa o estado ----------

def lista_estado(db, e: dict, casa: str | None) -> dict:
    uf = e["uf"]
    quer = {"senado", "camara"} if not casa else {casa}
    partes, dados = [], {}
    for c, titulo in (("senado", "Senadores"), ("camara", "Deputados federais")):
        if c not in quer:
            continue
        nomes = db.execute(select(Parlamentar.nome, Parlamentar.partido).where(
            Parlamentar.casa == c, Parlamentar.uf == uf, Parlamentar.em_exercicio.is_(True)).order_by(Parlamentar.nome)).all()
        dados[c] = [n for n, _p_ in nomes]
        if not nomes:
            partes.append(f"{titulo}: nenhum em exercício encontrado no banco.")
            continue
        mostrados = ", ".join(f"{n} ({p or 's/p'})" for n, p in nomes[:20])
        resto = f" e mais {len(nomes) - 20}" if len(nomes) > 20 else ""
        partes.append(f"{titulo} de {uf} em exercício ({len(nomes)}): {mostrados}{resto}.")
    return resposta(True, "lista_estado", " ".join(partes), [FONTE_CADASTRO], dados,
                    "Mostra só quem está em exercício na última coleta; suplentes que assumiram aparecem quando o cadastro já os traz.")


# ---------- histórico, partidos, formação ----------

def historico_pessoa(db, e: dict) -> dict:
    p = _p(db, e)
    pre = entendi(e)
    cands = db.scalars(select(Candidato).where(Candidato.parlamentar_id == p.id).order_by(Candidato.ano)).all()
    atual = f"{p.nome}: {cargo(p.casa)}, {p.partido or 'sem partido informado'}-{p.uf or '--'}, {'em exercício' if p.em_exercicio else 'fora de exercício na última coleta'}."
    aviso = ("Só o que passou por eleição no TSE (1994 em diante): cargos nomeados, suplência e mandatos anteriores não aparecem. "
             "Troca de partido fora de ano de eleição também não aparece. Formação e ocupação são o que a própria pessoa declarou.")
    if not cands:
        return resposta(True, "historico_pessoa", pre + atual + " Não encontrei candidaturas do TSE ligadas a essa pessoa (a ligação só é feita "
                        "quando não há dúvida de homônimo).", [FONTE_CADASTRO, FONTE_TSE], {"parlamentar": p.nome}, aviso)
    linhas = [f"{c.ano}: {c.cargo or 'cargo não informado'} pelo {c.partido or 's/p'}-{c.uf or '--'} ({c.resultado or c.situacao_candidatura or 'resultado não informado'})"
              for c in cands]
    mostradas = linhas[-8:]
    partidos: list[str] = []
    for c in cands:
        if c.partido and (not partidos or partidos[-1] != c.partido):
            partidos.append(c.partido)
    ult = cands[-1]
    texto = (pre + atual + " Candidaturas no TSE" + (" (as 8 mais recentes)" if len(linhas) > 8 else "") + ": " + "; ".join(mostradas) + ". "
             f"Partidos nas candidaturas: {' → '.join(partidos)}. Última declaração ao TSE ({ult.ano}): instrução {ult.instrucao or 'não informada'}, "
             f"ocupação {ult.ocupacao or 'não informada'}.")
    return resposta(True, "historico_pessoa", texto, [FONTE_CADASTRO, FONTE_TSE],
                    {"parlamentar": p.nome, "candidaturas": [{"ano": c.ano, "cargo": c.cargo, "partido": c.partido, "uf": c.uf, "resultado": c.resultado} for c in cands],
                     "partidos": partidos}, aviso)


# ---------- patrimônio e finanças de campanha ----------

def _financas(db, p: Parlamentar):
    return db.execute(select(Candidato.ano, Candidato.cargo, CandidatoFinancas).join(
        CandidatoFinancas, and_(CandidatoFinancas.ano == Candidato.ano, CandidatoFinancas.sq_candidato == Candidato.sq_candidato)).where(
        Candidato.parlamentar_id == p.id).order_by(Candidato.ano)).all()


def patrimonio_pessoa(db, e: dict) -> dict:
    p = _p(db, e)
    pre = entendi(e)
    linhas = [(ano, cargo_, f.patrimonio) for ano, cargo_, f in _financas(db, p) if f.patrimonio is not None]
    aviso = "Valores declarados pela própria pessoa ao TSE a cada candidatura, sem correção pela inflação. Só existe em ano de eleição."
    if not linhas:
        return resposta(True, "patrimonio_pessoa", pre + f"Não encontrei patrimônio declarado ao TSE por {p.nome} no banco.", [FONTE_TSE], {}, aviso)
    por_ano = "; ".join(f"{a}: {brl(v)}" for a, _c, v in linhas)
    texto = pre + f"Patrimônio declarado por {p.nome} ao TSE: {por_ano}."
    if len(linhas) > 1:
        ini, fim = linhas[0][2], linhas[-1][2]
        dif = fim - ini
        pct = f" ({dif / ini * 100:+.0f}%)".replace(".", ",") if ini else ""
        texto += f" Do primeiro ao último declarado ({linhas[0][0]} a {linhas[-1][0]}): {'+' if dif >= 0 else '-'}{brl(abs(dif))}{pct}."
    return resposta(True, "patrimonio_pessoa", texto, [FONTE_TSE], {"parlamentar": p.nome, "declarado": [{"ano": a, "valor": v} for a, _c, v in linhas]}, aviso)


def financas_campanha(db, e: dict) -> dict:
    p = _p(db, e)
    pre = entendi(e)
    linhas = _financas(db, p)
    aviso = ("O BRASIL+ guarda a origem das receitas (fundo eleitoral, partido, pessoas físicas...) e as despesas por tipo, mas não o nome de cada "
             "doador pessoa física (o CPF não é guardado).")
    if not linhas:
        return resposta(True, "financas_campanha", pre + f"Não encontrei prestação de contas de campanha de {p.nome} no banco.", [FONTE_TSE], {}, aviso)
    ano, _c, f = linhas[-1]
    partes = [f"Campanha de {ano} de {p.nome}: receitas de {brl(f.receitas or 0)} e despesas de {brl(f.despesas or 0)}."]
    if f.receitas_por_fonte:
        top = sorted(f.receitas_por_fonte.items(), key=lambda kv: -float(kv[1] or 0))[:5]
        partes.append("Origem das receitas: " + "; ".join(f"{k}: {brl(float(v))}" for k, v in top) + ".")
    if f.despesas_por_tipo:
        top = sorted(f.despesas_por_tipo.items(), key=lambda kv: -float(kv[1] or 0))[:5]
        partes.append("Maiores tipos de despesa: " + "; ".join(f"{k}: {brl(float(v))}" for k, v in top) + ".")
    return resposta(True, "financas_campanha", pre + " ".join(partes), [FONTE_TSE], {"parlamentar": p.nome, "ano": ano}, aviso)


# ---------- projetos ----------

def _autoria(db, p: Parlamentar):
    regs = db.scalars(select(Registro).where(Registro.tipo == "tramitacao")).all()
    meus = [x for x in regs if any(str(a.get("id_externo")) == p.id_externo and (a.get("casa") or "camara") == p.casa
                                   for a in (x.dados or {}).get("autores") or [])]
    return len(regs), meus


def projetos_pessoa(db, e: dict) -> dict:
    p = _p(db, e)
    pre = entendi(e)
    cobertura, meus = _autoria(db, p)
    aviso = (f"A autoria só existe para as {cobertura} proposições com tramitação coletada no BRASIL+, que não são todas as do Congresso: "
             "um número menor aqui NÃO quer dizer que a pessoa apresentou pouco. Não há critério de projeto 'principal'.")
    if not cobertura:
        return resposta(True, "projetos_pessoa", pre + "O BRASIL+ ainda não tem tramitação de proposições coletada, então não há autoria a mostrar.",
                        [FONTE_TRAMITACAO], {}, aviso)
    ids = [int(x.chave) for x in meus if str(x.chave).isdigit()]
    props = db.scalars(select(Proposicao).where(Proposicao.id.in_(ids))).all() if ids else []
    lei = sum(1 for x in props if SITUACAO_LEI.search(x.situacao or ""))
    arq = sum(1 for x in props if SITUACAO_ARQUIVADA.search(x.situacao or "") and not SITUACAO_LEI.search(x.situacao or ""))
    rej = sum(1 for x in props if SITUACAO_REJEITADA.search(x.situacao or ""))
    andamento = len(props) - lei - arq - rej
    if not meus:
        return resposta(True, "projetos_pessoa", pre + f"Entre as {cobertura} proposições com tramitação coletada, não há nenhuma com {p.nome} como autor(a).",
                        [FONTE_TRAMITACAO], {"cobertura": cobertura, "projetos": 0}, aviso)
    from app.routers.v03 import _temas   # as áreas por palavra-chave são as mesmas do perfil do parlamentar
    temas = _temas([x.titulo or "" for x in meus] + [(x.dados or {}).get("ementa") or "" for x in meus])
    texto = (pre + f"Entre as {cobertura} proposições com tramitação coletada, {plural(len(meus), 'tem', 'têm')} {p.nome} como autor(a). "
             f"Pela situação registrada: {lei} virou(ram) lei, {arq} arquivado(s), {rej} rejeitado(s) e {andamento} em andamento ou sem decisão final.")
    if temas:
        texto += " Áreas mais frequentes (por palavra-chave da ementa): " + ", ".join(f"{t['tema']} ({t['projetos']})" for t in temas) + "."
    return resposta(True, "projetos_pessoa", texto, [FONTE_TRAMITACAO],
                    {"parlamentar": p.nome, "cobertura": cobertura, "projetos": len(meus), "lei": lei, "arquivados": arq, "rejeitados": rej, "em_andamento": andamento}, aviso)


# ---------- votações ----------

def _nominais_12m(casa: str):
    desde = date.today() - timedelta(days=365)
    return select(Votacao.id).where(Votacao.casa == casa, Votacao.data >= desde, Votacao.secreta.isnot(True),
                                    Votacao.id.in_(select(Voto.votacao_id).distinct()))


def participacao_pessoa(db, e: dict) -> dict:
    p = _p(db, e)
    pre = entendi(e)
    from app.routers.v03 import _presenca
    pres = _presenca(db, p)
    cont = dict(db.execute(select(Voto.voto, func.count()).where(Voto.parlamentar_id == p.id).group_by(Voto.voto)).all())
    aviso = ("Só votações nominais coletadas. Quem não estava em exercício na data conta como ausente, e ausência não é necessariamente falta: "
             "pode ser licença, missão ou suplente ainda não empossado. Votação secreta não entra.")
    if not pres and not cont:
        return resposta(True, "participacao_pessoa", pre + f"Não encontrei votações nominais de {p.nome} no banco.", [FONTE_VOTACOES], {}, aviso)
    partes = []
    if pres:
        ausente = pres["total"] - pres["votou"]
        partes.append(f"Nos últimos 12 meses, {p.nome} votou em {pres['votou']} das {pres['total']} votações nominais da {'Câmara' if p.casa == 'camara' else 'Senado'} "
                      f"({pres['percentual']:.0f}%), e ficou sem voto em {ausente}.".replace(".0", ""))
    favor = sum(v for k, v in cont.items() if (k or "").strip().lower() == "sim")
    contra = sum(v for k, v in cont.items() if (k or "").strip().lower() in ("não", "nao"))
    abst = sum(v for k, v in cont.items() if "absten" in (k or "").lower())
    outros = sum(cont.values()) - favor - contra - abst
    if cont:
        partes.append(f"Nas votações coletadas: {favor} a favor, {contra} contra, {abst} abstenção(ões) e {outros} de outros tipos (como obstrução).")
    return resposta(True, "participacao_pessoa", pre + " ".join(partes), [FONTE_VOTACOES],
                    {"parlamentar": p.nome, "presenca": pres, "votos": {"favor": favor, "contra": contra, "abstencao": abst, "outros": outros}}, aviso)


def _contagem_participacao(db, casa: str, uf: str | None = None, partido: str | None = None):
    ids = _nominais_12m(casa)
    total = db.scalar(select(func.count()).select_from(ids.subquery())) or 0
    q = (select(Parlamentar.id, Parlamentar.nome, Parlamentar.partido, Parlamentar.uf, func.count(distinct(Voto.votacao_id)).label("n"))
         .join(Voto, Voto.parlamentar_id == Parlamentar.id).where(Voto.votacao_id.in_(ids), Parlamentar.casa == casa, Parlamentar.em_exercicio.is_(True))
         .group_by(Parlamentar.id, Parlamentar.nome, Parlamentar.partido, Parlamentar.uf))
    if uf:
        q = q.where(Parlamentar.uf == uf)
    if partido:
        q = q.where(Parlamentar.partido == partido)
    return total, q


def ranking_participacao(db, e: dict, casa: str | None, menor: bool) -> dict:
    casa = casa or "camara"
    total, q = _contagem_participacao(db, casa, e.get("uf"), e.get("partido"))
    quem = "Câmara" if casa == "camara" else "Senado"
    quem += "".join(x for x in (f", do {e['partido']}" if e.get("partido") else "", f", de {e['uf']}" if e.get("uf") else ""))
    aviso = ("Considera só quem está em exercício e votações nominais dos últimos 12 meses. Quem entrou há pouco (suplente) aparece com menos "
             "votações sem que isso seja falta. Quem não votou em nenhuma não aparece na lista.")
    if not total:
        return resposta(True, "ranking_participacao", f"Não há votações nominais dos últimos 12 meses da {quem} no banco.", [FONTE_VOTACOES], {}, aviso)
    linhas = db.execute(q.order_by(func.count(distinct(Voto.votacao_id)).asc() if menor else func.count(distinct(Voto.votacao_id)).desc()).limit(5)).all()
    if not linhas:
        return resposta(True, "ranking_participacao", f"Não encontrei votos de parlamentares da {quem} em exercício.", [FONTE_VOTACOES], {}, aviso)
    itens = [f"{i}. {n} ({p or 's/p'}-{u or '--'}): {c} de {total} ({c / total * 100:.0f}%)" for i, (_id, n, p, u, c) in enumerate(linhas, 1)]
    titulo = "Menor" if menor else "Maior"
    return resposta(True, "ranking_participacao", f"{titulo} participação em votações nominais da {quem} nos últimos 12 meses:\n" + "\n".join(itens),
                    [FONTE_VOTACOES], {"total_votacoes": total, "ranking": [{"nome": n, "votou": c} for _i, n, _p_, _u, c in linhas]}, aviso)


# ---------- despesas por categoria ----------

def _filtro_categoria(padroes: list[str]):
    from sqlalchemy import or_
    return or_(*[func.lower(Despesa.tipo).like(f"%{x}%") for x in padroes])


def despesas_categoria(db, e: dict, padroes: list[str] | None) -> dict:
    ano = e["ano"]
    if e["pessoas"]:
        p = _p(db, e)
        pre = entendi(e)
        q = select(Despesa.tipo, func.sum(Despesa.valor)).where(Despesa.parlamentar_id == p.id)
        quem = p.nome
    else:
        pre, quem = "", "todos os parlamentares"
        q = select(Despesa.tipo, func.sum(Despesa.valor))
        ano = ano or db.scalar(select(func.max(Despesa.ano)))
    if ano:
        q = q.where(Despesa.ano == ano)
    if padroes:
        q = q.where(_filtro_categoria(padroes))
    linhas = db.execute(q.group_by(Despesa.tipo).order_by(func.sum(Despesa.valor).desc()).limit(8)).all()
    quando = f"em {ano}" if ano else "em todos os anos coletados"
    aviso = "As categorias seguem o nome usado pela Câmara e pelo Senado (são diferentes entre as casas). Valor é o reembolsado/pago, em reais."
    if not linhas:
        return resposta(True, "despesas_categoria", pre + f"Não encontrei despesas da cota de {quem} {quando} nessa categoria.", [FONTE_COTA], {}, aviso)
    total = sum(v for _t, v in linhas)
    itens = "; ".join(f"{t or 'sem categoria'}: {brl(v)}" for t, v in linhas)
    return resposta(True, "despesas_categoria", pre + f"Cota parlamentar de {quem} {quando}, por categoria (as maiores): {itens}. Soma das mostradas: {brl(total)}.",
                    [FONTE_COTA], {"quem": quem, "ano": ano, "categorias": [{"tipo": t, "total": round(v, 2)} for t, v in linhas]}, aviso)


# ---------- condenações (só casos curados) ----------

def condenacoes_lista(db, e: dict) -> dict:
    c = escandalos.crimes()
    aviso = (c["aviso"] + " Só entram os casos curados pelo BRASIL+ (cada um com fonte): isto NÃO é o total de condenações de políticos do país, e "
             "quem não aparece aqui pode ter processo, investigação ou condenação que o BRASIL+ não tem.")
    por_situacao: dict[str, int] = {}
    for i in c["itens"]:
        por_situacao[i["situacao"]] = por_situacao.get(i["situacao"], 0) + 1
    recentes = "; ".join(f"{i['nome']} ({i['situacao']}, caso {i['caso']}" + (f", {i['data_situacao']}" if i["data_situacao"] else "") + ")" for i in c["itens"][:8])
    partes = [f"Nos casos curados do BRASIL+ há {c['total']} agente(s) público(s) com condenação registrada."]
    if por_situacao:
        partes.append("Por situação: " + ", ".join(f"{k}: {v}" for k, v in sorted(por_situacao.items(), key=lambda kv: -kv[1])) +
                      " (\"condenado (recorre)\" ainda cabe recurso).")
    if recentes:
        partes.append("Mais recentes: " + recentes + ".")
    return resposta(True, "condenacoes_lista", " ".join(partes), [c["fonte"]], {"total": c["total"], "por_situacao": por_situacao}, aviso)


def casos_da_pessoa(db, p: Parlamentar) -> str:
    """Resumo dos casos curados de uma pessoa, com a situação e a data da fonte (investigado, réu, condenado... são coisas diferentes)."""
    casos = processos.do_parlamentar(db, p)["casos_curados"]
    if not casos:
        return ""
    itens = []
    for c in casos:
        data = f", em {c['data_situacao']}" if c.get("data_situacao") else ""
        itens.append(f"caso {c['caso']}: {c['situacao'] or 'situação não informada'}{data}")
    return " Casos curados: " + "; ".join(itens) + "."


# ---------- emendas ----------

def emendas_pessoa(db, e: dict) -> dict:
    p = _p(db, e)
    pre = entendi(e)
    from app.collectors.emendas import AUTORES
    consulta = palavras(p.nome)
    anos = []
    for r in db.scalars(select(Registro).where(Registro.fonte == "transparencia", Registro.tipo == "emendas_ano").order_by(Registro.ano)).all():
        for autor, v in ((r.dados or {}).get("autores") or {}).items():
            if nota_nome(consulta, palavras(autor)) >= 0.9:
                anos.append((r.ano, float(v.get("empenhado") or 0), float(v.get("pago") or 0)))
                break
    aviso = (f"O BRASIL+ guarda só os {AUTORES} maiores autores de emendas de cada ano: se a pessoa não aparece, pode ter emendas menores que o corte. "
             "Por autor há só empenhado e pago (o liquidado existe apenas no total do ano). 'Pago' soma o pago no ano e os restos a pagar pagos depois.")
    if not anos:
        return resposta(True, "emendas_pessoa", pre + f"{p.nome} não aparece entre os {AUTORES} maiores autores de emendas de nenhum ano coletado.",
                        [FONTE_EMENDAS], {}, aviso)
    por_ano = "; ".join(f"{a}: empenhado {brl(emp)}, pago {brl(pg)}" for a, emp, pg in anos)
    return resposta(True, "emendas_pessoa", pre + f"Emendas de {p.nome} (anos em que está entre os maiores autores): {por_ano}. "
                    f"Total empenhado: {brl(sum(x[1] for x in anos))}; pago: {brl(sum(x[2] for x in anos))}.",
                    [FONTE_EMENDAS], {"parlamentar": p.nome, "anos": [{"ano": a, "empenhado": emp, "pago": pg} for a, emp, pg in anos]}, aviso)


# ---------- comparação com colegas ----------

def comparar_pessoa(db, e: dict) -> dict:
    p = _p(db, e)
    pre = entendi(e)
    partes, dados = [], {}
    ano = db.scalar(select(func.max(Despesa.ano)).join(Parlamentar, Parlamentar.id == Despesa.parlamentar_id).where(Parlamentar.casa == p.casa))
    if ano:
        totais = db.execute(select(Despesa.parlamentar_id, func.sum(Despesa.valor)).join(Parlamentar, Parlamentar.id == Despesa.parlamentar_id).where(
            Despesa.ano == ano, Parlamentar.casa == p.casa).group_by(Despesa.parlamentar_id).order_by(func.sum(Despesa.valor).desc())).all()
        pos = next((i for i, (pid, _v) in enumerate(totais, 1) if pid == p.id), None)
        if pos:
            media = sum(v for _i, v in totais) / len(totais)
            partes.append(f"Cota parlamentar em {ano}: {brl(totais[pos - 1][1])}, {pos}º entre {len(totais)} com despesa na mesma casa (média: {brl(media)}).")
            dados["gasto"] = {"ano": ano, "posicao": pos, "de": len(totais)}
    total, q = _contagem_participacao(db, p.casa)
    if total:
        todos = db.execute(q.order_by(func.count(distinct(Voto.votacao_id)).desc())).all()
        pos = next((i for i, (pid, *_r) in enumerate(todos, 1) if pid == p.id), None)
        if pos:
            partes.append(f"Votações nominais nos últimos 12 meses: votou em {todos[pos - 1][4]} de {total}, {pos}º entre {len(todos)} parlamentares em exercício com voto.")
            dados["participacao"] = {"posicao": pos, "de": len(todos)}
    aviso = ("Compara só quem está na mesma casa e período, com o que o BRASIL+ tem (cota e votações nominais). Projetos e emendas não entram na "
             "comparação porque a autoria e as emendas são coletadas só em parte.")
    if not partes:
        return resposta(True, "comparar_pessoa", pre + f"Não há dados de cota ou de votações para comparar {p.nome} com colegas.", [FONTE_COTA, FONTE_VOTACOES], {}, aviso)
    return resposta(True, "comparar_pessoa", pre + f"{p.nome} em comparação com a mesma casa. " + " ".join(partes), [FONTE_COTA, FONTE_VOTACOES], dados, aviso)


def sem_dado(topico: str) -> dict:
    return resposta(True, f"sem_dado:{topico}", SEM_DADO[topico], [], {}, "Quando o dado não existe aqui, o BRASIL+ diz isso em vez de inventar. "
                    "Não ter o dado não quer dizer que a informação não existe.")
