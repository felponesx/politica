"""Quando a IA própria não consegue responder, ela PERGUNTA DE VOLTA em vez de só dizer "não entendi".

A resposta traz, além do texto:
- `entendi`: o que foi reconhecido (assunto, pessoa, estado, partido, ano);
- `falta`: o que não deu para identificar;
- `pergunta_de_volta`: a pergunta objetiva que a IA faz;
- `sugestoes`: perguntas prontas para escolher, já com o nome preenchido quando possível.

Regra de segurança: quando um nome foi citado mas não bateu inteiro, a IA só SUGERE ("você quis dizer...?"): nunca responde sobre a pessoa
antes de a pessoa confirmar. Sem rede, sem modelo, sem custo.
"""
import zlib

from app.ia_base import resposta

# flag -> (assunto, pergunta com nome, pergunta geral sem nome)
ASSUNTOS = {
    "gasto": ("gastos da cota parlamentar", "Quanto {n} gastou com a cota parlamentar?", "Quem mais gastou com a cota parlamentar?"),
    "part": ("votações e participação", "Quantas vezes {n} votou a favor, contra ou se absteve?",
             "Quais parlamentares possuem maior participação em votações nominais?"),
    "proj": ("projetos de lei", "Quantos projetos de lei {n} apresentou?", None),
    "proc": ("processos e investigações", "Processos de {n}", "Quais políticos possuem condenações registradas?"),
    "cond": ("condenações", "{n} possui condenações?", "Quais políticos possuem condenações registradas?"),
    "patr": ("patrimônio declarado", "Qual o patrimônio declarado de {n}?", None),
    "hist": ("histórico, cargos e partidos", "Qual é o histórico político de {n}?", None),
    "emenda": ("emendas parlamentares", "Quanto das emendas de {n} foi empenhado e pago?", None),
    "camp": ("campanha eleitoral", "Quais foram as receitas de campanha de {n}?", None),
    "comp": ("comparação com outros parlamentares", "Como {n} se compara com os outros parlamentares?", None),
    "quant": ("quantidade de parlamentares", None, "Quantos deputados do PT tem?"),
}
# assuntos que só fazem sentido para UMA pessoa (sem nome, falta saber "de quem")
PRECISAM_DE_PESSOA = {"proj", "patr", "hist", "emenda", "camp", "comp", "part", "gasto", "proc", "cond"}

PADRAO = {"nome": None, "ano": None, "uf": None, "partido": None}


def amostra(db, pergunta: str, e: dict | None = None) -> dict:
    """Nome, ano, estado e partido REAIS do banco para os exemplos. Varia conforme a pergunta (escolha estável, sem sorteio):
    perguntas diferentes mostram pessoas diferentes; a mesma pergunta mostra sempre as mesmas. Estado, partido e ano citados pela pessoa mandam."""
    from sqlalchemy import func, select

    from app.models import Despesa, Parlamentar
    e = e or {}
    a = dict(PADRAO)
    try:
        ids = db.execute(select(Parlamentar.id).where(Parlamentar.em_exercicio.is_(True), Parlamentar.partido.is_not(None),
                                                      Parlamentar.uf.is_not(None)).order_by(Parlamentar.id)).scalars().all()
        if ids:
            p = db.get(Parlamentar, ids[zlib.crc32(pergunta.lower().encode()) % len(ids)])
            a.update(nome=p.nome, uf=p.uf, partido=p.partido)
        a["ano"] = db.execute(select(func.max(Despesa.ano))).scalar()
    except Exception:   # exemplo é enfeite: nunca derruba a resposta
        pass
    for k in ("uf", "partido", "ano"):
        if e.get(k):
            a[k] = e[k]
    return a


def opcoes_gerais(a: dict | None = None) -> list[str]:
    a = a or PADRAO
    n, ano, uf, pt = a.get("nome"), a.get("ano"), a.get("uf"), a.get("partido")
    r = [f"Quem mais gastou com a cota parlamentar{f' em {ano}' if ano else ''}?"]
    if n:
        r += [f"Quanto {n} gastou com a cota parlamentar{f' em {ano}' if ano else ''}?", f"Qual é o histórico político de {n}?"]
    r.append(f"Quantos deputados do {pt} tem?" if pt else "Quantos deputados e senadores existem?")
    r.append(f"Quais senadores representam {uf}?" if uf else "Quais senadores têm mais mandatos?")
    r += ["Quais parlamentares possuem maior participação em votações nominais?", "Quais políticos possuem condenações registradas?"]
    if n:
        r.append(f"Qual foi o patrimônio declarado de {n}?")
    return r


ORDEM_PESSOA = ("gasto", "part", "proj", "hist", "patr", "proc", "comp", "emenda")


def opcoes_da_pessoa(nome: str) -> list[str]:
    """Perguntas prontas sobre uma pessoa, com o nome já preenchido."""
    return [ASSUNTOS[k][1].format(n=nome) for k in ORDEM_PESSOA]


def _lista(itens: list[str]) -> str:
    return "\n".join(f"- {x}" for x in itens)


def esclarecer(e: dict, flags: dict, parecidos: list[dict], ex: dict | None = None) -> dict:
    """`e`: o que foi achado na pergunta (uf, partido, ano, pessoas, nome_citado). `flags`: assuntos reconhecidos pelas palavras.
    `parecidos`: parlamentares com nome parecido ao citado ([{nome, partido, uf, casa}]), só para sugerir."""
    ex = ex or PADRAO
    gerais = opcoes_gerais(ex)
    assuntos = [k for k in ASSUNTOS if flags.get(k)]
    rotulos = [ASSUNTOS[k][0] for k in assuntos]
    entendi: dict = {"assunto": rotulos, "pessoa": None, "estado": e.get("uf"), "partido": e.get("partido"), "ano": e.get("ano")}
    falta: list[str] = []
    opcoes: list[str] = []

    if e.get("nome_citado") and parecidos:
        falta.append("qual pessoa você quis dizer")
        nomes = [f"{p['nome']} ({p['partido'] or 's/p'}-{p['uf'] or '--'})" for p in parecidos]
        volta = f"Você quis dizer {', '.join(nomes[:-1]) + ' ou ' + nomes[-1] if len(nomes) > 1 else nomes[0]}? Escreva o nome completo e eu respondo."
        for p in parecidos[:3]:
            opcoes.append(ASSUNTOS[assuntos[0]][1].format(n=p["nome"]) if assuntos and ASSUNTOS[assuntos[0]][1] else f"Quem é {p['nome']}?")
    elif e.get("nome_citado"):
        falta.append("uma pessoa que esteja no cadastro de deputados e senadores")
        volta = ("Não encontrei ninguém com esse nome entre os deputados e senadores que o BRASIL+ tem (hoje só localizo parlamentares pelo nome). "
                 "Você escreveu o nome completo? É deputado(a) ou senador(a)? De que estado?")
        opcoes = gerais[:4]
    elif assuntos and any(a in PRECISAM_DE_PESSOA for a in assuntos):
        falta.append("de quem você quer saber (nome de um deputado ou senador)")
        volta = "De qual parlamentar? Diga o nome" + (f" (por exemplo, {ex['nome']})." if ex.get("nome") else ".")
        for a in assuntos:
            geral = ASSUNTOS[a][2]
            if geral and a == "gasto" and e.get("ano"):
                geral = f"Quem mais gastou com a cota parlamentar em {e['ano']}?"
            if geral:
                opcoes.append(geral)
        if ex.get("nome") and ASSUNTOS[assuntos[0]][1]:
            opcoes.append(ASSUNTOS[assuntos[0]][1].format(n=ex["nome"]))
        elif len(gerais) > 1:
            opcoes.append(gerais[1])
    elif e.get("uf") or e.get("partido") or e.get("ano"):
        falta.append("o que você quer saber")
        partes = [x for x in (f"estado {e['uf']}" if e.get("uf") else "", f"partido {e['partido']}" if e.get("partido") else "",
                              f"ano {e['ano']}" if e.get("ano") else "") if x]
        volta = f"Entendi {', '.join(partes)}, mas o que você quer saber sobre isso?"
        if e.get("uf"):
            opcoes += [f"Quais senadores representam {e['uf']}?", f"Quantos deputados de {e['uf']}?"]
        if e.get("partido"):
            opcoes += [f"Quantos deputados do {e['partido']} tem?", f"Quais parlamentares do {e['partido']} possuem maior participação em votações nominais?"]
        if e.get("ano"):
            opcoes.append(f"Quem mais gastou com a cota parlamentar em {e['ano']}?")
    else:
        falta += ["quem (o nome de um deputado ou senador)", "o quê (gastos, votações, projetos, histórico, patrimônio, processos...)"]
        volta = "Sobre quem ou sobre o quê você quer saber?"
        opcoes = gerais

    opcoes = list(dict.fromkeys(opcoes))[:8]
    reconhecido = [f"assunto: {', '.join(rotulos)}" if rotulos else "", f"estado: {e['uf']}" if e.get("uf") else "",
                   f"partido: {e['partido']}" if e.get("partido") else "", f"ano: {e['ano']}" if e.get("ano") else ""]
    reconhecido = [x for x in reconhecido if x]
    texto = ("Ainda não consigo responder, mas vou te ajudar a perguntar.\n"
             + ("Entendi: " + "; ".join(reconhecido) + ".\n" if reconhecido else "Não consegui reconhecer o assunto nem a pessoa.\n")
             + "Faltou: " + "; ".join(falta) + ".\n" + volta
             + "\nVocê pode tentar:\n" + _lista(opcoes) + "\nVeja tudo o que sei responder, e o que o BRASIL+ não tem, em /ia/cobertura. Guardei a pergunta para aprender um tipo novo.")
    r = resposta(False, None, texto, [], {}, None, opcoes)
    r.update(entendi=entendi, falta=falta, pergunta_de_volta=volta)
    return r
