"""Emendas parlamentares (Portal da Transparência), sem chave de acesso.

Arquivo único: https://portaldatransparencia.gov.br/download-de-dados/emendas-parlamentares/UNICO (zip de ~30 MB). Usamos
EmendasParlamentares.csv (uma linha por emenda, local, função e ação, com valores empenhado, liquidado e pago) e guardamos
só as somas de cada ano: por tipo de emenda, função, estado e autor.
"""
import csv
import io
import os
import re
import tempfile
import zipfile

from app import http
from app.collectors.base import registrar_coleta
from app.models import Registro
from app.utils import sem_acento, upsert

URL = "https://portaldatransparencia.gov.br/download-de-dados/emendas-parlamentares/UNICO"
UA = {"User-Agent": "Mozilla/5.0 (BRASIL+ coletor de dados publicos)", "Accept": "*/*"}
AUTORES = 30


def _n(v) -> float:
    try:
        return float(str(v).replace(".", "").replace(",", ".")) if str(v).strip() else 0.0
    except ValueError:
        return 0.0


def _col(cab, *expr):
    norm = [re.sub(r"\s+", " ", sem_acento(c).lower()).strip() for c in cab]
    for e in expr:
        for i, h in enumerate(norm):
            if re.search(e, h):
                return i
    return None


def _tipo(t: str) -> str:
    """Nome curto do tipo de emenda: 'Emenda Individual - Transferências com Finalidade Definida' → 'Individual'."""
    t = re.sub(r"^emenda\s+(de\s+)?", "", t.strip(), flags=re.I)
    t = t.split(" - ")[0].strip()
    return t[:1].upper() + t[1:] if t else "Sem informação"


def agregar_emendas(texto: str) -> dict:
    """{ano: {...}} somando o CSV de emendas (valores em reais)."""
    leitor = csv.reader(io.StringIO(texto), delimiter=";")
    cab = next(leitor)
    i = {"ano": _col(cab, r"^ano da emenda"), "tipo": _col(cab, r"^tipo de emenda"), "autor": _col(cab, r"^nome do autor"),
         "uf": _col(cab, r"^uf$"), "funcao": _col(cab, r"^nome funcao"), "emp": _col(cab, r"^valor empenhado"),
         "liq": _col(cab, r"^valor liquidado"), "pago": _col(cab, r"^valor pago$"), "rap": _col(cab, r"^valor restos a pagar pagos")}
    faltam = [k for k, v in i.items() if v is None]
    if faltam:
        raise ValueError(f"Arquivo das emendas mudou: faltam {faltam} em {cab[:10]}")
    out: dict[int, dict] = {}
    for l in leitor:
        if len(l) <= max(i.values()):
            continue
        try:
            ano = int(l[i["ano"]])
        except ValueError:
            continue
        a = out.setdefault(ano, {"empenhado": 0.0, "liquidado": 0.0, "pago": 0.0, "restos_pagos": 0.0, "n": 0,
                                 "tipos": {}, "funcoes": {}, "ufs": {}, "autores": {}})
        emp, liq, pago, rap = _n(l[i["emp"]]), _n(l[i["liq"]]), _n(l[i["pago"]]), _n(l[i["rap"]])
        a["empenhado"] += emp
        a["liquidado"] += liq
        a["pago"] += pago
        a["restos_pagos"] += rap
        a["n"] += 1
        efetivo = pago + rap  # o que de fato saiu: pago no ano mais restos a pagar pagos depois
        for chave, nome in (("tipos", _tipo(l[i["tipo"]])), ("funcoes", l[i["funcao"]] or "Sem função"), ("ufs", l[i["uf"]].strip())):
            d = a[chave].setdefault(nome, {"empenhado": 0.0, "pago": 0.0})
            d["empenhado"] += emp
            d["pago"] += efetivo
        au = l[i["autor"]].strip()
        if au and au.lower() not in ("sem informação", "s/i"):
            d = a["autores"].setdefault(au, {"empenhado": 0.0, "pago": 0.0})
            d["empenhado"] += emp
            d["pago"] += efetivo
    for a in out.values():
        for k in ("empenhado", "liquidado", "pago", "restos_pagos"):
            a[k] = round(a[k], 2)
        for chave in ("tipos", "funcoes", "ufs"):
            a[chave] = {k: {x: round(y, 2) for x, y in v.items()} for k, v in sorted(a[chave].items(), key=lambda kv: -kv[1]["empenhado"]) if v["empenhado"] or v["pago"]}
        top = sorted(a["autores"].items(), key=lambda kv: -kv[1]["empenhado"])[:AUTORES]
        a["autores"] = {k: {x: round(y, 2) for x, y in v.items()} for k, v in top}
    return out


def coletar_emendas():
    """Emendas parlamentares de todos os anos (arquivo único do Portal da Transparência)."""
    with registrar_coleta("transparencia", "emendas_parlamentares") as (db, n):
        caminho = os.path.join(tempfile.gettempdir(), "emendas_parlamentares.zip")
        with http._cliente.stream("GET", URL, headers=UA, timeout=300, follow_redirects=True) as r:
            r.raise_for_status()
            with open(caminho, "wb") as f:
                for b in r.iter_bytes(1 << 20):
                    f.write(b)
        with zipfile.ZipFile(caminho) as z:
            nome = next(x for x in z.namelist() if x.lower().endswith("emendasparlamentares.csv"))
            bruto = z.read(nome)
        try:
            texto = bruto.decode("utf-8-sig")
        except UnicodeDecodeError:
            texto = bruto.decode("latin-1")
        for ano, d in agregar_emendas(texto).items():
            upsert(db, Registro, {"fonte": "transparencia", "tipo": "emendas_ano", "chave": f"emendas-{ano}"},
                   {"ano": ano, "titulo": f"Emendas parlamentares {ano}", "valor": d["pago"], "dados": {**d, "url": URL}})
            n += 1
    return n.itens
