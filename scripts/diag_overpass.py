"""Diagnóstico do Overpass: quais seletores acham o município de Palmas (TO) e Brasília (DF) e se os espelhos respondem. Saída curta."""
import json
import time

import httpx

UA = {"User-Agent": "BRASIL+ coletor de dados publicos (contato: github.com/felponesx/politica)"}
ESPELHOS = ("https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter", "https://overpass.private.coffee/api/interpreter")
CASOS = {
    "Palmas": ['rel["boundary"="administrative"]["IBGE:GEOCODIGO"="1721000"]', 'rel["boundary"="administrative"]["ref:IBGE"="1721000"]', 'rel["boundary"="administrative"]["name"="Palmas"]["admin_level"="8"]["is_in:state_code"="TO"]',
               'rel["boundary"="administrative"]["name"="Palmas"]["admin_level"="8"]'],
    "Brasilia": ['rel["boundary"="administrative"]["IBGE:GEOCODIGO"="5300108"]', 'rel["boundary"="administrative"]["ref:IBGE"="5300108"]', 'rel["boundary"="administrative"]["name"="Brasília"]'],
}
for nome, seletores in CASOS.items():
    for sel in seletores:
        q = f'[out:json][timeout:60];{sel};out tags;'
        for url in ESPELHOS:
            try:
                r = httpx.post(url, data={"data": q}, headers=UA, timeout=90)
                if r.status_code != 200:
                    print(nome, sel[-45:], url.split("/")[2], r.status_code, flush=True)
                    continue
                el = r.json().get("elements", [])
                print(nome, sel[-60:], url.split("/")[2], len(el), [(e["id"], e["tags"].get("admin_level"), e["tags"].get("name"), e["tags"].get("IBGE:GEOCODIGO")) for e in el[:3]], flush=True)
                break
            except Exception as e:
                print(nome, sel[-45:], url.split("/")[2], "ERRO", type(e).__name__, flush=True)
            time.sleep(3)
        time.sleep(3)
print("fim", flush=True)
