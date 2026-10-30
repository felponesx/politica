"""Preço dos combustíveis nos postos (ANP, levantamento semanal de preços): média por estado no último mês do arquivo semestral.

Página: https://www.gov.br/anp/pt-br/centrais-de-conteudo/dados-abertos/serie-historica-de-precos-de-combustiveis. Os semestres novos saem em `ca-AAAA-0N.zip` (os antigos, em `.csv`),
com um CSV ';' em que cada linha é o preço coletado num posto: Regiao - Sigla;Estado - Sigla;Municipio;Revenda;CNPJ da Revenda;...;Produto;Data da Coleta (dd/mm/aaaa);Valor de Venda (vírgula);...
O servidor recusa HEAD e clientes sem cara de navegador: GET com User-Agent de navegador."""
import csv
import io
import re
import zipfile

from app import http
from app.collectors.base import registrar_coleta
from app.models import Registro
from app.utils import sem_acento, upsert

PAGINA = "https://www.gov.br/anp/pt-br/centrais-de-conteudo/dados-abertos/serie-historica-de-precos-de-combustiveis"
BASE = "https://www.gov.br/anp/pt-br/centrais-de-conteudo/dados-abertos/arquivos/shpc/dsas/ca/"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36", "Accept": "*/*"}
PRODUTOS = {"GASOLINA": "gasolina", "GASOLINA ADITIVADA": "gasolina_aditivada", "ETANOL": "etanol", "DIESEL": "diesel", "DIESEL S10": "diesel_s10", "GNV": "gnv"}
MINIMO_UF = 27
MINIMO_LINHAS = 20_000


def semestres_do_site(html: str) -> list[str]:
    """Nomes `ca-AAAA-0N.zip` listados na página, do mais novo para o mais antigo."""
    achados = set(re.findall(r"/ca/(ca-\d{4}-0[12]\.zip)", html))
    return sorted(achados, reverse=True)


def agregar(texto: str) -> dict:
    """{"mes": "AAAA-MM", "ufs": {uf: {produto: {"preco": media, "postos": n_de_coletas}}}} só do último mês do arquivo."""
    leitor = csv.reader(io.StringIO(texto), delimiter=";")
    cab = [sem_acento(c).lower().strip().lstrip("﻿") for c in next(leitor)]
    try:
        i = {k: cab.index(k) for k in ("estado - sigla", "produto", "data da coleta", "valor de venda")}
    except ValueError as e:
        raise ValueError(f"ANP: colunas mudaram ({cab[:8]}): {e}") from e
    meses: dict[str, dict] = {}
    for lin in leitor:
        if len(lin) <= max(i.values()):
            continue
        m = re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", lin[i["data da coleta"]].strip())
        prod = PRODUTOS.get(sem_acento(lin[i["produto"]]).strip().upper())
        try:
            v = float(lin[i["valor de venda"]].replace(",", "."))
        except ValueError:
            continue
        uf = lin[i["estado - sigla"]].strip().upper()
        if not m or not prod or len(uf) != 2 or not 0.5 < v < 50:
            continue
        a = meses.setdefault(f"{m.group(3)}-{m.group(2)}", {}).setdefault(uf, {}).setdefault(prod, [0.0, 0])
        a[0] += v
        a[1] += 1
    if not meses:
        raise ValueError("ANP: arquivo sem preços válidos")
    mes = max(meses)
    return {"mes": mes, "ufs": {uf: {p: {"preco": round(s / n, 3), "coletas": n} for p, (s, n) in d.items()} for uf, d in meses[mes].items()}}


def baixar_ultimo() -> tuple[str, str]:
    html = http.get(PAGINA, headers={**UA, "Accept": "text/html"}).text
    nomes = semestres_do_site(html) or ["ca-2026-01.zip"]
    for nome in nomes[:2]:
        r = http._cliente.get(BASE + nome, headers=UA, timeout=300)
        if r.status_code == 200 and r.content[:2] == b"PK":
            z = zipfile.ZipFile(io.BytesIO(r.content))
            csvs = [n for n in z.namelist() if n.lower().endswith(".csv") and "automotivo" in sem_acento(n).lower()] or [n for n in z.namelist() if n.lower().endswith(".csv")]
            if csvs:
                bruto = z.read(csvs[0])
                try:
                    return nome, bruto.decode("utf-8-sig")
                except UnicodeDecodeError:
                    return nome, bruto.decode("latin-1")
    raise RuntimeError("ANP: nenhum zip semestral abriu")


def coletar_anp_combustiveis():
    with registrar_coleta("anp", "combustiveis") as (db, n):
        nome, texto = baixar_ultimo()
        r = agregar(texto)
        if len(r["ufs"]) < MINIMO_UF:
            raise RuntimeError(f"ANP: só {len(r['ufs'])} estados no mês {r['mes']}; nada foi gravado")
        for uf, d in r["ufs"].items():
            upsert(db, Registro, {"fonte": "anp", "tipo": "combustiveis_uf", "chave": uf}, {"uf": uf, "titulo": f"Combustíveis {uf}", "valor": (d.get("gasolina") or {}).get("preco"),
                                                                                         "dados": {"mes": r["mes"], "arquivo": nome, "produtos": d}})
            n += 1
        db.commit()
    return n.itens
