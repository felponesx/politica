"""IA própria do BRASIL+: responde perguntas com o que está no banco, SEM modelo de linguagem, sem token e sem custo.

Como funciona (tudo no próprio sistema, na hora):
1. normaliza a pergunta (minúsculas, sem acento);
2. acha o TIPO da pergunta (intenção) pelas palavras: "quem mais gastou", "quantos deputados do PT", "processos de fulano"...;
3. acha o que foi citado: pessoa (mesmo escrita errada, pela busca por pronúncia de app/nomes.py), partido, estado e ano;
4. consulta o banco com uma consulta pronta e segura (nunca SQL escrito pela pergunta);
5. monta a resposta com a fonte e os avisos que valem para aquele assunto.

Limites assumidos (a resposta diz): só responde os tipos de pergunta que existem aqui; não resume texto livre nem raciocina fora disso.
Quando não entende, diz que não entendeu, sugere perguntas parecidas e guarda a pergunta (só o texto, sem IP) para virar um tipo novo.
Quando o dado não existe em base aberta (ex.: processos por pessoa), diz isso em vez de inventar.
"""
import hashlib
import logging
import re

from sqlalchemy import func, select

from app import busca, ia_local, processos
from app.models import Despesa, Parlamentar, Registro
from app.nomes import normalizar
from app.utils import upsert

log = logging.getLogger("brasilplus.ia_propria")

UF_NOMES = {
    "acre": "AC", "alagoas": "AL", "amapa": "AP", "amazonas": "AM", "bahia": "BA", "ceara": "CE", "distrito federal": "DF",
    "espirito santo": "ES", "goias": "GO", "maranhao": "MA", "mato grosso do sul": "MS", "mato grosso": "MT", "minas gerais": "MG",
    "para": "PA", "paraiba": "PB", "parana": "PR", "pernambuco": "PE", "piaui": "PI", "rio de janeiro": "RJ",
    "rio grande do norte": "RN", "rio grande do sul": "RS", "rondonia": "RO", "roraima": "RR", "santa catarina": "SC",
    "sao paulo": "SP", "sergipe": "SE", "tocantins": "TO",
}
SIGLAS_UF = set(UF_NOMES.values())

# palavras que fazem parte da pergunta e não do nome de uma pessoa
PALAVRAS_DA_PERGUNTA = set("""quem qual quais quanto quantos quantas foi e eh o a os as um uma que de da do das dos em no na nos nas com por
para tem teve ter sobre me fale diga mostre informacoes informacao perfil deputado deputada deputados deputadas senador senadora senadores
parlamentar parlamentares gastou gasto gastos gastar mais maior maiores menos cota ceap despesa despesas processo processos representacao
representacoes decoro partido estado ano hoje atual atualmente ha existem existe total numero ranking top lidera candidato candidatos
investigado condenado inquerito acusado respondeu responde ao aos pelo pela pelos pelas vez cadeira cadeiras federal federais""".split())

EXEMPLOS = [
    "Quem mais gastou com a cota parlamentar em 2024?",
    "Quanto o Nikolas Ferreira gastou em 2024?",
    "Quantos deputados do PT tem?",
    "Quantos senadores de São Paulo?",
    "Quem é a deputada Maria da Silva?",
    "Processos do Nikolas Ferreira",
]
FONTE_COTA = "Cota parlamentar: Câmara dos Deputados (cota para o exercício da atividade parlamentar) e Senado (CEAPS), dados abertos."
FONTE_CADASTRO = "Cadastro de parlamentares: Câmara dos Deputados e Senado Federal, dados abertos."


# ---------- apoio ----------

def brl(v: float) -> str:
    return "R$ " + f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _entendi(e: dict) -> str:
    """Se o nome achado não é igual ao digitado, diz quem foi entendido (a pessoa pode corrigir)."""
    _i, nome, nota = e["pessoas"][0]
    return f"Entendi que você se refere a {nome}. " if nota < 0.97 else ""


def _plural(n: int, singular: str, plural: str) -> str:
    return f"{n} {singular if n == 1 else plural}"


def _tem(tokens: list[str], *radicais: str) -> bool:
    return any(t.startswith(r) for t in tokens for r in radicais)


def _cargo(casa: str | None) -> str:
    return {"camara": "deputado(a) federal", "senado": "senador(a)"}.get(casa or "", "parlamentar")


def _resposta(entendeu: bool, intencao: str | None, texto: str, fontes: list[str] | None = None, dados: dict | None = None,
              aviso: str | None = None, sugestoes: list[str] | None = None) -> dict:
    return {"entendeu": entendeu, "intencao": intencao, "resposta": texto, "fontes": fontes or [], "dados": dados or {},
            "aviso": aviso, "sugestoes": sugestoes or []}


def _entidades(db, pergunta: str, norm: str) -> dict:
    """UF, partido, ano e pessoa citados na pergunta."""
    e: dict = {"uf": None, "partido": None, "ano": None, "pessoas": []}
    sobra = f" {norm} "
    for nome in sorted(UF_NOMES, key=len, reverse=True):          # estado pelo nome ("são paulo"), maior nome primeiro
        if f" {nome} " in sobra:
            e["uf"] = UF_NOMES[nome]
            sobra = sobra.replace(f" {nome} ", " ")
            break
    if not e["uf"]:
        m = next((s for s in re.findall(r"\b[A-Z]{2}\b", pergunta) if s in SIGLAS_UF), None)   # sigla só em maiúsculas
        if m:
            e["uf"] = m
            sobra = sobra.replace(f" {m.lower()} ", " ")
    m = re.search(r"\b(19\d{2}|20\d{2})\b", norm)
    if m:
        e["ano"] = int(m.group(1))
        sobra = sobra.replace(m.group(1), " ")

    partidos = {p.upper() for p in db.scalars(select(Parlamentar.partido).distinct()).all() if p}
    for t in re.findall(r"[A-Za-zÀ-ú]{2,}", pergunta):
        if t.upper() in partidos and (t.isupper() or re.search(rf"(?:partido|do|da|pelo)\s+{re.escape(t)}\b", pergunta, re.I)):
            e["partido"] = t.upper()
            sobra = sobra.replace(f" {normalizar(t)} ", " ")
            break

    resto = [t for t in sobra.split() if t not in PALAVRAS_DA_PERGUNTA and not t.isdigit()]
    palavras_originais = re.findall(r"[A-Za-zÀ-ú']+", pergunta)
    capitalizadas = {normalizar(w) for i, w in enumerate(palavras_originais) if i > 0 and w[:1].isupper() and (not w.isupper() or len(w) > 3)}
    e["pessoas"] = _achar_pessoas(db, resto, capitalizadas)
    return e


def _achar_pessoas(db, resto: list[str], capitalizadas: set[str] | None = None, so_completo: bool = False) -> list[tuple[int, str, float]]:
    """Parlamentares parecidos com o que sobrou da pergunta. Tenta o resto inteiro e, se não achar, trechos menores.
    Um trecho menor só vale se as palavras deixadas de fora NÃO foram escritas com inicial maiúscula (seriam parte do nome:
    "Nikolas Ferreira Costa" não pode virar "Nikolas Ferreira"). `so_completo` exige o resto inteiro."""
    if not resto:
        return []
    indice = busca._indice(db, "parlamentares", "nome")
    if indice is None:
        return []
    n = len(resto)
    capitalizadas = capitalizadas or set()
    for tamanho in range(min(n, 5), 0, -1):
        if so_completo and tamanho != n:
            continue
        for ini in range(0, n - tamanho + 1):
            trecho = resto[ini:ini + tamanho]
            if tamanho == 1 and len(trecho[0]) < 4:
                continue
            if any(t in capitalizadas for t in resto[:ini] + resto[ini + tamanho:]):   # deixaria de fora parte de um nome
                continue
            achados = indice.buscar(" ".join(trecho), 4)
            if achados:
                melhor = achados[0][2]
                return [(i, nome, nota) for i, nome, nota in achados if melhor - nota <= 0.04]   # empate = pode ser outra pessoa
    return []


def _parlamentar(db, ident: int) -> Parlamentar:
    return db.get(Parlamentar, ident)


def _guardar_sem_resposta(db, pergunta: str, norm: str) -> None:
    """Guarda a pergunta que não entendi (só o texto, sem IP), para virar um tipo novo. Se a API for só de leitura, ignora."""
    try:
        chave = hashlib.sha1(norm.encode(), usedforsecurity=False).hexdigest()[:20]
        antes = db.scalar(select(Registro).where(Registro.fonte == "ia", Registro.tipo == "pergunta_sem_resposta", Registro.chave == chave))
        n = ((antes.dados or {}).get("vezes", 0) if antes else 0) + 1
        upsert(db, Registro, {"fonte": "ia", "tipo": "pergunta_sem_resposta", "chave": chave},
               {"titulo": pergunta[:200], "valor": float(n), "dados": {"vezes": n, "pergunta": pergunta[:200]}})
        db.commit()
    except Exception as ex:   # sem permissão de escrita: tudo bem, a resposta segue
        db.rollback()
        log.debug("pergunta sem resposta não guardada: %s", type(ex).__name__)


# ---------- tipos de pergunta ----------

def _gasto_ranking(db, e: dict, casa: str | None) -> dict:
    ano = e["ano"] or db.scalar(select(func.max(Despesa.ano)))
    if not ano:
        return _resposta(True, "gasto_ranking", "Ainda não há despesas da cota parlamentar no banco.", [FONTE_COTA])
    q = (select(Parlamentar.nome, Parlamentar.partido, Parlamentar.uf, Parlamentar.casa, func.sum(Despesa.valor).label("total"))
         .join(Parlamentar, Parlamentar.id == Despesa.parlamentar_id).where(Despesa.ano == ano))
    for campo, valor in ((Parlamentar.casa, casa), (Parlamentar.uf, e["uf"]), (Parlamentar.partido, e["partido"])):
        if valor:
            q = q.where(campo == valor)
    linhas = db.execute(q.group_by(Parlamentar.id, Parlamentar.nome, Parlamentar.partido, Parlamentar.uf, Parlamentar.casa)
                        .order_by(func.sum(Despesa.valor).desc()).limit(5)).all()
    if not linhas:
        return _resposta(True, "gasto_ranking", f"Não encontrei despesas da cota em {ano} com esses filtros.", [FONTE_COTA])
    ultimo_mes = db.scalar(select(func.max(Despesa.mes)).where(Despesa.ano == ano))
    partes = [f"{i}. {n} ({p or 's/p'}-{u or '--'}): {brl(t)}" for i, (n, p, u, _c, t) in enumerate(linhas, 1)]
    onde = " ".join(x for x in (f"de {e['uf']}" if e["uf"] else "", f"do {e['partido']}" if e["partido"] else "") if x)
    texto = f"Em {ano}, quem mais gastou com a cota parlamentar {onde}".replace("  ", " ").strip() + f" foi {linhas[0][0]}, com {brl(linhas[0][4])}." + ("\nRanking:\n" + "\n".join(partes) if len(linhas) > 1 else "")
    aviso = f"Dados de {ano} até o mês {ultimo_mes}: o ano pode estar incompleto." if ultimo_mes and ultimo_mes < 12 and ano >= _ano_atual(db) else None
    return _resposta(True, "gasto_ranking", texto, [FONTE_COTA], {"ano": ano, "ranking": [{"nome": n, "partido": p, "uf": u, "total": round(t, 2)} for n, p, u, _c, t in linhas]}, aviso)


def _ano_atual(db) -> int:
    return db.scalar(select(func.max(Despesa.ano))) or 0


def _gasto_pessoa(db, e: dict) -> dict:
    ident, nome, _ = e["pessoas"][0]
    p = _parlamentar(db, ident)
    q = select(Despesa.ano, func.sum(Despesa.valor), func.max(Despesa.mes)).where(Despesa.parlamentar_id == ident).group_by(Despesa.ano).order_by(Despesa.ano.desc())
    if e["ano"]:
        q = q.where(Despesa.ano == e["ano"])
    linhas = db.execute(q).all()
    if not linhas:
        quando = f" em {e['ano']}" if e["ano"] else ""
        return _resposta(True, "gasto_pessoa", _entendi(e) + f"Não encontrei despesas da cota de {p.nome}{quando} no banco.", [FONTE_COTA])
    if e["ano"]:
        ano, total, mes = linhas[0]
        texto = f"{p.nome} ({p.partido or 's/p'}-{p.uf or '--'}) gastou {brl(total)} com a cota parlamentar em {ano}."
        aviso = f"Dados até o mês {mes}: o ano pode estar incompleto." if ano >= _ano_atual(db) and mes and mes < 12 else None
    else:
        recentes = linhas[:4]
        texto = (f"{p.nome} ({p.partido or 's/p'}-{p.uf or '--'}), cota parlamentar por ano: "
                 + "; ".join(f"{a}: {brl(t)}" for a, t, _m in recentes) + f". Total nos anos mostrados: {brl(sum(t for _a, t, _m in recentes))}.")
        aviso = None
    return _resposta(True, "gasto_pessoa", _entendi(e) + texto, [FONTE_COTA], {"parlamentar": p.nome, "por_ano": [{"ano": a, "total": round(t, 2)} for a, t, _m in linhas]}, aviso)


def _quantos(db, e: dict, casa: str | None) -> dict:
    q = select(Parlamentar.casa, func.count()).where(Parlamentar.em_exercicio.is_(True))
    for campo, valor in ((Parlamentar.casa, casa), (Parlamentar.uf, e["uf"]), (Parlamentar.partido, e["partido"])):
        if valor:
            q = q.where(campo == valor)
    por_casa = dict(db.execute(q.group_by(Parlamentar.casa)).all())
    quem = " ".join(x for x in (f"do {e['partido']}" if e["partido"] else "", f"de {e['uf']}" if e["uf"] else "") if x)
    partes = [_plural(por_casa.get(c, 0), s_, p_) for c, s_, p_ in (("camara", "deputado federal", "deputados federais"), ("senado", "senador", "senadores")) if not casa or casa == c]
    texto = f"Em exercício {quem}: ".replace("  ", " ") + " e ".join(partes) + "."
    return _resposta(True, "quantos_parlamentares", texto, [FONTE_CADASTRO], {"por_casa": por_casa})


def _perfil(db, e: dict) -> dict:
    achados = e["pessoas"]
    if len(achados) > 1:
        lista = [f"{n} ({_parlamentar(db, i).partido or 's/p'}-{_parlamentar(db, i).uf or '--'}, {_cargo(_parlamentar(db, i).casa)})" for i, n, _ in achados]
        return _resposta(True, "perfil", "Achei mais de uma pessoa com esse nome: " + "; ".join(lista) + ". Diga o nome completo.", [FONTE_CADASTRO],
                         {"opcoes": [n for _i, n, _s in achados]})
    p = _parlamentar(db, achados[0][0])
    situacao = "em exercício" if p.em_exercicio else "fora de exercício na última coleta"
    texto = _entendi(e) + f"{p.nome}: {_cargo(p.casa)}, {p.partido or 'sem partido informado'}-{p.uf or '--'}, {situacao}."
    return _resposta(True, "perfil", texto, [FONTE_CADASTRO], {"id": p.id, "nome": p.nome, "partido": p.partido, "uf": p.uf, "casa": p.casa})


def _processos_pessoa(db, e: dict) -> dict:
    ident, _nome, _ = e["pessoas"][0]
    p = _parlamentar(db, ident)
    r = processos.do_parlamentar(db, p)
    n_rep, n_reg, n_caso = len(r["representacoes_decoro"]), len(r["registro_de_candidatura"]), len(r["casos_curados"])
    if not (n_rep or n_reg or n_caso):
        texto = f"Não há registro de representação por quebra de decoro, candidatura indeferida ou caso curado de {p.nome} nas fontes que o BRASIL+ tem."
    else:
        texto = (f"Sobre {p.nome}, nas fontes que o BRASIL+ tem: {n_rep} representação(ões) por quebra de decoro na Câmara, "
                 f"{n_reg} registro(s) de candidatura com situação a destacar e {n_caso} caso(s) curado(s).")
    texto = _entendi(e) + texto + " Não existe base aberta de inquéritos e ações penais por nome; o que não está nessas fontes não aparece."
    return _resposta(True, "processos_pessoa", texto, ["Câmara dos Deputados (representações), TSE (registro de candidatura), casos curados do BRASIL+."],
                     {"parlamentar": p.nome, "representacoes": n_rep, "registros": n_reg, "casos": n_caso}, processos.AVISO)


def _processos_ranking() -> dict:
    texto = ("Não consigo dizer quem tem mais processos: não existe base aberta que traga processos judiciais por pessoa. "
             "O que o BRASIL+ tem é limitado: representações por quebra de decoro na Câmara, candidaturas com registro indeferido no TSE e os casos "
             "curados dos escândalos. Posso mostrar isso de um nome específico, por exemplo: \"Processos do Nikolas Ferreira\".")
    return _resposta(True, "processos_ranking", texto, [], {}, processos.AVISO, ["Processos do Nikolas Ferreira"])


def _executar(db, intencao: str, e: dict, casa: str | None) -> dict | None:
    """Roda um tipo de pergunta. Devolve None se faltar o que o tipo precisa (ex.: a pessoa não foi achada no banco)."""
    pessoa = bool(e["pessoas"])
    if intencao == "processos_pessoa":
        return _processos_pessoa(db, e) if pessoa else None
    if intencao == "processos_ranking":
        return _processos_ranking()
    if intencao == "gasto_ranking":
        return _gasto_ranking(db, e, casa)
    if intencao == "gasto_pessoa":
        return _gasto_pessoa(db, e) if pessoa else None
    if intencao == "quantos_parlamentares":
        return _quantos(db, e, casa)
    if intencao == "perfil":
        return _perfil(db, e) if pessoa else None
    return None


def _com_sugestao(db, e: dict, sug: dict) -> dict:
    """Junta o que o assistente viu com o que as regras já achavam. A pessoa e o partido SEMPRE são conferidos no banco."""
    novo = dict(e)
    if sug["nome"]:
        resto = [t for t in normalizar(sug["nome"]).split() if t not in PALAVRAS_DA_PERGUNTA]
        novo["pessoas"] = _achar_pessoas(db, resto, None, so_completo=True) or e["pessoas"]
    if sug["uf"]:
        novo["uf"] = sug["uf"]
    if sug["ano"]:
        novo["ano"] = sug["ano"]
    if sug["partido"] and sug["partido"] in {x.upper() for x in db.scalars(select(Parlamentar.partido).distinct()).all() if x}:
        novo["partido"] = sug["partido"]
    return novo


# ---------- entrada ----------

def responder(db, pergunta: str) -> dict:
    pergunta = (pergunta or "").replace("\x00", " ").strip()[:300]
    norm = normalizar(pergunta)
    tokens = norm.split()
    e = _entidades(db, pergunta, norm)
    pessoa = bool(e["pessoas"])
    f_gasto = _tem(tokens, "gast", "despes", "cota", "ceap")
    f_mais = _tem(tokens, "mais", "maior", "ranking", "top", "lider")
    f_quant = _tem(tokens, "quant", "numero", "total")
    f_cargo = _tem(tokens, "deputad", "senador", "parlament")
    f_proc = _tem(tokens, "process", "representac", "decoro", "investig", "condenad", "inquerit", "acusad", "respond")
    casa = "senado" if _tem(tokens, "senador") and not _tem(tokens, "deputad") else "camara" if _tem(tokens, "deputad") and not _tem(tokens, "senador") else None

    regra = ("processos_pessoa" if f_proc and pessoa else "processos_ranking" if f_proc and f_mais else
             "gasto_ranking" if f_gasto and f_mais and not pessoa else "gasto_pessoa" if f_gasto and pessoa else
             "quantos_parlamentares" if f_quant and f_cargo else "perfil" if pessoa else None)
    if regra:
        return _executar(db, regra, e, casa)

    # As regras não entenderam. Se o assistente local estiver ligado (opcional), ele sugere o tipo e o que foi citado;
    # o motor confere tudo no banco e é ele quem responde.
    sugestao = ia_local.classificar(pergunta)
    if sugestao:
        r = _executar(db, sugestao["intencao"], _com_sugestao(db, e, sugestao), sugestao["casa"] or casa)
        if r:
            r["assistente"] = "modelo local"
            return r
    _guardar_sem_resposta(db, pergunta, norm)
    return _resposta(False, None, "Não entendi essa pergunta. Posso responder, por exemplo:\n- " + "\n- ".join(EXEMPLOS)
                     + "\nGuardei a pergunta para aprender um tipo novo.", [], {}, None, EXEMPLOS)
