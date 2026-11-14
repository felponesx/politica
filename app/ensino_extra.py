"""Ensino: quanto ganham os professores (RAIS 2024) e como o ensino se divide entre redes (Censo Escolar).

Salários: a RAIS traz, por ocupação (CBO), a remuneração média nominal dos vínculos ativos em 31/12 e a faixa típica (p10 e p90).
A média de uma etapa é a média das ocupações dela ponderada pelo número de vínculos (é a média exata do grupo, não uma estimativa).
Não há mediana nem faixa por etapa: a faixa só existe por ocupação. Não há separação entre escola pública e privada nesta base.
Redes: somas de escolas, matrículas e professores por etapa e rede (Censo Escolar). O arquivo NÃO traz disciplinas.
"""
import json
from pathlib import Path

from sqlalchemy.orm import Session

from app.models import Registro

DADOS = Path(__file__).parent / "dados"

# ocupações da RAIS (CBO) agrupadas por etapa
NIVEIS = [
    ("fundamental_iniciais", "Ensino fundamental — anos iniciais (1º ao 5º)", ["231210"]),
    ("fundamental_finais", "Ensino fundamental — anos finais (cada disciplina)", ["231305", "231310", "231315", "231320", "231325", "231330", "231335", "231340"]),
    ("medio", "Ensino médio (cada disciplina e disciplinas pedagógicas)", ["232105", "232110", "232115", "232120", "232125", "232130", "232135",
                                                                          "232140", "232145", "232150", "232155", "232165", "232170"]),
]
AVISO_SALARIOS = ("Remuneração média nominal de quem tem vínculo de trabalho ativo em 31/12/2024, segundo a RAIS (Ministério do Trabalho). "
                  "Inclui escola pública e privada, todas as jornadas e todos os vínculos de cada professor (quem tem mais de um vínculo aparece em cada um). "
                  "Não é salário-hora nem piso salarial. A faixa típica (10% e 90%) só existe por ocupação.")


def _media_ponderada(itens: list[dict]) -> float | None:
    vinc = sum(x["vinculos"] for x in itens)
    if not vinc:
        return None
    return round(sum(x["media"] * x["vinculos"] for x in itens) / vinc, 2)


def professores() -> dict | None:
    """Remuneração média dos professores por etapa e por ocupação (RAIS 2024), com a média da jornada de 31 horas ou mais."""
    arq = DADOS / "profissoes_rais_2024.json"
    cbo = DADOS / "cbo_nomes.json"
    if not arq.exists():
        return None
    rais = json.loads(arq.read_text(encoding="utf-8"))
    nomes = json.loads(cbo.read_text(encoding="utf-8")).get("nomes", {}) if cbo.exists() else {}
    prof = rais.get("profissoes", {})
    niveis = []
    for chave, rotulo, codigos in NIVEIS:
        ocup = []
        for c in codigos:
            p = prof.get(c)
            if not p or not p.get("vinculos"):
                continue
            ocup.append({"cbo": c, "ocupacao": nomes.get(c, c), "vinculos": p["vinculos"], "media": p["media"],
                         "p10": p.get("p10"), "p90": p.get("p90")})
        if not ocup:
            continue
        # jornada de 31 h ou mais: faixas da RAIS (pct de vínculos e média por faixa)
        j = []
        for c in codigos:
            p = prof.get(c)
            if not p or not p.get("vinculos"):
                continue
            for f in p.get("horas", []):
                if f["faixa"] in ("31 a 40 h", "41 a 44 h", "mais de 44 h") and f.get("pct"):
                    j.append({"media": f["media"], "vinculos": p["vinculos"] * f["pct"] / 100})
        niveis.append({"chave": chave, "nivel": rotulo, "vinculos": sum(x["vinculos"] for x in ocup),
                       "media": _media_ponderada(ocup), "media_jornada_31h_ou_mais": _media_ponderada(j) if j else None,
                       "ocupacoes": sorted(ocup, key=lambda x: -x["vinculos"])})
    return {"ano": rais.get("ano_referencia"), "fonte": rais.get("fonte"), "niveis": niveis, "aviso": AVISO_SALARIOS}


AVISO_REDES = ("Escolas em atividade, por estado e rede (Censo Escolar do INEP). Professores por etapa não somam entre etapas "
               "(quem dá aula em duas etapas conta nas duas). Esta base NÃO traz as disciplinas (matérias) que cada escola dá.")
REDES_ORDEM = ["estadual", "privada", "municipal", "federal"]


def redes(db: Session, ano: int | None = None, uf: str | None = None) -> dict | None:
    """Escolas, matrículas e professores por rede. Sem `uf`, dá o país e os estados; com `uf`, só aquele estado."""
    q = db.query(Registro).filter(Registro.fonte == "inep", Registro.tipo == "censo_escolar_rede")
    regs = q.all()
    if not regs:
        return None
    anos = sorted({r.dados["ano"] for r in regs if r.dados}, reverse=True)
    ano = ano or anos[0]
    linhas = [r.dados for r in regs if r.dados and r.dados.get("ano") == ano]
    if not linhas:
        return {"anos": anos, "ano": ano, "erro": "sem dados desse ano"}
    pais = {x["rede"]: x for x in linhas if x["uf"] == "BR"}
    estados: dict[str, dict] = {}
    for x in linhas:
        if x["uf"] == "BR":
            continue
        e = estados.setdefault(x["uf"], {"uf": x["uf"], "redes": {}})
        e["redes"][x["rede"]] = x
    if uf:
        estados = {k: v for k, v in estados.items() if k == uf.upper()}
    lista = [{"uf": k, "redes": v["redes"]} for k, v in sorted(estados.items())]
    return {"ano": ano, "anos": anos, "fonte": "INEP — Censo Escolar", "aviso": AVISO_REDES, "pais": pais, "estados": lista,
            "redes_ordem": REDES_ORDEM}
