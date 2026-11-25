"""Pesquisas financiadas com dinheiro público: leitura de app/dados/pesquisas.json (gerado por scripts/pesquisas.py).

Cada projeto é uma lista compacta (o arquivo fica pequeno); aqui ela vira dicionário. Regras que valem para toda a aba:
  * valor é sempre do tipo que a fonte diz (contratado na FAPEMIG e na FINEP, pactuado no INT) — a resposta traz `tipo_valor` e nunca soma tipos diferentes;
  * só a FINEP informa também o valor LIBERADO (`pago`: soma do que ela já repassou ao projeto); o percentual liberado é pago ÷ contratado e só existe onde há `pago`;
  * campo ausente fica nulo (a tela escreve "não informado"); nada é estimado;
  * a coluna `institucional` de cada projeto é um grupo: 0 = pesquisa; 1 = termo ou programa da própria FAPEMIG (executora SEDE); 2 = empresa (subvenção da FINEP).
    Os grupos 1 e 2 ficam fora dos rankings de instituição e das somas de "pesquisa", mas continuam na lista, marcados (`institucional`, `empresa`).
  * tipo de valor "nd" (FAPERJ): a fonte não publica valor; o valor fica nulo.
"""
from __future__ import annotations

import json
import unicodedata
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

ARQ = Path(__file__).resolve().parent / "dados" / "pesquisas.json"

AVISO = ("Dinheiro público destinado a projetos de pesquisa, como registrado por cada fonte. Valor contratado ou pactuado não é valor pago, "
         "e não mede o andamento nem o resultado científico da pesquisa. Cada fonte cobre só o que ela própria financia: não existe base nacional única.")

COLS = ["fonte", "ano", "processo", "titulo", "pesquisador", "inst", "gestora", "area", "chamada", "modalidade", "valor", "inicio", "fim", "institucional", "extra", "pago"]


def _sem_acento(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s or "") if unicodedata.category(c) != "Mn").lower()


@lru_cache(maxsize=1)
def _dados() -> dict | None:
    if not ARQ.exists():
        return None
    return json.loads(ARQ.read_text(encoding="utf-8"))


def recarregar() -> None:
    _dados.cache_clear()
    _indice.cache_clear()


def base() -> dict | None:
    """O arquivo inteiro (listas compactas), para a tela filtrar no próprio navegador."""
    d = _dados()
    if d is None:
        return None
    return {**d, "colunas": COLS, "aviso": AVISO}


def _proj(d: dict, i: int) -> dict:
    p = d["p"][i]
    r = dict(zip(COLS, p))
    r["id"] = i
    f = d["fontes"][r["fonte"]]
    r["fonte_id"], r["fonte_nome"], r["tipo_valor"] = f["id"], f["nome"], f["tipo_valor"]
    inst = d["inst"][r["inst"]]
    r["instituicao"] = {"id": r["inst"], "nome": inst[0], "sigla": inst[1], "uf": inst[2], "tipo": inst[3]}
    g = r["gestora"]
    r["gestora"] = None if g is None else {"id": g, "nome": d["inst"][g][0], "sigla": d["inst"][g][1]}
    r["area"] = None if r["area"] is None else d["areas"][r["area"]]
    r["chamada"] = None if r["chamada"] is None else d["chamadas"][r["chamada"]]
    r["modalidade"] = None if r["modalidade"] is None else d["modalidades"][r["modalidade"]]
    r["empresa"] = r["institucional"] == 2
    r["institucional"] = r["institucional"] == 1
    r["percentual_liberado"] = round(r["pago"] / r["valor"] * 100, 1) if r["pago"] is not None and r["valor"] else None
    del r["inst"]
    return r


@lru_cache(maxsize=1)
def _indice() -> dict:
    """Texto sem acento de cada projeto (para a busca) e somas por instituição."""
    d = _dados()
    busca, por_inst = [], defaultdict(lambda: {"n": 0, "valor": 0.0, "sem_valor": 0, "anos": set(), "fontes": set(), "pago": 0.0, "valor_com_pago": 0.0})
    for i, p in enumerate(d["p"]):
        inst = d["inst"][p[5]]
        area = d["areas"][p[7]] if p[7] is not None else ""
        busca.append(_sem_acento(" ".join(str(x) for x in (p[3], p[4], p[2], inst[0], inst[1], area) if x)))
        if p[13]:
            continue
        a = por_inst[p[5]]
        a["n"] += 1
        if p[10] is None:
            a["sem_valor"] += 1
        else:
            a["valor"] += p[10]
        if p[15] is not None:
            a["pago"] += p[15]
            a["valor_com_pago"] += p[10] or 0.0
        if p[1]:
            a["anos"].add(p[1])
        a["fontes"].add(d["fontes"][p[0]]["id"])
    return {"busca": busca, "inst": por_inst}


def listar(q: str = "", instituicao: int | None = None, uf: str = "", area: str = "", ano: int | None = None, fonte: str = "",
           institucional: bool | None = False, empresa: bool = False, ordem: str = "valor", limite: int = 50, pagina: int = 1) -> dict | None:
    d = _dados()
    if d is None:
        return None
    ix = _indice()
    termos = [t for t in _sem_acento(q).split() if t]
    ids = []
    for i, p in enumerate(d["p"]):
        if empresa:
            if p[13] != 2:
                continue
        elif institucional is not None and (p[13] == 1) != institucional:
            continue
        elif institucional is False and p[13] == 2:
            continue
        if instituicao is not None and p[5] != instituicao:
            continue
        if uf and d["inst"][p[5]][2] != uf.upper():
            continue
        if area and (p[7] is None or _sem_acento(d["areas"][p[7]]) != _sem_acento(area)):
            continue
        if ano and p[1] != ano:
            continue
        if fonte and d["fontes"][p[0]]["id"] != fonte:
            continue
        if termos and not all(t in ix["busca"][i] for t in termos):
            continue
        ids.append(i)
    if ordem == "ano":
        ids.sort(key=lambda i: (d["p"][i][1] or 0, d["p"][i][10] or 0), reverse=True)
    else:
        ids.sort(key=lambda i: (d["p"][i][10] is not None, d["p"][i][10] or 0), reverse=True)     # sem valor vai para o fim
    limite = max(1, min(limite, 200))
    pagina = max(1, pagina)
    fatia = ids[(pagina - 1) * limite: pagina * limite]
    valores = [d["p"][i][10] for i in ids if d["p"][i][10] is not None]
    return {"total": len(ids), "pagina": pagina, "limite": limite, "valor_total": sum(valores), "sem_valor": len(ids) - len(valores),
            "projetos": [_proj(d, i) for i in fatia], "aviso": AVISO}


def projeto(i: int) -> dict | None:
    d = _dados()
    if d is None or not 0 <= i < len(d["p"]):
        return None
    r = _proj(d, i)
    r["aviso"] = AVISO
    r["fonte_info"] = {k: d["fontes"][r["fonte"]].get(k) for k in ("id", "nome", "financiador", "url", "tipo_valor", "atualizacao", "aviso")}
    return r


def instituicoes(uf: str = "", q: str = "") -> dict | None:
    d = _dados()
    if d is None:
        return None
    ix = _indice()
    termos = [t for t in _sem_acento(q).split() if t]
    out = []
    for i, a in ix["inst"].items():
        nome, sigla, u, tipo = d["inst"][i]
        if uf and u != uf.upper():
            continue
        if termos and not all(t in _sem_acento(f"{nome} {sigla or ''}") for t in termos):
            continue
        out.append({"id": i, "nome": nome, "sigla": sigla, "uf": u, "tipo": tipo, "projetos": a["n"], "valor": a["valor"], "sem_valor": a["sem_valor"],
                    "pago": a["pago"] if a["valor_com_pago"] else None, "percentual_liberado": round(a["pago"] / a["valor_com_pago"] * 100, 1) if a["valor_com_pago"] else None,
                    "primeiro_ano": min(a["anos"]) if a["anos"] else None, "ultimo_ano": max(a["anos"]) if a["anos"] else None, "fontes": sorted(a["fontes"])})
    out.sort(key=lambda x: x["valor"], reverse=True)
    return {"total": len(out), "instituicoes": out, "aviso": AVISO}


def instituicao(i: int) -> dict | None:
    d = _dados()
    if d is None or not 0 <= i < len(d["inst"]):
        return None
    nome, sigla, uf, tipo = d["inst"][i]
    meus = [k for k, p in enumerate(d["p"]) if p[5] == i and not p[13]]
    por_ano, por_area = defaultdict(lambda: [0, 0.0]), defaultdict(lambda: [0, 0.0])
    for k in meus:
        p = d["p"][k]
        v = p[10] or 0.0
        if p[1]:
            por_ano[p[1]][0] += 1
            por_ano[p[1]][1] += v
        rot = d["areas"][p[7]] if p[7] is not None else "Não informado"
        por_area[rot][0] += 1
        por_area[rot][1] += v
    maiores = sorted(meus, key=lambda k: d["p"][k][10] or 0, reverse=True)[:15]
    gest = defaultdict(lambda: [0, 0.0])
    for k in meus:
        g = d["p"][k][6]
        if g is not None:
            gest[g][0] += 1
            gest[g][1] += d["p"][k][10] or 0.0
    valores = [d["p"][k][10] for k in meus if d["p"][k][10] is not None]
    com_pago = [k for k in meus if d["p"][k][15] is not None]
    pago, base_pago = sum(d["p"][k][15] for k in com_pago), sum(d["p"][k][10] or 0.0 for k in com_pago)
    return {"id": i, "nome": nome, "sigla": sigla, "uf": uf, "tipo": tipo, "projetos": len(meus), "valor": sum(valores), "sem_valor": len(meus) - len(valores),
            "pago": pago if com_pago else None, "contratado_com_pago": base_pago if com_pago else None, "percentual_liberado": round(pago / base_pago * 100, 1) if base_pago else None,
            "por_ano": [{"ano": a, "projetos": v[0], "valor": v[1]} for a, v in sorted(por_ano.items())],
            "por_area": sorted(({"area": a, "projetos": v[0], "valor": v[1]} for a, v in por_area.items()), key=lambda x: -x["valor"])[:12],
            "gestoras": sorted(({"id": g, "nome": d["inst"][g][0], "sigla": d["inst"][g][1], "projetos": v[0], "valor": v[1]} for g, v in gest.items()),
                               key=lambda x: -x["valor"])[:6],
            "maiores": [_proj(d, k) for k in maiores],
            "fontes": sorted({d["fontes"][d["p"][k][0]]["id"] for k in meus}), "aviso": AVISO}


def resumo() -> dict | None:
    d = _dados()
    if d is None:
        return None
    ix = _indice()
    por_ano, por_uf, por_area = defaultdict(lambda: [0, 0.0]), defaultdict(lambda: [0, 0.0, 0]), defaultdict(lambda: [0, 0.0])
    por_fonte = defaultdict(lambda: {"projetos": 0, "valor": 0.0, "sem_valor": 0, "institucional_n": 0, "institucional_valor": 0.0, "empresas_n": 0, "empresas_valor": 0.0,
                                                      "empresas_pago": 0.0, "pago": 0.0, "valor_com_pago": 0.0})
    for p in d["p"]:
        f = por_fonte[d["fontes"][p[0]]["id"]]
        if p[13] == 2:                                   # empresas (subvenção da FINEP): contadas à parte, fora de rankings e somas de pesquisa
            f["empresas_n"] += 1
            f["empresas_valor"] += p[10] or 0.0
            f["empresas_pago"] += p[15] or 0.0
            continue
        if p[13]:
            f["institucional_n"] += 1
            f["institucional_valor"] += p[10] or 0.0
            continue
        f["projetos"] += 1
        if p[10] is None:
            f["sem_valor"] += 1
        else:
            f["valor"] += p[10]
        if p[15] is not None:
            f["pago"] += p[15]
            f["valor_com_pago"] += p[10] or 0.0
        v = p[10] or 0.0
        if p[1]:
            por_ano[p[1]][0] += 1
            por_ano[p[1]][1] += v
        u = d["inst"][p[5]][2] or "?"
        por_uf[u][0] += 1
        por_uf[u][1] += v
        if p[7] is not None:
            por_area[d["areas"][p[7]]][0] += 1
            por_area[d["areas"][p[7]]][1] += v
    for i, a in ix["inst"].items():
        u = d["inst"][i][2] or "?"
        por_uf[u][2] += 1
    n = sum(f["projetos"] for f in por_fonte.values())
    valor = sum(f["valor"] for f in por_fonte.values())
    return {"gerado_em": d["gerado_em"], "projetos": n, "valor_total": valor, "instituicoes": len(ix["inst"]),
            "fontes": [{**{k: f.get(k) for k in ("id", "nome", "financiador", "uf", "url", "tipo_valor", "atualizacao", "tem_pesquisador", "tem_pago", "grupo", "aviso")},
                        **por_fonte[f["id"]]} for f in d["fontes"]],
            "por_ano": [{"ano": a, "projetos": v[0], "valor": v[1]} for a, v in sorted(por_ano.items())],
            "por_uf": [{"uf": u, "projetos": v[0], "valor": v[1], "instituicoes": v[2]} for u, v in sorted(por_uf.items(), key=lambda x: -x[1][1])],
            "por_area": [{"area": a, "projetos": v[0], "valor": v[1]} for a, v in sorted(por_area.items(), key=lambda x: -x[1][1])[:15]],
            "ufs_sem_dado": sorted(set("AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO".split()) - {u for u in por_uf}),
            "aviso": AVISO}
