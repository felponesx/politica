"""Diagnóstico da segunda etapa: PDET/CAGED (páginas, FTP, Acesso Online), Querido Diário (TLS, HTTP/1.1, hosts), Overpass e TomTom. Saída curta."""
import ftplib
import re
import socket
import ssl

import httpx

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36", "Accept": "*/*"}
cli = httpx.Client(timeout=40, follow_redirects=True, headers=UA)


def tenta(rotulo, url, **kw):
    try:
        r = cli.get(url, **kw)
        print(rotulo, r.status_code, len(r.content), r.headers.get("content-type"), re.sub(r"\s+", " ", r.text[:160]), flush=True)
        return r
    except Exception as e:
        print(rotulo, "ERRO", type(e).__name__, str(e)[:150], flush=True)


for u in ("https://acesso.trabalho.gov.br/portal-pdet/o-pdet/portifolio-de-produtos/bases-de-dados.htm",
          "https://www.gov.br/trabalho-e-emprego/pt-br/acesso-a-informacao/acoes-e-programas/programas-projetos-acoes-obras-e-atividades/estatisticas-trabalho/novo-caged"):
    r = tenta("PDET", u)
    if r is not None and r.status_code == 200:
        links = sorted(set(re.findall(r'href="([^"]+)"', r.text)))
        print("  links úteis:", [l for l in links if re.search(r"caged|pdet|ftp|\.xls|\.zip|\.csv|tabela|acesso", l, re.I)][:40], flush=True)
try:
    f = ftplib.FTP(timeout=30, encoding="latin-1")
    f.connect("ftp.mtps.gov.br", 21)
    f.login()
    f.cwd("/pdet/microdados/NOVO CAGED")
    anos = f.nlst()
    print("CAGED FTP anos:", anos[-4:], flush=True)
    f.cwd(anos[-1])
    meses = f.nlst()
    print("  meses:", meses[-3:], flush=True)
    f.cwd(meses[-1])
    for nome in f.nlst()[:6]:
        try:
            print("   ", nome, f.size(nome), flush=True)
        except Exception:
            print("   ", nome, flush=True)
    f.quit()
except Exception as e:
    print("CAGED FTP ERRO", type(e).__name__, str(e)[:150], flush=True)
for u in ("http://pdet.mte.gov.br/", "http://pdet.mte.gov.br/novo-caged", "http://bi.mte.gov.br/bgcaged/", "http://pdet.mte.gov.br/images/Novo_CAGED/2026/202608/3-Tabelas.xlsx",
          "https://pdet.mte.gov.br/images/Novo_CAGED/2026/202608/3-Tabelas.xlsx"):
    tenta("PDET-alt", u)

# Querido Diário: TLS e DNS
for host in ("api.queridodiario.ok.org.br", "queridodiario.ok.org.br"):
    try:
        print("DNS", host, sorted({a[4][0] for a in socket.getaddrinfo(host, 443)})[:4], flush=True)
    except Exception as e:
        print("DNS", host, "ERRO", e, flush=True)
    for versao in (ssl.TLSVersion.TLSv1_2, ssl.TLSVersion.TLSv1_3):
        try:
            ctx = ssl.create_default_context()
            ctx.minimum_version = ctx.maximum_version = versao
            with socket.create_connection((host, 443), timeout=20) as s, ctx.wrap_socket(s, server_hostname=host) as t:
                print("TLS", host, versao.name, "ok", t.version(), t.cipher()[0], flush=True)
        except Exception as e:
            print("TLS", host, versao.name, "ERRO", type(e).__name__, str(e)[:100], flush=True)
for u in ("https://api.queridodiario.ok.org.br/cities?city_name=campinas", "https://api.queridodiario.ok.org.br/gazettes?querystring=licitacao&size=1",
          "https://queridodiario.ok.org.br/api/docs", "https://queridodiario.ok.org.br/api/gazettes?querystring=licitacao&size=1",
          "https://data.queridodiario.ok.org.br/"):
    tenta("QD", u)
# Overpass
for u in ("https://overpass-api.de/api/status", "https://overpass.kumi.systems/api/status", "https://overpass.private.coffee/api/status"):
    tenta("OVERPASS", u)
q = '[out:json][timeout:60];area["name"="Palmas"]["admin_level"="8"]->.a;way(area.a)["highway"~"^(primary|secondary|tertiary|residential)$"];out count;'
tenta("OVERPASS-consulta", "https://overpass-api.de/api/interpreter", params={"data": q})
# TomTom (sem chave): só confere o endereço
tenta("TOMTOM", "https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/10/json?point=-23.55,-46.63&key=")
print("fim", flush=True)
