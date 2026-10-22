"""Acrescenta fotos que faltam em site/midia, sem refazer tudo (o passo "Fotos e logos" do robô leva horas):

  python -m scripts.fotos_extra [site/midia] [site/dados]

- prefeitos eleitos de 2024: a lista vem da cópia dos dados (`/candidatos?cargo=PREFEITO&eleitos=true`) e cada foto, do zip do TSE
  do estado por pedido Range (`fotos_prefeitos_de`); só as que ainda não estão nos blocos;
- pessoas dos escândalos que foram deputados federais: retrato oficial da Câmara (`foto_camara`), só para quem ainda não tem foto.
Só acrescenta: nunca apaga nem troca uma foto que já existe. O próximo `midia_site` completo gera as mesmas fotos pelo banco.
"""
import json
import logging
import os
import sys
from pathlib import Path

from scripts.fotos_escandalos import foto_camara
from scripts.logos_arquivo import webp
from scripts.midia_site import fnv1a, fotos_prefeitos_de
from scripts.revisar_dados import Copia

log = logging.getLogger("brasilplus.midia")


def _blocos(pasta: str) -> tuple[int, dict]:
    n = json.load(open(os.path.join(pasta, "indice.json"), encoding="utf-8"))["blocos"]
    return n, {i: json.load(open(os.path.join(pasta, f"fotos_{i}.json"), encoding="utf-8")) for i in range(n)}


def _gravar(pasta: str, n: int, blocos: dict, novas: dict) -> int:
    """Acrescenta as fotos novas nos blocos (nunca troca uma que já existe); devolve quantos blocos mudaram."""
    mudou = set()
    for k, v in novas.items():
        i = fnv1a(k) % n
        if k not in blocos[i]:
            blocos[i][k] = webp(v, 80)
            mudou.add(i)
    for i in mudou:
        with open(os.path.join(pasta, f"fotos_{i}.json"), "w", encoding="utf-8") as f:
            json.dump(blocos[i], f, separators=(",", ":"))
    idx_arq = os.path.join(pasta, "indice.json")
    idx = json.load(open(idx_arq, encoding="utf-8"))
    idx["fotos"] = sum(len(b) for b in blocos.values())
    with open(idx_arq, "w", encoding="utf-8") as f:
        json.dump(idx, f, ensure_ascii=False)
    return len(mudou)


def lista_prefeitos(dados: str) -> dict[str, set]:
    """{UF: {sq}} dos prefeitos eleitos na cópia dos dados."""
    c = Copia(Path(dados))
    por_uf: dict[str, set] = {}
    for x in (c.get("/candidatos?cargo=PREFEITO&eleitos=true") or {}).get("itens") or []:
        if x.get("uf") and x.get("sq_candidato"):
            por_uf.setdefault(x["uf"], set()).add(str(x["sq_candidato"]))
    return por_uf


def main(argv):
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    pasta = argv[0] if argv else "site/midia"
    dados = argv[1] if len(argv) > 1 else "site/dados"
    n, blocos = _blocos(pasta)
    tem = set().union(*[set(b) for b in blocos.values()])
    por_uf = {uf: {sq for sq in sqs if f"tse:{sq}" not in tem} for uf, sqs in lista_prefeitos(dados).items()}
    por_uf = {uf: s for uf, s in por_uf.items() if s}
    novas = fotos_prefeitos_de(por_uf) if por_uf else {}
    print(f"prefeitos: {len(novas)} fotos novas de {sum(len(s) for s in por_uf.values())} que faltavam")
    from app import escandalos
    esc = {}
    for slug, caso in escandalos.casos().items():
        for p in caso["pessoas"]:
            k = "esc:" + p["nome"]
            if k in tem or k in esc:
                continue
            try:
                img = foto_camara(p)
            except Exception as e:  # noqa: BLE001
                log.warning("%s: %s", p["nome"], e)
                img = None
            if img:
                esc[k] = img
                log.info("%s: retrato oficial da Câmara", p["nome"])
    print(f"escândalos: {len(esc)} retratos oficiais novos")
    _gravar(pasta, n, blocos, {**novas, **esc})
    print(f"{sum(len(b) for b in blocos.values())} fotos em {pasta}")


if __name__ == "__main__":
    main(sys.argv[1:])
