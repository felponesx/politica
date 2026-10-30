"""Terceira rodada das fontes novas: CAGED (FTP em latin-1), INPE focos por estado (anual) e TCU contas irregulares (POST/parâmetros). Saída curta."""
import ftplib
import re

import httpx

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36", "Accept": "*/*"}
cli = httpx.Client(timeout=60, follow_redirects=True, headers=UA)
try:
    f = ftplib.FTP(timeout=30, encoding="latin-1")
    f.connect("ftp.mtps.gov.br", 21)
    f.login()
    f.cwd("/pdet/microdados/NOVO CAGED")
    anos = f.nlst()
    print("CAGED anos:", anos[-5:], flush=True)
    f.cwd(anos[-1])
    meses = f.nlst()
    print("  meses:", meses[-4:], flush=True)
    f.cwd(meses[-1])
    for nome in f.nlst()[:8]:
        try:
            print("   ", nome, f.size(nome), flush=True)
        except Exception:
            print("   ", nome, flush=True)
    f.quit()
except Exception as e:
    print("CAGED ERRO", type(e).__name__, str(e)[:150], flush=True)
base = "https://dataserver-coids.inpe.br/queimadas/queimadas/focos/csv/anual/"
for sub in ("EstadosBr_sat_ref/", "Brasil_sat_ref/"):
    r = cli.get(base + sub)
    arq = re.findall(r'href="([^"?/][^"]*)"', r.text)
    print("INPE", sub, r.status_code, len(arq), arq[:3], arq[-3:], flush=True)
    if arq:
        h = cli.get(base + sub + arq[-1], headers={"Range": "bytes=0-600"})
        print("   topo", arq[-1], h.status_code, h.headers.get("content-range"), re.sub(r"\s+", " ", h.text[:400]), flush=True)
u = "https://certidoes.apps.tcu.gov.br/api/publico/responsaveis-contas-irregulares"
for metodo, kw in (("GET", {"params": {"pagina": 0, "tamanho": 2}}), ("POST", {"json": {}}), ("POST", {"json": {"pagina": 0, "tamanho": 2}}), ("OPTIONS", {})):
    try:
        r = cli.request(metodo, u, **kw)
        print("TCU", metodo, kw, r.status_code, r.headers.get("allow"), re.sub(r"\s+", " ", r.text[:260]), flush=True)
    except Exception as e:
        print("TCU", metodo, "ERRO", type(e).__name__, flush=True)
d = cli.get("https://sites.tcu.gov.br/dados-abertos/inidoneos-irregulares/dicionario-dados.html")
t = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", d.text))
for m in re.finditer(r"(?i)(api|endpoint|csv|json|download|irregular)", t):
    pass
print("TCU dicionário trechos:", [t[max(0, m.start() - 60):m.start() + 160] for m in list(re.finditer(r"(?i)contas irregulares", t))[:3]], flush=True)
print("fim", flush=True)
