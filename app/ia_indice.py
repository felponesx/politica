"""Índice da IA do BRASIL+: rankings prontos para perguntas como "quem mais gastou", "quem foi o mais votado" e
"quem está há mais tempo no poder".

É montado a partir das respostas da API já guardadas na cópia estática (`dados`: caminho → resposta), por isso
funciona igual no robô (scripts/exportar_snapshot.py) e numa cópia já pronta (scripts/indice_ia.py).

Limitações (vão junto no índice, para a IA repetir):
- mandatos: só eleições que o BRASIL+ tem (TSE, 1994 em diante). Em 2002 o arquivo do TSE marca todos os
  candidatos a deputado, senador e governador como eleitos, então 2002 só entra para presidente. Suplentes que
  assumiram, cargos nomeados (ministro, secretário) e vereadores não entram.
- a mesma pessoa é reconhecida pelo nome no mesmo estado (o TSE não publica CPF em todos os anos). Nomes de urna
  diferentes ("GENOINO" e "JOSÉ GENOINO") só são unidos quando não há outra pessoa possível; homônimos no mesmo
  ano e cargo não são unidos.
"""
from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from datetime import date

DURACAO = {"PRESIDENTE": 4, "GOVERNADOR": 4, "SENADOR": 8, "DEPUTADO FEDERAL": 4, "DEPUTADO ESTADUAL": 4,
           "DEPUTADO DISTRITAL": 4, "PREFEITO": 4}
CARGOS = list(DURACAO)
# anos em que a situação "eleito" do arquivo do TSE não serve para o cargo
SEM_ELEITOS = {(2002, c) for c in ("DEPUTADO FEDERAL", "DEPUTADO ESTADUAL", "DEPUTADO DISTRITAL", "SENADOR", "GOVERNADOR")}
_ROTA = re.compile(r"^/eleicoes/(\d{4})/([A-Z]{2})\?cargo=([^&]+)&turno=(\d)$")


def _norm(nome: str) -> str:
    t = unicodedata.normalize("NFD", nome or "").encode("ascii", "ignore").decode().upper()
    return " ".join(re.sub(r"[^A-Z ]", " ", t).split())


def _gastos(dados: dict) -> dict:
    lista = dados.get("/parlamentares") or {}
    itens, anos = [], set()
    for p in lista.get("itens", []) if isinstance(lista, dict) else []:
        if p.get("casa") not in ("camara", "senado"):
            continue
        d = dados.get(f"/parlamentares/{p['id']}")
        if not isinstance(d, dict) or not d.get("total_gasto"):
            continue
        por_ano = defaultdict(float)
        for g in d.get("gastos_por_tipo") or []:
            if g.get("ano"):
                por_ano[int(g["ano"])] += g.get("total") or 0
        anos.update(por_ano)
        itens.append([p["id"], p["nome"], p.get("partido"), p.get("uf"), p["casa"], round(d["total_gasto"], 2),
                      {str(a): round(v, 2) for a, v in sorted(por_ano.items())}])
    itens.sort(key=lambda x: -x[5])
    return {"campos": ["id", "nome", "partido", "uf", "casa", "total", "por_ano"], "itens": itens,
            "anos": sorted(anos),
            "fonte": "Câmara dos Deputados (Cota para o Exercício da Atividade Parlamentar) e Senado Federal (CEAPS)",
            "nota": "Total das notas da cota parlamentar coletadas pelo BRASIL+ nos anos indicados; não inclui salário "
                    "nem verba de gabinete."}


def _eleicoes(dados: dict):
    """Eleitos e mais votados de cada eleição guardada (sem repetir turno nem a lista por estado do presidente)."""
    eleitos, votados = {}, {}
    for k, v in dados.items():
        m = _ROTA.match(k)
        if not m or not isinstance(v, dict):
            continue
        ano, uf, cargo, turno = int(m[1]), m[2], m[3], int(m[4])
        if cargo == "PRESIDENTE" and uf != "BR":
            continue
        for e in v.get("mais_votados") or []:
            chave = (ano, cargo, uf, e.get("sq_candidato"))
            if e.get("votos") and (chave not in votados or votados[chave][0] < e["votos"]):
                votados[chave] = (e["votos"], e.get("nome"), e.get("partido"), e.get("unidade"), e.get("percentual"), turno)
        if (ano, cargo) in SEM_ELEITOS:
            continue
        for e in v.get("eleitos") or []:
            if not str(e.get("situacao") or "").upper().startswith("ELEITO"):
                continue
            chave = (ano, cargo, uf, e.get("sq_candidato"))
            if chave not in eleitos or turno > eleitos[chave]["turno"]:
                eleitos[chave] = {"ano": ano, "cargo": cargo, "uf": uf, "sq": e.get("sq_candidato"), "nome": e.get("nome") or "",
                                  "partido": e.get("partido"), "unidade": e.get("unidade"), "votos": e.get("votos"), "turno": turno}
    return list(eleitos.values()), votados


def _pessoas(eleitos: list) -> list:
    """Junta os mandatos da mesma pessoa (mesmo nome no mesmo estado; presidente pelo nome)."""
    # homônimos: dois candidatos diferentes com o mesmo nome no mesmo ano, cargo e estado não são unidos
    vistos, homonimos = defaultdict(set), set()
    for e in eleitos:
        vistos[(e["ano"], e["cargo"], e["uf"], _norm(e["nome"]))].add(e["sq"])
    for (ano, cargo, uf, n), sqs in vistos.items():
        if len(sqs) > 1:
            homonimos.add((uf, n))
    grupos = defaultdict(list)
    for e in eleitos:
        n = _norm(e["nome"])
        if not n:
            continue
        uf = e["uf"]
        chave = (uf, n) if (uf, n) not in homonimos else (uf, n, e["sq"])
        grupos[chave].append(e)
    # nome curto contido num nome maior do mesmo estado, com o mesmo sobrenome final e um só candidato possível
    por_uf = defaultdict(list)
    for chave in grupos:
        if len(chave) == 2:
            por_uf[chave[0]].append(chave[1])
    destino = {}
    for uf, nomes in por_uf.items():
        tokens = {n: set(n.split()) for n in nomes}
        for n in nomes:
            t = n.split()
            if len(t) < 2:
                continue
            maiores = [m for m in nomes if m != n and m.split()[-1] == t[-1] and tokens[n] < tokens[m]]
            if len(maiores) == 1:
                destino[(uf, n)] = (uf, maiores[0])
    for origem, alvo in destino.items():
        while alvo in destino:
            alvo = destino[alvo]
        if origem in grupos and alvo in grupos and origem != alvo:
            grupos[alvo].extend(grupos.pop(origem))
    hoje = date.today().year
    pessoas = []
    for chave, mandatos in grupos.items():
        mandatos.sort(key=lambda x: (x["ano"], x["cargo"]))
        anos = set()
        for m in mandatos:
            ini = m["ano"] + 1
            anos.update(range(ini, ini + DURACAO.get(m["cargo"], 4)))
        cumpridos = len([a for a in anos if a <= hoje])
        nome = max((m["nome"] for m in mandatos), key=lambda s: (len(s.split()), len(s)))
        ultimo = mandatos[-1]
        # mandato compacto: [ano, cargo (índice em CARGOS), partido, votos, cidade (só prefeito), estado (só se mudou)]
        pessoas.append([nome, chave[0], ultimo.get("partido"), cumpridos, len(mandatos),
                        [[m["ano"], CARGOS.index(m["cargo"]), m.get("partido"), m.get("votos"),
                          m.get("unidade") if m["cargo"] == "PREFEITO" else "", m["uf"] if m["uf"] != chave[0] else ""]
                         for m in mandatos]])
    pessoas.sort(key=lambda p: (-p[3], -p[4], p[0]))
    return pessoas


def _mais_votados(votados: dict) -> dict:
    out = defaultdict(lambda: defaultdict(list))
    for (ano, cargo, uf, sq), (votos, nome, partido, unidade, pct, turno) in votados.items():
        if (ano, cargo) in SEM_ELEITOS and cargo != "PRESIDENTE":
            continue
        out[cargo][str(ano)].append([nome, partido, uf, unidade, votos, pct, turno, sq])
    return {c: {a: sorted(l, key=lambda x: -(x[4] or 0))[:40] for a, l in sorted(anos.items())} for c, anos in out.items()}


def montar(dados: dict) -> dict:
    eleitos, votados = _eleicoes(dados)
    return {
        "versao": 1,
        "gerado_em": date.today().isoformat(),
        "gastos": _gastos(dados),
        "mandatos": {
            "campos": ["nome", "uf", "partido_atual", "anos_no_poder_ate_hoje", "mandatos_ganhos",
                       "mandatos[ano da eleição, cargo, partido, votos, cidade, estado se outro]"],
            "cargos": CARGOS,
            "itens": _pessoas(eleitos),
            "fonte": "Tribunal Superior Eleitoral (resultados por candidato, 1994 em diante)",
            "nota": ("Conta só mandatos ganhos nas eleições que o BRASIL+ tem (1994 em diante; 2002 só para presidente; "
                     "faltam as eleições para presidente de 2006 e 2010). Não entram vereadores, suplentes que assumiram, "
                     "cargos nomeados nem mandatos anteriores a 1995. A mesma pessoa é reconhecida pelo nome no mesmo "
                     "estado; homônimos não são unidos."),
        },
        "mais_votados": {"campos": ["nome", "partido", "uf", "cidade", "votos", "percentual", "turno", "sq_candidato"],
                         "por_cargo": _mais_votados(votados),
                         "fonte": "Tribunal Superior Eleitoral",
                         "nota": "Até 40 mais votados do país em cada eleição e cargo (deputados, senadores e governadores: "
                                 "soma por estado). Presidente: turno indicado."},
        "aviso": "Aparecer num ranking não indica irregularidade; os números vêm das bases oficiais citadas.",
    }
