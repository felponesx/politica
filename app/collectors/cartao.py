"""Cartão de Pagamento do Governo Federal (cartão corporativo), sem chave de acesso.

Arquivo mensal do Portal da Transparência: https://portaldatransparencia.gov.br/download-de-dados/cpgf/{AAAAMM} (zip com um CSV ';').
Cada linha é uma transação: órgão, portador (CPF mascarado), favorecido, tipo (compra, saque…), data e valor.
Guardamos só somas por mês: total, compras, saques, por órgão superior e os maiores favorecidos com CNPJ.
Nome do portador e CPF não são guardados.
"""
import csv
import io
import re
import time
import zipfile
from datetime import date

from app import http
from app.collectors.base import registrar_coleta
from sqlalchemy import select

from app.models import Registro
from app.utils import sem_acento, upsert

URL = "https://portaldatransparencia.gov.br/download-de-dados/cpgf/{ano}{mes:02d}"
UA = {"User-Agent": "Mozilla/5.0 (BRASIL+ coletor de dados publicos)", "Accept": "*/*"}
FAVORECIDOS = 40


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


def agregar_cartao(texto: str) -> dict:
    """Somas de um mês do CSV do cartão corporativo."""
    leitor = csv.reader(io.StringIO(texto), delimiter=";")
    cab = next(leitor)
    i = {"sup": _col(cab, r"^nome orgao superior"), "fav_doc": _col(cab, r"^cnpj ou cpf favorecido"),
         "fav": _col(cab, r"^nome favorecido"), "tipo": _col(cab, r"^transacao"), "valor": _col(cab, r"^valor transacao")}
    faltam = [k for k, v in i.items() if v is None]
    if faltam:
        raise ValueError(f"Arquivo do cartão corporativo mudou: faltam {faltam} em {cab[:8]}")
    total = saques = 0.0
    n = n_saques = 0
    orgaos, favs = {}, {}
    for l in leitor:
        if len(l) <= max(i.values()):
            continue
        v = _n(l[i["valor"]])
        total += v
        n += 1
        if "saque" in sem_acento(l[i["tipo"]]).lower():
            saques += v
            n_saques += 1
        o = l[i["sup"]] or "Sem órgão superior"
        orgaos[o] = orgaos.get(o, 0.0) + v
        doc = re.sub(r"\D", "", l[i["fav_doc"]])
        if len(doc) == 14:  # só empresas; pessoa física e saque não entram na lista de favorecidos
            f = favs.setdefault(doc, {"cnpj": doc, "nome": l[i["fav"]], "valor": 0.0, "compras": 0})
            f["valor"] += v
            f["compras"] += 1
    maiores = sorted(favs.values(), key=lambda x: -x["valor"])[:FAVORECIDOS]
    return {"total": round(total, 2), "transacoes": n, "saques": round(saques, 2), "saques_n": n_saques,
            "orgaos": {k: round(x, 2) for k, x in sorted(orgaos.items(), key=lambda x: -x[1])},
            "favorecidos": [{**f, "valor": round(f["valor"], 2)} for f in maiores]}


def _baixar(ano: int, mes: int) -> str | None:
    """O Portal bloqueia (405) quem baixa muitos arquivos seguidos: espera e tenta de novo."""
    for espera in (0, 20, 60, 120):
        time.sleep(espera)
        r = http._cliente.get(URL.format(ano=ano, mes=mes), headers=UA, timeout=120, follow_redirects=True)
        if r.status_code in (403, 404):  # mês ainda não publicado
            return None
        if r.status_code == 405:
            continue
        r.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            bruto = z.read(next(x for x in z.namelist() if x.lower().endswith(".csv")))
        try:
            return bruto.decode("utf-8-sig")
        except UnicodeDecodeError:
            return bruto.decode("latin-1")
    raise RuntimeError(f"Portal da Transparência bloqueou o download de {mes:02d}/{ano} (405)")


def coletar_cartao(ano: int):
    """Cartão corporativo do governo federal em todos os meses publicados do ano."""
    ano = int(ano)
    with registrar_coleta("transparencia", "cartao_corporativo", ano=ano) as (db, n):
        for mes in range(1, 13):
            if ano == date.today().year and mes > date.today().month:
                break
            chave = f"cpgf-{ano}{mes:02d}"
            fechado = (ano, mes) < (date.today().year, date.today().month - 1 or 1) and ano < date.today().year
            if fechado and db.scalar(select(Registro.id).where(Registro.fonte == "transparencia", Registro.tipo == "cartao_mes", Registro.chave == chave)):
                continue  # mês antigo já guardado: não baixa de novo
            time.sleep(3)  # um arquivo a cada poucos segundos
            texto = _baixar(ano, mes)
            if texto is None:
                continue
            d = agregar_cartao(texto)
            upsert(db, Registro, {"fonte": "transparencia", "tipo": "cartao_mes", "chave": chave},
                   {"ano": ano, "titulo": f"Cartão corporativo {mes:02d}/{ano}", "valor": d["total"],
                    "dados": {**d, "mes": mes, "url": URL.format(ano=ano, mes=mes)}})
            n += 1
    return n.itens
