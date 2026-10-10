"""Orçamento da União por órgão, sem chave de acesso.

Arquivo anual do Portal da Transparência (downloads de dados abertos, não precisa da chave da API):
https://portaldatransparencia.gov.br/download-de-dados/orcamento-despesa/{ano} — zip com um CSV (';') com o orçamento
inicial, atualizado, empenhado e realizado por órgão superior, órgão subordinado, função e ação.
Somamos por órgão subordinado (com a quebra por função) e gravamos como `gasto_orgao`, o mesmo tipo que a rota
/orgaos já lê.
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

URL = "https://portaldatransparencia.gov.br/download-de-dados/orcamento-despesa/{ano}"
UA = {"User-Agent": "Mozilla/5.0 (BRASIL+ coletor de dados publicos)", "Accept": "*/*"}


def _n(v) -> float:
    try:
        return float(str(v).replace(".", "").replace(",", ".")) if str(v).strip() else 0.0
    except ValueError:
        return 0.0


def _col(cab: list[str], *expr: str) -> int | None:
    norm = [re.sub(r"\s+", " ", sem_acento(c).lower()).strip() for c in cab]
    for e in expr:
        for i, h in enumerate(norm):
            if re.search(e, h):
                return i
    return None


def agregar_orcamento(texto: str) -> dict:
    """{codigo_orgao: {...}} somando as linhas do CSV do orçamento."""
    leitor = csv.reader(io.StringIO(texto), delimiter=";")
    cab = next(leitor)
    i = {"cod_sup": _col(cab, r"^codigo orgao superior"), "nome_sup": _col(cab, r"^nome orgao superior"),
         "cod": _col(cab, r"^codigo orgao subordinado"), "nome": _col(cab, r"^nome orgao subordinado"),
         "funcao": _col(cab, r"^nome funcao"), "inicial": _col(cab, r"orcamento inicial"),
         "atualizado": _col(cab, r"orcamento atualizado"), "empenhado": _col(cab, r"orcamento empenhado"),
         "realizado": _col(cab, r"orcamento realizado")}
    faltam = [k for k, v in i.items() if v is None]
    if faltam:
        raise ValueError(f"Arquivo do orçamento mudou: faltam {faltam} em {cab[:8]}")
    out = {}
    for l in leitor:
        if len(l) <= max(i.values()):
            continue
        o = out.setdefault(l[i["cod"]], {"codigoOrgaoSuperior": l[i["cod_sup"]], "orgaoSuperior": l[i["nome_sup"]],
                                         "codigoOrgao": l[i["cod"]], "orgao": l[i["nome"]], "orcamento_inicial": 0.0,
                                         "orcamento_atualizado": 0.0, "empenhado": 0.0, "pago": 0.0, "funcoes": {}})
        o["orcamento_inicial"] += _n(l[i["inicial"]])
        o["orcamento_atualizado"] += _n(l[i["atualizado"]])
        o["empenhado"] += _n(l[i["empenhado"]])
        real = _n(l[i["realizado"]])
        o["pago"] += real
        f = l[i["funcao"]] or "Sem função"
        o["funcoes"][f] = o["funcoes"].get(f, 0.0) + real
    for o in out.values():
        for k in ("orcamento_inicial", "orcamento_atualizado", "empenhado", "pago"):
            o[k] = round(o[k], 2)
        o["funcoes"] = {k: round(v, 2) for k, v in sorted(o["funcoes"].items(), key=lambda x: -x[1]) if v}
    return out


def coletar_orcamento_orgaos(ano: int):
    """Orçamento e execução de todos os órgãos federais no ano (arquivo do Portal da Transparência)."""
    ano = int(ano)
    with registrar_coleta("transparencia", "orcamento_orgaos", ano=ano) as (db, n):
        caminho = os.path.join(tempfile.gettempdir(), f"orcamento_{ano}.zip")
        with http._cliente.stream("GET", URL.format(ano=ano), headers=UA, timeout=300, follow_redirects=True) as r:
            r.raise_for_status()
            with open(caminho, "wb") as f:
                for b in r.iter_bytes(1 << 20):
                    f.write(b)
        with zipfile.ZipFile(caminho) as z:
            nome = next(x for x in z.namelist() if x.lower().endswith(".csv"))
            bruto = z.read(nome)
        try:
            texto = bruto.decode("utf-8-sig")
        except UnicodeDecodeError:
            texto = bruto.decode("latin-1")
        orgaos = agregar_orcamento(texto)
        superiores = {}
        for cod, d in orgaos.items():
            upsert(db, Registro, {"fonte": "transparencia", "tipo": "gasto_orgao", "chave": f"orc-{ano}-{cod}"},
                   {"ano": ano, "titulo": d["orgao"], "valor": d["pago"],
                    "dados": {**d, "fonte": "orcamento-despesa", "url": URL.format(ano=ano)}})
            superiores[d["codigoOrgaoSuperior"]] = d["orgaoSuperior"]
            n += 1
        for cod, nome in superiores.items():  # nomes dos órgãos superiores, para a lista e a busca
            upsert(db, Registro, {"fonte": "transparencia", "tipo": "orgao", "chave": cod},
                   {"titulo": nome, "dados": {"codigo": cod, "descricao": nome}})
    return n.itens
