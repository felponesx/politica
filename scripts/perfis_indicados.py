"""Perfis dos indicados (ministros de Estado, STF, STJ, TSE, TCU, STM e Banco Central) para o site sem servidor.

Para cada nome de `app/dados/indicados_nomes.json`: resumo do verbete da Wikipédia (2 primeiras frases) e data de nascimento do
Wikidata (usada para calcular quando os ministros do STF completam 75 anos, a aposentadoria compulsória). Só entra o verbete
cujo resumo cita um cargo público (evita homônimos). Grava `site/midia/perfis.json`: {nome: {resumo, pagina, nascimento}}.
Uso: python -m scripts.perfis_indicados [site/midia]
"""
import json
import logging
import os
import re
import sys
from urllib.parse import quote

log = logging.getLogger("brasilplus.perfis")
NOMES = os.path.join(os.path.dirname(__file__), "..", "app", "dados", "indicados_nomes.json")
CARGO = re.compile(r"minist|magistrad|jurista|advogad|pol[ií]tic|economist|diplomata|procurador|deputad|senador|governador|"
                   r"desembargador|ju[ií]z|general|almirante|brigadeiro|engenheir|professor|servidor|auditor|banqueiro|"
                   r"sindicalista|cientista|militar|presidente", re.I)


def _json(url: str):
    from scripts.fotos_escandalos import _get
    cod, corpo = _get(url)
    return json.loads(corpo) if cod == 200 and corpo else None


def _frases(txt: str, n: int = 2) -> str:
    txt = re.sub(r"\s+", " ", re.sub(r"\([^()]*\)", "", txt or "")).strip()
    partes = re.split(r"(?<=[.!?])\s+(?=[A-ZÁÉÍÓÚÂÊÔÃÕÇ])", txt)
    return " ".join(partes[:n])[:520]


def perfil(nome: str) -> dict | None:
    d = _json("https://pt.wikipedia.org/api/rest_v1/page/summary/" + quote(nome.replace(" ", "_"), safe=""))
    if not d or d.get("type") != "standard":
        return None
    extrato = d.get("extract") or ""
    if not CARGO.search(extrato + " " + (d.get("description") or "")):
        return None
    out = {"resumo": _frases(extrato), "pagina": ((d.get("content_urls") or {}).get("desktop") or {}).get("page")}
    q = d.get("wikibase_item")
    if q:
        e = _json(f"https://www.wikidata.org/wiki/Special:EntityData/{q}.json")
        try:
            t = e["entities"][q]["claims"]["P569"][0]["mainsnak"]["datavalue"]["value"]["time"]
            out["nascimento"] = t.lstrip("+")[:10]
        except Exception:
            pass
    return out


def main(pasta: str = "site/midia"):
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    arq = os.path.join(pasta, "perfis.json")
    try:
        with open(arq, encoding="utf-8") as f:
            antes = json.load(f)
    except (OSError, ValueError):
        antes = {}
    out = dict(antes)
    for n in json.load(open(NOMES, encoding="utf-8")):
        try:
            p = perfil(n)
        except Exception as e:  # noqa: BLE001 - limite da Wikimedia etc.: fica o que já havia
            log.warning("%s: %s", n, e)
            continue
        if p:
            out[n] = p
    with open(arq, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    log.info("perfis de indicados: %d de %d", len(out), len(json.load(open(NOMES, encoding="utf-8"))))


if __name__ == "__main__":
    main(*sys.argv[1:])
