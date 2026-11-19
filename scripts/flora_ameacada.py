"""Plantas e fungos brasileiros ameaçados de extinção: lista oficial de 2026 do MMA + bioma, estados e nome comum da base de 2020.

Uso:
    python -m scripts.flora_ameacada [pasta_com_os_csv] [saida.json] [--sem-gbif]

Sem pasta, baixa do Portal de Dados Abertos do MMA (https://dados.mma.gov.br/dataset/especies-ameacadas):
  - lista-de-especies-da-flora-ameacadas-portaria1783_2026.csv (flora, Portaria GM/MMA 1.783/2026)
  - lista-de-fungos-ameacados-de-extincao-2026.csv (fungos, 2026)
  - lista-de-especies-ameacas-2020.csv (linhas "Flora": grupo, bioma, estados de ocorrência, ameaças, nome comum)
A categoria de risco vem SEMPRE da lista de 2026. Bioma, estados, ameaças e grupo (angiospermas, gimnospermas, pteridófitas,
briófitas) vêm da base de 2020 e só aparecem quando o nome científico consta nela. Nome comum: base de 2020; quando falta,
GBIF (Catalogue of Life, Lista Vermelha da IUCN e outras), em app/dados/flora_nomes_gbif.json, marcado como "gbif".
A lista oficial não diz quais espécies são árvores: essa informação não está nestes arquivos.
Resultado em app/dados/flora_ameacada.json (lido por GET /ambiente/plantas).
"""
from __future__ import annotations

import csv
import io
import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path

from scripts.fauna_ameacada import BIOMAS, CATEGORIAS, _atributos, _chave, _linhas, _texto, nomes_gbif

BASE = "https://dados.mma.gov.br/dataset/41a79b71-445f-4a6a-8c70-d46af991292a/resource/"
ARQS = {
    "flora": BASE + "4e80c194-8ef8-4ef4-9731-48afb5c1aeef/download/lista-de-especies-da-flora-ameacadas-portaria1783_2026.csv",
    "fungos": BASE + "3d548cbf-1309-4424-80e4-8d4459b167c2/download/lista-de-fungos-ameacados-de-extincao-2026.csv",
    "lista2020": BASE + "1f13b062-f3f6-4198-a4c5-3581548bebec/download/lista-de-especies-ameacas-2020.csv",
}
SAIDA = Path(__file__).resolve().parent.parent / "app" / "dados" / "flora_ameacada.json"
CACHE_NOMES = Path(__file__).resolve().parent.parent / "app" / "dados" / "flora_nomes_gbif.json"
SEM_GRUPO = "Não informado"


def _colunas(linhas: list[list[str]], *nomes: str) -> dict[str, int]:
    """Posição das colunas pelo nome do cabeçalho (sem diferença de maiúsculas); falta uma coluna = erro, nunca lista vazia."""
    cab = {c.strip().lower(): i for i, c in enumerate(linhas[0])}
    faltam = [n for n in nomes if n.lower() not in cab]
    if faltam:
        raise SystemExit(f"coluna(s) não encontrada(s) na lista: {faltam}")
    return {n: cab[n.lower()] for n in nomes}


def _lista_oficial(linhas: list[list[str]], tipo: str) -> list[dict]:
    """Espécies da lista de 2026 (flora ou fungos) com categoria de risco reconhecida."""
    if tipo == "Plantas":
        ix = _colunas(linhas, "Família", "Espécie ou Subespécie/Variedade", "Categoria de Risco")
        fam, nome, cat = ix["Família"], ix["Espécie ou Subespécie/Variedade"], ix["Categoria de Risco"]
    else:
        ix = _colunas(linhas, "Ordem/Família", "Espécie", "Categoria de risco")
        fam, nome, cat = ix["Ordem/Família"], ix["Espécie"], ix["Categoria de risco"]
    out = []
    for r in linhas[1:]:
        if len(r) <= max(fam, nome, cat) or not r[nome].strip():
            continue
        c = r[cat].strip()
        if c not in CATEGORIAS:
            continue
        out.append({"cientifico": r[nome].strip(), "familia": r[fam].strip(), "categoria": c, "tipo": tipo})
    return out


def calcular(flora: str, fungos: str, lista2020: str, gbif: dict[str, str] | None = None) -> dict:
    especies = _lista_oficial(_linhas(flora), "Plantas") + _lista_oficial(_linhas(fungos), "Fungos")
    attr = _atributos(_linhas(lista2020), tipo="Flora")
    itens = []
    com_attr = 0
    for e in especies:
        a = attr.get(_chave(e["cientifico"])) if e["tipo"] == "Plantas" else None
        if a:
            com_attr += 1
        comum = (a or {}).get("comum", "")
        origem = "mma" if comum else ""
        if not comum and gbif and gbif.get(e["cientifico"]):
            comum, origem = gbif[e["cientifico"]], "gbif"
        grupo = (a or {}).get("grupo") or (("Fungos") if e["tipo"] == "Fungos" else SEM_GRUPO)
        itens.append([e["cientifico"], comum, e["tipo"], grupo, e["familia"], e["categoria"],
                      [BIOMAS.index(b) for b in (a or {}).get("biomas", [])], (a or {}).get("estados", []),
                      (a or {}).get("ameacas", [])[:3], 1 if (a or {}).get("exclusiva") else 0, 1 if a else 0, origem])
    por_cat = Counter(i[5] for i in itens)
    por_bioma: dict[str, Counter] = {b: Counter() for b in BIOMAS}
    for i in itens:
        for b in i[6]:
            por_bioma[BIOMAS[b]][i[5]] += 1
    return {
        "fonte": "MMA — Portal de Dados Abertos, Espécies Ameaçadas: flora (Portaria 1.783/2026), fungos (2026) e base de 2020",
        "metodo": "Categoria de risco da lista oficial de 2026 (plantas e fungos). Bioma, estados, ameaças e grupo vêm da base de 2020 do MMA "
                  "e só aparecem quando a espécie consta nela. O nome comum vem da base de 2020 e, quando falta, do GBIF.",
        "gerado_em": date.today().isoformat(),
        "categorias": CATEGORIAS,
        "biomas": BIOMAS,
        "campos": ["nome_cientifico", "nome_comum", "tipo", "grupo", "familia", "categoria", "biomas", "estados", "principais_ameacas",
                   "exclusiva_do_brasil", "tem_dados_2020", "origem_nome_comum"],
        "totais": {"especies": len(itens), "por_categoria": dict(por_cat),
                   "por_tipo": dict(Counter(i[2] for i in itens)),
                   "por_grupo": dict(Counter(i[3] for i in itens).most_common()),
                   "por_familia": dict(Counter(i[4] for i in itens if i[2] == "Plantas").most_common(15)),
                   "com_bioma": sum(1 for i in itens if i[6]), "com_nome_comum": sum(1 for i in itens if i[1]),
                   "nome_comum_gbif": sum(1 for i in itens if i[11] == "gbif"), "com_dados_2020": com_attr,
                   "por_bioma": {b: dict(c) for b, c in por_bioma.items()}},
        "especies": sorted(itens, key=lambda i: (i[2], i[3], i[0])),
    }


def _baixar(url: str) -> str:
    import httpx
    r = httpx.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=120, follow_redirects=True)
    r.raise_for_status()
    return _texto(r.content)


def main(argv: list[str]) -> None:
    sem_gbif = "--sem-gbif" in argv
    argv = [a for a in argv if a != "--sem-gbif"]
    if argv and Path(argv[0]).is_dir():
        pasta = Path(argv[0])
        t = {k: _texto((pasta / f"{k}.csv").read_bytes()) for k in ARQS}
    else:
        t = {k: _baixar(u) for k, u in ARQS.items()}
    base = calcular(t["flora"], t["fungos"], t["lista2020"])
    # o GBIF só entra para plantas e fungos que a base de 2020 não nomeia (o reino muda a busca)
    sem_nome = [e[0] for e in base["especies"] if not e[1]]
    gbif = {}
    if not sem_gbif:
        gbif.update(nomes_gbif([e[0] for e in base["especies"] if not e[1] and e[2] == "Plantas"], CACHE_NOMES, reino="Plantae"))
        gbif.update(nomes_gbif([e[0] for e in base["especies"] if not e[1] and e[2] == "Fungos"],
                               CACHE_NOMES.with_name("fungos_nomes_gbif.json"), reino="Fungi"))
    r = calcular(t["flora"], t["fungos"], t["lista2020"], gbif)
    destino = Path(argv[1]) if len(argv) > 1 else SAIDA
    destino.write_text(json.dumps(r, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tt = r["totais"]
    print(f"{tt['especies']} espécies ({tt['por_tipo']}, {tt['por_categoria']}), {tt['com_dados_2020']} com dados de 2020, "
          f"{len(sem_nome)} sem nome na base de 2020 → {destino}")


if __name__ == "__main__":
    main(sys.argv[1:])
