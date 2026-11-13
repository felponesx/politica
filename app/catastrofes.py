"""Catástrofes e acidentes: tragédias marcantes (cadastro curado, com fonte) e acidentes nas rodovias federais por estado e tipo de envolvido.

Regras: toda tragédia tem fonte (sem fonte é descartada ao carregar); o número de mortos é o que a fonte citou (`mortos_nota` diz de onde vem
e o que a conta inclui). Acidentes: a porcentagem de cada tipo é sobre os ACIDENTES do estado (uma ocorrência com moto e pedestre conta nas duas),
não sobre pessoas. Motoboy não é identificável no arquivo da PRF: o que dá para separar é o condutor de motocicleta ou motoneta.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from sqlalchemy.orm import Session

from app.collectors.prf import CATEGORIAS_PESSOA
from app.models import Registro
from app.utils import UFS

CADASTRO = Path(__file__).parent / "dados" / "catastrofes.json"

ROTULOS = {
    "pedestre": "Pedestre",
    "motociclista": "Motociclista (moto ou motoneta)",
    "motorista_carro": "Motorista de carro, caminhonete ou utilitário",
    "caminhao_carreta": "Caminhão ou carreta (condutor)",
    "onibus": "Ônibus e micro-ônibus (condutor)",
    "bicicleta": "Ciclista",
}
TIPOS = {"aviao": "Avião", "barragem": "Barragem", "chuva_deslizamento": "Chuva e deslizamento", "incendio": "Incêndio",
         "rodovia": "Rodovia", "desabamento": "Desabamento", "naufragio": "Naufrágio", "ferrovia": "Ferrovia"}
AVISO_CATASTROFES = ("Lista de tragédias marcantes, com a fonte de cada número. Os totais de mortos são os citados pela fonte e podem diferir entre "
                     "fontes (a nota de cada caso diz o que a conta inclui). Não é lista completa de acidentes do país.")
AVISO_RODOVIAS = ("Acidentes nas rodovias federais (PRF), que não cobrem rodovias estaduais nem vias urbanas. A porcentagem de cada tipo é sobre os acidentes "
                  "do estado: um acidente com moto e pedestre aparece nas duas. Motoboy não é separado: o arquivo traz o condutor de moto, não a profissão.")


def _valida(x: dict) -> bool:
    return bool(x.get("titulo") and x.get("data") and x.get("uf") in UFS and x.get("fontes")
                and all(f.get("url", "").startswith("https://") for f in x["fontes"]))


def tragedias(tipo: str | None = None) -> dict:
    """Tragédias marcantes do cadastro (mais recentes primeiro). Registro sem fonte é descartado."""
    itens = json.loads(CADASTRO.read_text(encoding="utf-8"))
    validos = [x for x in itens if _valida(x)]
    if tipo:
        validos = [x for x in validos if x.get("tipo") == tipo]
    validos.sort(key=lambda x: x["data"], reverse=True)
    tipos = sorted({x["tipo"] for x in itens if _valida(x)})
    return {"total": len(validos), "itens": validos, "tipos": {t: TIPOS.get(t, t) for t in tipos}, "aviso": AVISO_CATASTROFES,
            "descartados": len(itens) - len([x for x in itens if _valida(x)])}


def _regs(db: Session, tipo: str) -> dict[int, dict]:
    return {int(r.chave): r.dados for r in db.query(Registro).filter_by(fonte="prf", tipo=tipo).all() if r.chave.isdigit()}


def rodovias(db: Session, ano: int | None = None) -> dict | None:
    """Acidentes por estado no ano escolhido (o mais recente com dados por pessoa, por padrão)."""
    pessoas = _regs(db, "pessoas_ano")
    if not pessoas:
        return None
    anos_disponiveis = sorted(pessoas, reverse=True)
    ano = ano or anos_disponiveis[0]
    if ano not in pessoas:
        return {"anos": anos_disponiveis, "ano": ano, "erro": "sem dados desse ano"}
    d = pessoas[ano]
    totais = _regs(db, "acidentes_ano").get(ano, {}).get("por_uf", {})  # mortos totais por estado (arquivo por ocorrência)
    estados = []
    tot_ac, tot_mortos = 0, 0
    tot_cat = {c: {"ocorrencias": 0, "mortos": 0} for c in CATEGORIAS_PESSOA}
    for uf in sorted(d["por_uf"]):
        u = d["por_uf"][uf]
        ac = u["acidentes"]
        cats = {}
        for c in CATEGORIAS_PESSOA:
            x = u["categorias"][c]
            cats[c] = {"ocorrencias": x["ocorrencias"], "pct": round(100 * x["ocorrencias"] / ac, 1) if ac else 0.0, "mortos": x["mortos"]}
            tot_cat[c]["ocorrencias"] += x["ocorrencias"]
            tot_cat[c]["mortos"] += x["mortos"]
        tot_ac += ac
        estados.append({"uf": uf, "acidentes": ac, "mortos": (totais.get(uf) or {}).get("mortos") if totais else None, "categorias": cats})
    estados.sort(key=lambda e: -e["acidentes"])
    brasil = {"acidentes": tot_ac, "categorias": {c: {"ocorrencias": v["ocorrencias"], "pct": round(100 * v["ocorrencias"] / tot_ac, 1) if tot_ac else 0.0,
                                                    "mortos": v["mortos"]} for c, v in tot_cat.items()}}
    return {"ano": ano, "parcial": ano >= date.today().year, "anos": anos_disponiveis, "brasil": brasil, "estados": estados, "rotulos": ROTULOS,
            "aviso": AVISO_RODOVIAS, "fonte": "Polícia Rodoviária Federal — dados abertos (arquivo por pessoa)",
            "definicao": {"pedestre": "Pessoa com envolvido = Pedestre.", "motociclista": "Condutor de motocicleta ou motoneta.",
                          "motorista_carro": "Condutor de automóvel, caminhonete, camioneta ou utilitário.",
                          "caminhao_carreta": "Condutor de caminhão ou caminhão-trator (cavalo mecânico que puxa a carreta).",
                          "onibus": "Condutor de ônibus ou micro-ônibus.", "bicicleta": "Condutor de bicicleta."}}
