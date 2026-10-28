"""Robô rápido de notícias (.github/workflows/noticias.yml): lê os feeds, sem banco, e grava site/dados/noticias.json.

  python -m scripts.noticias_rapido [site/dados]

O arquivo tem o mesmo formato da resposta de GET /noticias (o site o usa no lugar da cópia completa) e cada matéria
ganha `casos`: os escândalos citados no título ou no resumo (app/escandalos.py). Junta com o que já estava no arquivo
(ou, na primeira vez, com a cópia completa), tira repetidas e matérias com mais de DIAS dias e só reescreve quando algo
mudou, para o robô não gerar commit à toa. Se nenhum feed responder, não grava nada (nunca apaga o que já existe).
"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.collectors.noticias import QUEBRADA, buscar_feeds
from app.escandalos import casos_da_materia

DIAS = 10
TETO = 1200
SHARDS = 128
AVISO = "Títulos e resumos dos feeds públicos de cada veículo; a matéria completa fica no site original."


def _fnv1a(texto: str) -> int:  # a mesma conta de scripts/exportar_snapshot.py (sem importar o banco)
    h = 0x811C9DC5
    for c in texto:
        h = ((h ^ ord(c)) * 0x01000193) & 0xFFFFFFFF
    return h


def ler_anterior(pasta: Path) -> dict:
    """O arquivo deste robô; na primeira vez, a lista de notícias da cópia completa."""
    for arq, chave in ((pasta / "noticias.json", None), (pasta / f"s{_fnv1a('/noticias') % SHARDS}.json", "/noticias")):
        try:
            d = json.loads(arq.read_text(encoding="utf-8"))
            return (d[chave] if chave else d) or {}
        except (OSError, ValueError, KeyError):
            continue
    return {}


def montar(anterior: list[dict], novas: list[dict], agora: datetime, dias: int = DIAS, teto: int = TETO) -> list[dict]:
    """Junta, tira repetidas (pelo link), matérias com letras quebradas e as mais velhas que `dias`; mais novas primeiro."""
    limite = (agora - timedelta(days=dias)).isoformat()
    limite_fake = (agora - timedelta(days=90)).isoformat()  # desmentidos de sites oficiais saem poucas vezes: valem 90 dias
    por_link = {}
    for it in [*anterior, *novas]:  # a versão nova de um link vale mais que a antiga
        if it.get("link") and it.get("titulo"):
            por_link[it["link"]] = it
    itens = [it for it in por_link.values() if not QUEBRADA.search(f"{it['titulo']} {it.get('resumo') or ''}")
             and (it.get("data") or "") >= (limite_fake if it.get("tema") == "fake" else limite)]
    for it in itens:
        it["casos"] = casos_da_materia(it["titulo"], it.get("resumo") or "")
    itens.sort(key=lambda i: i.get("data") or "", reverse=True)
    fake = [i for i in itens if i.get("tema") == "fake"][:300]
    resto = [i for i in itens if i.get("tema") != "fake"][:teto]
    return sorted([*resto, *fake], key=lambda i: i.get("data") or "", reverse=True)


def main(argv):
    pasta = Path(argv[0] if argv else "site/dados")
    agora = datetime.now(timezone.utc)
    novas, avisos = buscar_feeds()
    if not novas:
        sys.exit("Nenhum feed respondeu; o arquivo de notícias não foi alterado. " + "; ".join(avisos[:5]))
    antes = ler_anterior(pasta)
    itens = montar(antes.get("itens") or [], novas, agora)
    veiculos: dict[str, int] = {}
    for it in itens:
        veiculos[it.get("veiculo")] = veiculos.get(it.get("veiculo"), 0) + 1
    saida = {"__completa": True, "total": len(itens), "itens": itens, "veiculos": veiculos, "aviso": AVISO,
             "atualizado_em": antes.get("atualizado_em"), "feeds_sem_resposta": avisos}
    if json.dumps({**saida, "atualizado_em": None}, sort_keys=True) == json.dumps({**antes, "atualizado_em": None}, sort_keys=True):
        print(f"Nada novo ({len(itens)} matérias; {len(avisos)} feeds sem resposta).")
        return
    saida["atualizado_em"] = agora.isoformat(timespec="seconds")
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / "noticias.json").write_text(json.dumps(saida, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    com_caso = sum(1 for i in itens if i["casos"])
    print(f"{len(itens)} matérias ({len(novas)} lidas agora, {com_caso} ligadas a escândalos); {len(avisos)} feeds sem resposta.")


if __name__ == "__main__":
    main(sys.argv[1:])
