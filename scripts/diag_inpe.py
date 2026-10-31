"""Diagnóstico do INPE/TerraBrasilis (2ª rodada): descobre os endereços reais lendo o aplicativo de painéis e seus scripts. Saída curta."""
import re
import time

import httpx

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36", "Accept": "*/*"}
cli = httpx.Client(timeout=60, follow_redirects=True, headers=UA)


def get(url, tentativas=3, **kw):
    for i in range(tentativas):
        try:
            r = cli.get(url, **kw)
            print("GET", url[:120], r.status_code, len(r.content), (r.headers.get("content-type") or "")[:30], flush=True)
            if r.status_code < 500:
                return r
        except Exception as e:
            print("GET", url[:120], "ERRO", type(e).__name__, str(e)[:60], flush=True)
        time.sleep(6)
    return None


achados = {}
paginas = ["https://terrabrasilis.dpi.inpe.br/app/dashboard/deforestation/biomes/cerrado/increments", "https://terrabrasilis.dpi.inpe.br/app/map/deforestation"]
for pg in paginas:
    r = get(pg)
    if r is None or r.status_code != 200:
        continue
    js = re.findall(r'(?:src|href)="([^"]+\.js)"', r.text)
    print("  scripts:", len(js), js[6:16], flush=True)
    base = pg.rsplit("/", 1)[0] + "/" if not pg.endswith("/") else pg
    for s in js[:40]:
        if "jquery" in s or "bootstrap" in s or "popper" in s or "lodash" in s or s.startswith("//"):
            continue
        u = s if s.startswith("http") else (("https://terrabrasilis.dpi.inpe.br" + s) if s.startswith("/") else "https://terrabrasilis.dpi.inpe.br/app/" + s.lstrip("./"))
        print("  js:", u[:110], flush=True)
        j = get(u, 1)
        if j is not None and j.status_code == 200:
            for m in re.findall(r"""["'`]((?:https?:)?//?[\w./:{}$-]*(?:terrabrasilis|api/v\d|download|redis|prodes|geoserver)[\w./:?=&%{}$-]*)["'`]""", j.text):
                achados.setdefault(m, pg)
print("ENDEREÇOS ENCONTRADOS NOS SCRIPTS:", flush=True)
for u in sorted(achados)[:80]:
    print("  ", u[:160], flush=True)
# testa os mais promissores
for u in sorted(achados):
    if re.search(r"(download|api/v|redis).*(cerrado|caatinga|atlantica|prodes)|(cerrado|caatinga|atlantica|prodes).*(download|api/v|redis)", u) and u.startswith("http"):
        get(u, 1, headers={"Range": "bytes=0-400"})
print("fim", flush=True)
