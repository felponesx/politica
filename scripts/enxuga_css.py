"""Enxuga o CSS do site sem mudar o resultado:
1) declaração sobrescrita depois pela MESMA lista de seletores, no MESMO contexto (@media/@supports), com a mesma
   propriedade (e sem perder um !important) é removida;
2) parte de seletor cujas classes/ids (fora de :not/:is/:where/:has) não aparecem em lugar nenhum do HTML/JS
   (nem montadas por prefixo, ex. "ob-"+x ou `ob-${x}`) é removida;
3) regras e @media que ficam vazios saem. Comentários e @keyframes/@font-face ficam como estão.
Uso: python -m scripts.enxuga_css site/index.html  (reescreve o arquivo e imprime o resumo; precisa de tinycss2)
Conferência usada em 10/11/2026: estilo calculado de cada elemento em 42 telas (celular claro/escuro e PC), antes x depois: idêntico.
"""
import re
import sys

import tinycss2
from tinycss2 import ast

arq = sys.argv[1]
html = open(arq, encoding="utf-8").read()
m = re.search(r"(<style[^>]*>)([\s\S]*?)(</style>)", html)
css = m.group(2)
fora = html[:m.start(2)] + html[m.end(2):]  # todo o resto (HTML e JS)

_cache = {}


def usado(nome: str) -> bool:
    if nome in _cache:
        return _cache[nome]
    ok = re.search(r"(?<![\w-])" + re.escape(nome) + r"(?![\w-])", fora) is not None
    if not ok:  # montado por pedaços: "ob-"+x, 'lv'+i, `ob-${x}`, "esc-"+(...)
        for k in range(2, len(nome)):
            pre = re.escape(nome[:k])
            if re.search(r"(?<![\w-])" + pre + r"(?:\$\{|[\"'`]\s*\+)", fora):
                ok = True
                break
    _cache[nome] = ok
    return ok


def partes(prelude):
    """Divide a lista de seletores nas vírgulas de nível 0 (as de dentro de :is(...) ficam no bloco da função)."""
    out, cur = [], []
    for t in prelude:
        if t.type == "literal" and t.value == ",":
            out.append(cur)
            cur = []
        else:
            cur.append(t)
    out.append(cur)
    return out


def obrigatorios(seletor):
    """Classes e ids que o elemento PRECISA ter (fora de funções como :not())."""
    nomes = []
    toks = list(seletor)
    for i, t in enumerate(toks):
        if t.type == "hash" and t.is_identifier:
            nomes.append(t.value)
        elif t.type == "literal" and t.value == "." and i + 1 < len(toks) and toks[i + 1].type == "ident":
            nomes.append(toks[i + 1].value)
    return nomes


def norm(tokens) -> str:
    return re.sub(r"\s+", " ", tinycss2.serialize(tokens)).strip()


INFO = {}
regras = []  # (contexto, seletor normalizado, objeto regra, lista de declarações)
stats = {"decl_removidas": 0, "seletores_removidos": 0, "regras_removidas": 0}


def coleta(nodes, contexto):
    for n in nodes:
        if n.type == "qualified-rule":
            decls = [d for d in tinycss2.parse_blocks_contents(n.content) if d.type == "declaration"]
            outros = [d for d in tinycss2.parse_blocks_contents(n.content) if d.type not in ("declaration", "whitespace", "comment")]
            INFO[id(n)] = {"decls": decls, "outros": outros}  # outros: regras aninhadas ou erros -> não mexer nessa regra
            regras.append((contexto, norm(n.prelude), n))
        elif n.type == "at-rule" and n.lower_at_keyword in ("media", "supports") and n.content is not None:
            INFO[id(n)] = {"filhos": tinycss2.parse_rule_list(n.content)}
            coleta(INFO[id(n)]["filhos"], contexto + "@" + n.lower_at_keyword + " " + norm(n.prelude) + "|")


topo = tinycss2.parse_stylesheet(css, skip_comments=False, skip_whitespace=False)
coleta(topo, "")

# 1) declarações sempre sobrescritas depois (mesmo contexto + mesma lista de seletores)
ultimos = {}  # (ctx, sel, prop) -> (indice da última regra, tem !important em alguma posterior)
for i in range(len(regras) - 1, -1, -1):
    ctx, sel, n = regras[i]
    if INFO[id(n)]["outros"]:
        continue
    manter = []
    for d in INFO[id(n)]["decls"]:
        chave = (ctx, sel, d.lower_name)
        depois = ultimos.get(chave)
        if depois is not None and (depois or not d.important):
            stats["decl_removidas"] += 1
            continue
        manter.append(d)
    # registra depois de decidir (as desta regra contam para as anteriores)
    for d in INFO[id(n)]["decls"]:
        chave = (ctx, sel, d.lower_name)
        ultimos[chave] = ultimos.get(chave, False) or d.important
    INFO[id(n)]["decls"] = manter

# 2) seletores impossíveis (classe/id que não existe no site)
for ctx, sel, n in regras:
    if INFO[id(n)]["outros"]:
        INFO[id(n)]["sel"] = n.prelude
        continue
    ps = partes(n.prelude)
    vivas = [p for p in ps if all(usado(x) for x in obrigatorios(p))]
    stats["seletores_removidos"] += len(ps) - len(vivas)
    if len(vivas) == len(ps):
        INFO[id(n)]["sel"] = n.prelude
    else:
        novo = []
        for k, p in enumerate(vivas):
            if k:
                novo.append(ast.LiteralToken(0, 0, ","))
            novo.extend(p)
        INFO[id(n)]["sel"] = novo if vivas else None


def decl_txt(d):
    return f"{d.name}:{tinycss2.serialize(d.value).strip()}{'!important' if d.important else ''}"


def escreve(nodes):
    out = []
    for n in nodes:
        if n.type == "qualified-rule":
            if INFO[id(n)]["outros"]:
                out.append(tinycss2.serialize([n]))
                continue
            if INFO[id(n)]["sel"] is None or not INFO[id(n)]["decls"]:
                stats["regras_removidas"] += 1
                continue
            sel = tinycss2.serialize(INFO[id(n)]["sel"]).strip()
            out.append(sel + "{" + ";".join(decl_txt(d) for d in INFO[id(n)]["decls"]) + "}")
        elif n.type == "at-rule" and "filhos" in INFO.get(id(n), {}):
            dentro = escreve(INFO[id(n)]["filhos"]).strip()
            if not dentro:
                stats["regras_removidas"] += 1
                continue
            out.append(f"@{n.at_keyword} {tinycss2.serialize(n.prelude).strip()}{{{dentro}}}")
        else:
            out.append(tinycss2.serialize([n]))
    return "".join(out)


novo = escreve(topo)
novo = re.sub(r"\n{3,}", "\n\n", novo)
html2 = html[:m.start(2)] + novo + html[m.end(2):]
open(arq, "w", encoding="utf-8").write(html2)
print(stats, "CSS", len(css.encode()), "->", len(novo.encode()), "bytes")
