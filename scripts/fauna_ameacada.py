"""Fauna brasileira ameaçada de extinção: lista oficial de 2026 + bioma, nome comum e estados da base de 2020 do MMA.

Uso:
    python -m scripts.fauna_ameacada [pasta_com_os_csv] [saida.json]

Sem pasta, baixa os três arquivos do Portal de Dados Abertos do MMA (https://dados.mma.gov.br/dataset/especies-ameacadas):
  - lista de espécies da fauna ameaçadas, NÃO peixes, 2026 (Portaria GM/MMA 1.667/2026 e atualizações)
  - lista de espécies aquáticas (peixes e invertebrados) ameaçadas, 2026
  - lista de espécies ameaçadas 2020 (traz nome comum, bioma, principais ameaças, estados de ocorrência)
A categoria de risco vem SEMPRE da lista de 2026. Quando a base de 2020 não tem o nome comum, ele é completado pelo GBIF (nomes em
português, entre eles os do Catálogo Taxonômico da Fauna do Brasil), guardado em app/dados/fauna_nomes_gbif.json e marcado como
"gbif" para a tela poder dizer de onde veio. Bioma, nome comum, estados e ameaças vêm da base de 2020 e só aparecem
quando o nome científico da espécie existe nela; as espécies que entraram na lista depois (marcadas com "novo") podem não ter
esses campos. O resultado fica em app/dados/fauna_ameacada.json (lido por GET /ambiente/animais).
"""
from __future__ import annotations

import csv
import io
import json
import re
import sys
import unicodedata
from collections import Counter
from datetime import date
from pathlib import Path

BASE = "https://dados.mma.gov.br/dataset/41a79b71-445f-4a6a-8c70-d46af991292a/resource/"
ARQS = {
    "nao_peixes": BASE + "f83bd2d4-fcb0-4804-ab8c-3697e7594fb3/download/lista-de-especies-da-fauna-ameacadas_nao-peixes-2026.csv",
    "aquaticas": BASE + "29975acc-a4f3-47d8-86c2-281b37aca5ab/download/lista-de-especies-aquaticas-peixes-e-invertebrados-ameacadas-2026.csv",
    "lista2020": BASE + "1f13b062-f3f6-4198-a4c5-3581548bebec/download/lista-de-especies-ameacas-2020.csv",
}
SAIDA = Path(__file__).resolve().parent.parent / "app" / "dados" / "fauna_ameacada.json"
CACHE_NOMES = Path(__file__).resolve().parent.parent / "app" / "dados" / "fauna_nomes_gbif.json"
CATEGORIAS = {"CR": "Criticamente em perigo", "EN": "Em perigo", "VU": "Vulnerável", "CR (PE)": "Criticamente em perigo (possivelmente extinta)",
              "EW": "Extinta na natureza"}
BIOMAS = ["Amazônia", "Caatinga", "Cerrado", "Mata Atlântica", "Pampa", "Pantanal"]


def _texto(raw: bytes) -> str:
    for enc in ("utf-8-sig", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def _linhas(texto: str):
    return list(csv.reader(io.StringIO(texto), delimiter=";"))


def _chave(nome: str) -> str:
    """Nome científico em minúsculas e sem acento, duas primeiras palavras (gênero + espécie)."""
    s = unicodedata.normalize("NFKD", nome or "").encode("ascii", "ignore").decode().lower()
    return " ".join(re.sub(r"[^a-z ]", " ", s).split()[:2])


def _lista(txt: str) -> list[str]:
    return [x.strip() for x in re.split(r"[;,]", txt or "") if x.strip() and x.strip() != "-"]


def _novas(linhas: list[list[str]], aquatica: bool) -> list[dict]:
    """Linhas da lista de 2026: nº, marca de novo (*), grupo, classe, ordem, família, espécie, categoria."""
    out = []
    for r in linhas[1:]:
        if len(r) < 8 or not r[6].strip():
            continue
        cat = r[7].strip()
        if cat not in CATEGORIAS:
            continue
        out.append({"cientifico": r[6].strip(), "grupo": r[2].strip(), "classe": r[3].strip(), "ordem": r[4].strip(), "familia": r[5].strip(),
                    "categoria": cat, "novo": r[1].strip() == "*", "aquatica": aquatica})
    return out


def _atributos(linhas: list[list[str]]) -> dict[str, dict]:
    """Base de 2020 (só fauna): nome comum, biomas, estados e principais ameaças por nome científico."""
    cab = [c.strip() for c in linhas[0]]
    ix = {c: i for i, c in enumerate(cab)}
    pegar = lambda r, c: r[ix[c]].strip() if c in ix and ix[c] < len(r) else ""
    out = {}
    for r in linhas[1:]:
        if pegar(r, "Fauna/Flora") != "Fauna":
            continue
        nome = pegar(r, "Espécie (Simplificado)")
        if not nome:
            continue
        comum = pegar(r, "Nome Comum")
        out[_chave(nome)] = {"comum": "" if comum == "-" else comum,
                             "biomas": [b for b in _lista(pegar(r, "Bioma")) if b in BIOMAS],
                             "estados": _lista(pegar(r, "Estados de Ocorrência")),
                             "ameacas": _lista(pegar(r, "Principais Ameaças")),
                             "exclusiva": pegar(r, "Espécie exclusiva do Brasil") == "Sim"}
    return out


def _nome_gbif(cli, cientifico: str) -> str:
    """Nome comum em português de uma espécie no GBIF (só quando o nome científico bate exato). Prefere os do Catálogo Taxonômico da Fauna do Brasil."""
    m = cli.get("https://api.gbif.org/v1/species/match", params={"name": cientifico, "kingdom": "Animalia"}).json()
    if m.get("matchType") != "EXACT" or not m.get("usageKey"):
        return ""
    res = cli.get(f"https://api.gbif.org/v1/species/{m['usageKey']}/vernacularNames", params={"limit": 200}).json().get("results", [])
    pt = [(x.get("vernacularName", "").strip(), x.get("source", "")) for x in res if x.get("language") in ("por", "pt") and x.get("vernacularName")]
    oficiais = [n for n, f in pt if "Fauna do Brasil" in f]
    escolha = oficiais or [n for n, _ in pt]
    if not escolha:
        return ""
    mais = Counter(n.lower() for n in escolha).most_common(1)[0][0]
    return mais[:1].upper() + mais[1:]


def nomes_gbif(cientificos: list[str], cache: Path = CACHE_NOMES) -> dict[str, str]:
    """Nomes comuns do GBIF, com cache em arquivo (só consulta o que ainda não foi consultado)."""
    import httpx
    from concurrent.futures import ThreadPoolExecutor
    dados = json.loads(cache.read_text(encoding="utf-8")) if cache.exists() else {}
    falta = [c for c in cientificos if c not in dados]
    if falta:
        def um(c):
            try:
                return c, _nome_gbif(cli, c)
            except Exception:
                return c, None                      # falha de rede: tenta de novo na próxima rodada
        with httpx.Client(timeout=30, headers={"User-Agent": "Mozilla/5.0"}) as cli, ThreadPoolExecutor(8) as ex:
            for c, n in ex.map(um, falta):
                if n is not None:
                    dados[c] = n
        cache.write_text(json.dumps(dados, ensure_ascii=False, indent=0, sort_keys=True), encoding="utf-8")
    return dados


def calcular(nao_peixes: str, aquaticas: str, lista2020: str, gbif: dict[str, str] | None = None) -> dict:
    especies = _novas(_linhas(nao_peixes), False) + _novas(_linhas(aquaticas), True)
    attr = _atributos(_linhas(lista2020))
    itens = []
    com_attr = 0
    for e in especies:
        a = attr.get(_chave(e["cientifico"]))
        if a:
            com_attr += 1
        comum = (a or {}).get("comum", "")
        origem = "mma" if comum else ""
        if not comum and gbif and gbif.get(e["cientifico"]):
            comum, origem = gbif[e["cientifico"]], "gbif"
        itens.append([e["cientifico"], comum, e["grupo"], e["familia"], e["categoria"], 1 if e["novo"] else 0,
                      [BIOMAS.index(b) for b in (a or {}).get("biomas", [])], (a or {}).get("estados", []), (a or {}).get("ameacas", [])[:3],
                      1 if (a or {}).get("exclusiva") else 0, 1 if a else 0, origem])
    por_cat = Counter(i[4] for i in itens)
    por_grupo = Counter(i[2] for i in itens)
    por_bioma: dict[str, Counter] = {b: Counter() for b in BIOMAS}
    for i in itens:
        for b in i[6]:
            por_bioma[BIOMAS[b]][i[4]] += 1
    return {
        "fonte": "MMA — Portal de Dados Abertos, Espécies Ameaçadas (listas de 2026 e base de 2020)",
        "metodo": "Categoria de risco da lista oficial de 2026. Bioma, estados e ameaças vêm da base de 2020 do MMA e só aparecem quando a espécie consta nela. O nome comum vem da base de 2020 e, quando falta, do GBIF (Catálogo Taxonômico da Fauna do Brasil e outras fontes).",
        "gerado_em": date.today().isoformat(),
        "categorias": CATEGORIAS,
        "biomas": BIOMAS,
        "campos": ["nome_cientifico", "nome_comum", "grupo", "familia", "categoria", "novo_na_lista_2026", "biomas", "estados", "principais_ameacas",
                   "exclusiva_do_brasil", "tem_dados_2020", "origem_nome_comum"],
        "totais": {"especies": len(itens), "por_categoria": dict(por_cat), "por_grupo": dict(por_grupo.most_common()),
                   "novas_2026": sum(i[5] for i in itens), "com_bioma": sum(1 for i in itens if i[6]), "com_nome_comum": sum(1 for i in itens if i[1]),
                   "nome_comum_gbif": sum(1 for i in itens if i[11] == "gbif"),
                   "por_bioma": {b: dict(c) for b, c in por_bioma.items()}, "com_dados_2020": com_attr},
        "especies": sorted(itens, key=lambda i: (i[2], i[0])),
    }


def _baixar(url: str) -> str:
    import httpx
    r = httpx.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=120, follow_redirects=True)
    r.raise_for_status()
    return _texto(r.content)


def main(argv: list[str]) -> None:
    if argv and Path(argv[0]).is_dir():
        pasta = Path(argv[0])
        t = {k: _texto((pasta / f"{k}.csv").read_bytes()) for k in ARQS}
    else:
        t = {k: _baixar(u) for k, u in ARQS.items()}
    sem_gbif = "--sem-gbif" in argv
    argv = [a for a in argv if a != "--sem-gbif"]
    base = calcular(t["nao_peixes"], t["aquaticas"], t["lista2020"])
    gbif = {} if sem_gbif else nomes_gbif([e[0] for e in base["especies"] if not e[1]])
    r = calcular(t["nao_peixes"], t["aquaticas"], t["lista2020"], gbif)
    destino = Path(argv[1]) if len(argv) > 1 else SAIDA
    destino.write_text(json.dumps(r, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tt = r["totais"]
    print(f"{tt['especies']} espécies ({tt['por_categoria']}), {tt['com_dados_2020']} com dados de 2020 → {destino}")


if __name__ == "__main__":
    main(sys.argv[1:])
