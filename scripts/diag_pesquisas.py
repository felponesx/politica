"""Diagnóstico das fontes de pesquisa que NÃO abriram do ambiente do Claude (FINEP, CNPq, FAPERJ, FAPESP, Transferegov, Portal da Transparência, outras fundações).

Roda no GitHub Actions (.github/workflows/diag-pesquisas.yml). Só mostra status, tamanho e os links de dados que cada página oferece;
nada é gravado. Serve para decidir quais fontes entram na aba Pesquisas (docs/PESQUISAS_FONTES.md).
"""
import re
import time
from html import unescape
from urllib.parse import urljoin

import httpx

cli = httpx.Client(timeout=60, follow_redirects=True, verify=True,
                   headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"})
DADOS = re.compile(r"\.(csv|xlsx?|json|zip|xml)(\?|$|/)|dados.?abertos|download|projetos.?(contratados|contemplados|financiados)|bolsas|auxilio|painel|power.?bi|api", re.I)


def varrer(nome, url, filtro=DADOS, max_links=25):
    t = time.monotonic()
    try:
        r = cli.get(url)
    except Exception as e:  # noqa: BLE001
        print(f"\n=== {nome}: ERRO {type(e).__name__}: {str(e)[:120]} ({time.monotonic() - t:.1f}s) | {url}", flush=True)
        return None
    print(f"\n=== {nome}: HTTP {r.status_code} | {r.headers.get('content-type', '')[:40]} | {len(r.content)} bytes | {time.monotonic() - t:.1f}s | {r.url}", flush=True)
    if "html" in r.headers.get("content-type", "") and r.status_code == 200:
        vistos = set()
        for m in re.finditer(r'<a [^>]*href="([^"#]+)"[^>]*>(.*?)</a>', r.text, re.S | re.I):
            h, txt = urljoin(str(r.url), unescape(m.group(1))), re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", unescape(m.group(2)))).strip()
            if filtro.search(h + " " + txt) and h not in vistos and len(vistos) < max_links:
                vistos.add(h)
                print(f"   {txt[:70]!r} -> {h[:140]}", flush=True)
    return r


def cabecalho(nome, url):
    try:
        r = cli.head(url)
        print(f"\n=== HEAD {nome}: HTTP {r.status_code} | {r.headers.get('content-type')} | {r.headers.get('content-length')} bytes | {r.headers.get('last-modified')} | {r.url}", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"\n=== HEAD {nome}: ERRO {type(e).__name__}: {str(e)[:120]}", flush=True)


print("##### FINEP", flush=True)
for u in ("https://www.finep.gov.br/transparencia/projetos-contratados", "https://www.finep.gov.br/transparencia", "https://legacy.finep.gov.br/transparencia-finep/paineis-e-downloads/central-de-downloads",
          "https://www.finep.gov.br/transparencia/paineis-e-downloads/central-de-downloads", "https://www.finep.gov.br/images/a-finep/Transparencia/Projetos_Contratados.xlsx"):
    varrer("FINEP " + u[-50:], u)

print("\n##### CNPq", flush=True)
for u in ("http://dadosabertos.cnpq.br/pt_BR/", "http://dadosabertos.cnpq.br/pt_BR/dataset", "https://dadosabertos.cnpq.br/pt_BR/dataset", "https://www.gov.br/cnpq/pt-br/acesso-a-informacao/dados-abertos/consulta-de-dados-1",
          "https://www.gov.br/cnpq/pt-br/acesso-a-informacao/dados-abertos/consulta-de-dados", "http://bi.cnpq.br/painel/fomento-cti/"):
    varrer("CNPq " + u[-50:], u)

print("\n##### FAPERJ", flush=True)
r = varrer("FAPERJ busca", "https://siteantigo.faperj.br/servicos/buscaprojetosinfaperj/busca_projeto.phtml", re.compile(r"projeto|busca|resumo|csv|xls", re.I))
if r is not None and r.status_code == 200:
    for f in re.findall(r"<form[^>]*>", r.text, re.I)[:3]:
        print("   form:", f[:200], flush=True)
    for i in re.findall(r"<(?:input|select|textarea)[^>]*name=\"([^\"]+)\"", r.text, re.I)[:20]:
        print("   campo:", i, flush=True)
varrer("FAPERJ resumo de projetos", "https://www.faperj.br/?id=47.4.0", re.compile(r"projeto|contemplad|csv|xls|pdf", re.I))

print("\n##### FAPESP", flush=True)
for u in ("https://bv.fapesp.br/pt/dados-abertos/", "https://bv.fapesp.br/pt/pesquisador/", "https://bv.fapesp.br/", "https://fapesp.br/dadosabertos", "https://dadosabertos.fapesp.br/",
          "https://fapesp.br/transparencia"):
    varrer("FAPESP " + u[-45:], u, re.compile(r"\.(csv|xlsx?|json|zip)|dados.?abertos|download|exporta|api", re.I))

print("\n##### Transferegov / dados.gov.br / Portal da Transparência", flush=True)
for u in ("https://dadosabertos.transferegov.sistema.gov.br/", "https://api.transferegov.gestao.gov.br/", "https://www.transferegov.sistema.gov.br/portal/",
          "https://portaldatransparencia.gov.br/download-de-dados", "https://dados.gov.br/dados/conjuntos-dados?termo=pesquisa%20cient%C3%ADfica"):
    varrer("GOV " + u[-55:], u)
for ano_mes in ("202509",):
    cabecalho("Transparência despesas " + ano_mes, f"https://portaldatransparencia.gov.br/download-de-dados/despesas/{ano_mes}")
    cabecalho("Transparência convênios", "https://portaldatransparencia.gov.br/download-de-dados/convenios")

print("\n##### Outras fundações estaduais (página inicial: o que oferecem de dados abertos)", flush=True)
FAPS = {"FAPERGS": "https://fapergs.rs.gov.br/", "FACEPE": "https://www.facepe.br/", "FUNCAP": "https://www.funcap.ce.gov.br/", "FAPESB": "https://www.fapesb.ba.gov.br/",
        "FAPES": "https://fapes.es.gov.br/", "FAPESC": "https://www.fapesc.sc.gov.br/", "Fundação Araucária": "https://www.fappr.pr.gov.br/",
        "FAPEG": "https://goias.gov.br/fapeg/", "FAPDF": "https://www.fap.df.gov.br/", "FAPEAM": "https://www.fapeam.am.gov.br/", "FAPEMA": "https://www.fapema.br/",
        "FAPEAL": "https://fapeal.al.gov.br/", "FAPESQ": "https://fapesq.rpp.br/", "FAPERN": "https://www.fapern.rn.gov.br/", "FAPITEC": "https://fapitec.se.gov.br/",
        "FAPESPA": "https://www.fapespa.pa.gov.br/", "FAPEMAT": "https://www.fapemat.mt.gov.br/", "FUNDECT": "https://www.fundect.ms.gov.br/"}
filtro = re.compile(r"dados.?abertos|projetos.?(contratados|contemplados|financiados|aprovados)|resultado|transpar", re.I)
for nome, u in FAPS.items():
    varrer(nome, u, filtro, max_links=8)

print("\n##### Butantan / Fiocruz / Embrapa / EMBRAPII", flush=True)
for nome, u in {"Butantan": "https://butantan.gov.br/acesso-a-informacao", "Fiocruz dados": "https://dadosdepesquisa.fiocruz.br/", "Embrapa": "https://www.embrapa.br/acesso-a-informacao/dados-abertos",
                "EMBRAPII": "https://embrapii.org.br/", "OpenAlex Butantan": "https://api.openalex.org/institutions?search=butantan&per-page=2&select=id,display_name,works_count,ror"}.items():
    varrer(nome, u, re.compile(r"\.(csv|xlsx?|json)|dados.?abertos|projetos|transpar", re.I), max_links=10)
print("\nfim", flush=True)
