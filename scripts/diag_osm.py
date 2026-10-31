"""Diagnóstico do OpenStreetMap (o robô alcança o que o ambiente do Claude não alcança): cada espelho do Overpass (código HTTP, corpo do erro, tempo),
o extrato do Brasil da Geofabrik (tamanho, data), o pyosmium/osmium e o limite do município no IBGE. Saída curta."""
import subprocess
import sys
import time

import httpx

UA = {"User-Agent": "BRASIL+ coletor de dados publicos (contato: github.com/felponesx/politica)"}
ESPELHOS = ["https://overpass-api.de/api/interpreter", "https://overpass.private.coffee/api/interpreter", "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
            "https://overpass.kumi.systems/api/interpreter"]
PALMAS = '[out:json][timeout:120];rel["boundary"="administrative"]["IBGE:GEOCODIGO"="1721000"];map_to_area->.a;way(area.a)["highway"];out count;'
MINI = '[out:json][timeout:25];node(-10.2,-48.4,-10.19,-48.39);out count;'


def post(url, q, timeout):
    t = time.time()
    try:
        r = httpx.post(url, data={"data": q}, headers=UA, timeout=timeout)
        corpo = " ".join(r.text.split())[:240]
        print(f"  POST {url.split('/')[2]} HTTP {r.status_code} {len(r.content)}B {time.time() - t:.1f}s :: {corpo}", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"  POST {url.split('/')[2]} ERRO {type(e).__name__} {time.time() - t:.1f}s {str(e)[:100]}", flush=True)


print("== Overpass: status, consulta mínima e Palmas (contagem)")
for u in ESPELHOS:
    try:
        r = httpx.get(u.replace("interpreter", "status"), headers=UA, timeout=30)
        print(f"  GET status {u.split('/')[2]} HTTP {r.status_code} :: {' '.join(r.text.split())[:200]}", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"  GET status {u.split('/')[2]} ERRO {type(e).__name__} {str(e)[:80]}", flush=True)
    post(u, MINI, 60)
    post(u, PALMAS, 200)

print("== Geofabrik")
for u in ["https://download.geofabrik.de/south-america/brazil-latest.osm.pbf", "https://download.geofabrik.de/south-america/brazil-latest.osm.pbf.md5",
          "https://download.geofabrik.de/south-america/brazil-updates/state.txt", "https://download.geofabrik.de/south-america/brazil.poly"]:
    try:
        r = httpx.get(u, headers={**UA, "Range": "bytes=0-199"} if u.endswith("pbf") else UA, timeout=60, follow_redirects=True)
        print(f"  {u.rsplit('/', 1)[-1]} HTTP {r.status_code} total={r.headers.get('content-range') or r.headers.get('content-length')} mod={r.headers.get('last-modified')} :: "
              f"{'' if u.endswith('pbf') else ' '.join(r.text.split())[:160]}", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"  {u} ERRO {type(e).__name__} {str(e)[:80]}", flush=True)

print("== osmium")
r = subprocess.run([sys.executable, "-m", "pip", "install", "-q", "osmium", "shapely"], capture_output=True, text=True)
print("  pip osmium:", r.returncode, (r.stderr or r.stdout)[-200:])
try:
    import osmium
    print("  osmium", osmium.__version__)
except Exception as e:  # noqa: BLE001
    print("  import osmium:", e)

print("== IBGE limite do município (Palmas)")
for u in ["https://servicodados.ibge.gov.br/api/v3/malhas/municipios/1721000?formato=application/vnd.geo%2Bjson&qualidade=intermediaria"]:
    try:
        r = httpx.get(u, headers=UA, timeout=60)
        print(f"  HTTP {r.status_code} {len(r.content)}B {(r.headers.get('content-type') or '')[:40]} :: {r.text[:120]}")
    except Exception as e:  # noqa: BLE001
        print("  ERRO", type(e).__name__, str(e)[:80])
