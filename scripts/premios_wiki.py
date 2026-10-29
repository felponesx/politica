"""Busca na Wikipédia (pt) a história e uma imagem de cada título de app/dados/premios.json.

    python -m scripts.premios_wiki [site/midia]

Grava o texto (resumo do verbete, com link) em app/dados/premios_wiki.json e baixa as imagens para site/midia/premios/
(até 360 px, WebP). Só guarda o que a Wikipédia devolve; sem verbete, o título aparece só com os dados da lista.
O texto da Wikipédia é CC BY-SA: o site mostra o link do verbete.
"""
import io
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
DADOS = RAIZ / "app" / "dados" / "premios.json"
SAIDA = RAIZ / "app" / "dados" / "premios_wiki.json"
UA = "BRASIL+/1.0 (transparencia; contato: github.com/felponesx/politica)"

MODELOS = {
    "Copa do Mundo masculina": ["Copa do Mundo FIFA de {a}"],
    "Copa do Mundo feminina": ["Copa do Mundo FIFA de Futebol Feminino de {a}"],
    "Copa América": ["Copa América de {a}", "Campeonato Sul-Americano de {a}", "Campeonato Sul-Americano de Futebol de {a}"],
    "Copa das Confederações": ["Copa das Confederações FIFA de {a}"],
    "Jogos Olímpicos": ["Futebol nos Jogos Olímpicos de Verão de {a}", "Basquetebol nos Jogos Olímpicos de Verão de {a}"],
    "Copa do Mundo de Futsal (FIFA)": ["Copa do Mundo de Futsal da FIFA de {a}", "Campeonato Mundial de Futsal de {a}", "Copa do Mundo de Futsal de {a}"],
    "Jogos Olímpicos (quadra)": ["Voleibol nos Jogos Olímpicos de Verão de {a}"],
    "Campeonato Mundial masculino": ["Campeonato Mundial de Voleibol Masculino de {a}", "Campeonato Mundial de Basquetebol de {a}", "Campeonato Mundial de Basquetebol Masculino de {a}"],
    "Jogos Olímpicos (vôlei de praia)": ["Voleibol de praia nos Jogos Olímpicos de Verão de {a}"],
    "Campeonato Mundial feminino": ["Campeonato Mundial de Basquetebol Feminino de {a}", "Campeonato Mundial de Handebol Feminino de {a}"],
    "Valorant Champions": ["Valorant Champions {a}"],
    "Counter-Strike (Majors)": ["ESL One Cologne {a}", "MLG Columbus {a}"],
}
# esportes de pessoas: o verbete é o da pessoa
PESSOAS = {"olimpiadas", "automobilismo", "tenis", "surfe"}


def pessoa(detalhe: str) -> list[str]:
    nome = re.sub(r"\s*\(.*\)", "", detalhe).strip()
    return [n.strip() for n in re.split(r" e ", nome)][:1]


def candidatos(slug, grupo, e):
    if slug in PESSOAS or grupo["nome"].startswith("Jogos Olímpicos (vôlei de praia)") and False:
        return pessoa(e["detalhe"])
    if grupo["nome"] == "Jogos Olímpicos (vôlei de praia)":
        return [m.format(a=e["ano"]) for m in MODELOS[grupo["nome"]]] + pessoa(e["detalhe"])
    ms = MODELOS.get(grupo["nome"], [])
    if slug == "handebol" or (slug == "basquete" and grupo["nome"].startswith("Campeonato")):
        ms = [m for m in ms if ("Handebol" in m) == (slug == "handebol")]
    if slug == "futebol" and grupo["nome"] == "Jogos Olímpicos":
        ms = ms[:1]
    if slug == "basquete" and grupo["nome"] == "Jogos Olímpicos":
        ms = ms[1:]
    return [m.format(a=e["ano"]) for m in ms]


def get(url, tentativas=4):
    for i in range(tentativas):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=30) as r:
                return r.read()
        except Exception as ex:  # 404 = sem verbete; 429 = espera e tenta de novo
            if getattr(ex, "code", 0) == 404:
                return None
            time.sleep(3 * (i + 1))
    return None


def resumo(titulo):
    b = get("https://pt.wikipedia.org/api/rest_v1/page/summary/" + urllib.parse.quote(titulo.replace(" ", "_"), safe=""))
    if not b:
        return None
    d = json.loads(b)
    if d.get("type") == "disambiguation" or not d.get("extract"):
        return None
    txt = d["extract"]
    if len(txt) > 700:
        corte = txt[:700]
        txt = corte[: corte.rfind(". ") + 1] or corte
    return {"titulo": d["title"], "texto": txt, "pagina": d["content_urls"]["desktop"]["page"],
            "imagem": (d.get("originalimage") or d.get("thumbnail") or {}).get("source")}


def baixar(url, dest: Path):
    from PIL import Image
    b = get(url)
    if not b:
        return False
    im = Image.open(io.BytesIO(b)).convert("RGB")
    im.thumbnail((480, 480))
    im.save(dest, "WEBP", quality=78)
    return True


def main(argv):
    midia = Path(argv[0] if argv else RAIZ / "site" / "midia") / "premios"
    midia.mkdir(parents=True, exist_ok=True)
    antes = json.loads(SAIDA.read_text(encoding="utf-8")) if SAIDA.exists() else {}
    novo = {}
    for c in json.loads(DADOS.read_text(encoding="utf-8"))["categorias"]:
        for gi, g in enumerate(c["grupos"]):
            for ei, e in enumerate(g["brasil"]):
                chave = f"{c['slug']}-{gi}-{ei}"
                r = antes.get(chave)
                if not r:
                    for t in candidatos(c["slug"], g, e):
                        r = resumo(t)
                        if r:
                            break
                        time.sleep(.2)
                if not r:
                    continue
                img = midia / f"{chave}.webp"
                if r.get("imagem") and not img.exists():
                    try:
                        baixar(r["imagem"], img)
                    except Exception as ex:
                        print("sem imagem", chave, ex)
                    time.sleep(.5)
                r["arquivo"] = f"premios/{chave}.webp" if img.exists() else None
                novo[chave] = r
                print(chave, "->", r["titulo"], "| img" if r["arquivo"] else "| sem imagem")
    SAIDA.write_text(json.dumps(novo, ensure_ascii=False, indent=1), encoding="utf-8")
    print(len(novo), "títulos com verbete")


if __name__ == "__main__":
    main(sys.argv[1:])
