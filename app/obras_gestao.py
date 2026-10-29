"""Andamento das obras e projetos de um governo (presidente, governador ou prefeito).

Base: obras com dinheiro federal cadastradas no ObrasGov. Não são todas as obras de um governo nem as promessas do plano de
governo (não existe base aberta que acompanhe o plano). A porcentagem é a parte das obras (em número e em valor) em cada situação;
o atraso é o prazo previsto de término já vencido em obra que não foi concluída nem cancelada.
"""
import re
from datetime import date

from app.obras_valor import AVISO_VALOR, valor_suspeito
from app.utils import sem_acento

CATEGORIAS = [("concluida", "Concluídas"), ("execucao", "Em andamento"), ("parada", "Paradas"),
              ("nao_iniciada", "Não começaram"), ("sem_situacao", "Sem situação"), ("cancelada", "Canceladas")]
AVISO = ("Só entram obras com dinheiro federal cadastradas no ObrasGov; não são todas as obras do governo nem as promessas do plano de "
         "governo. A porcentagem é a parte das obras em cada situação (canceladas ficam de fora da conta). O atraso conta o prazo previsto "
         "de término já vencido em obra não concluída. O percentual de execução física de cada obra não é publicado de forma aberta.")

_ESTADUAL = re.compile(r"^(ESTADO D|GOVERNO D|SECRETARIA)|SECRETARIA (DE|DO|DA) ESTADO|DO ESTADO\b")
_MUNIC = re.compile(r"^(MUNICIPIO|PREFEITURA)( MUNICIPAL)?( DE| DO| DA| DOS| DAS)? (.+)$")


def categoria(situacao: str | None) -> str:
    s = sem_acento(situacao or "").lower()
    if s.startswith("conclu"):
        return "concluida"
    if "execu" in s:
        return "execucao"
    if s.startswith(("paraliz", "paralis", "inacab", "inativ")):
        return "parada"
    if s.startswith("cancel"):
        return "cancelada"
    if s.startswith(("cadastr", "nao inici", "em licit", "em planej")):
        return "nao_iniciada"
    return "sem_situacao"


def eh_estadual(executor: str | None) -> bool:
    return bool(_ESTADUAL.search(sem_acento(executor or "").upper()))


def nome_municipio(executor: str | None) -> str | None:
    m = _MUNIC.match(sem_acento(executor or "").upper().strip())
    return re.sub(r"\s*\([A-Z]{2}\)$", "", m.group(4)).strip() if m else None


def _suspeita(o) -> bool:
    return valor_suspeito(o.nome, o.descricao, getattr(o, "tipo", None), o.valor_previsto)


def resumir(obras, hoje: date | None = None, lista: int = 8) -> dict:
    """obras: iteráveis de objetos com situacao, valor_previsto, fim_previsto, id, nome, descricao, executor (e, se houver, tipo).
    Obra com valor que parece erro de cadastro (app/obras_valor.py) conta na quantidade, mas não nos valores nem nos percentuais de valor."""
    hoje = hoje or date.today()
    obras = list(obras)
    suspeitas = [o for o in obras if _suspeita(o)]
    ids_suspeitos = {id(o) for o in suspeitas}
    valor = lambda o: 0 if id(o) in ids_suspeitos else (o.valor_previsto or 0)  # noqa: E731
    por = {k: {"quantidade": 0, "valor": 0.0} for k, _ in CATEGORIAS}
    atrasos, no_prazo, sem_data, prox = [], 0, 0, None
    for o in obras:
        k = categoria(o.situacao)
        por[k]["quantidade"] += 1
        por[k]["valor"] += valor(o)
        if k in ("concluida", "cancelada"):
            continue
        if not o.fim_previsto or o.fim_previsto.year < 1990:  # data vazia ou absurda (ex.: 1900) não conta como atraso
            sem_data += 1
        elif o.fim_previsto < hoje:
            atrasos.append((o, (hoje - o.fim_previsto).days))
        else:
            no_prazo += 1
            prox = o.fim_previsto if prox is None or o.fim_previsto < prox else prox
    total = sum(v["quantidade"] for v in por.values())
    valido = total - por["cancelada"]["quantidade"]
    valido_v = sum(v["valor"] for k, v in por.items() if k != "cancelada")
    for k, v in por.items():
        v["valor"] = round(v["valor"], 2)
        v["pct_obras"] = round(100 * v["quantidade"] / valido, 1) if valido and k != "cancelada" else None
        v["pct_valor"] = round(100 * v["valor"] / valido_v, 1) if valido_v and k != "cancelada" else None
    abertas = total - por["concluida"]["quantidade"] - por["cancelada"]["quantidade"]
    dias = [d for _, d in atrasos]
    return {"total": total, "valor_total": round(sum(v["valor"] for v in por.values()), 2),
            "situacoes": [{"chave": k, "nome": n, **por[k]} for k, n in CATEGORIAS],
            "pct_concluido": por["concluida"]["pct_obras"], "pct_concluido_valor": por["concluida"]["pct_valor"],
            "falta": {"obras": abertas, "valor": round(sum(por[k]["valor"] for k in ("execucao", "parada", "nao_iniciada", "sem_situacao")), 2)},
            "atraso": {"obras": len(atrasos), "pct_das_abertas": round(100 * len(atrasos) / abertas, 1) if abertas else None,
                       "valor": round(sum(valor(o) for o, _ in atrasos), 2),
                       "dias_medio": round(sum(dias) / len(dias)) if dias else None, "dias_maior": max(dias) if dias else None},
            "no_prazo": no_prazo, "sem_data_prevista": sem_data, "proximo_termino": prox,
            "mais_atrasadas": [{"id": o.id, "nome": (o.descricao or o.nome or "Obra")[:140], "situacao": o.situacao, "executor": o.executor,
                                "fim_previsto": o.fim_previsto, "dias_atraso": d, "valor": None if id(o) in ids_suspeitos else o.valor_previsto,
                                "valor_suspeito": id(o) in ids_suspeitos}
                               for o, d in sorted(atrasos, key=lambda x: -valor(x[0]))[:lista]],
            "valor_suspeito": {"obras": len(suspeitas), "valor": round(sum(o.valor_previsto or 0 for o in suspeitas), 2),
                               "aviso": AVISO_VALOR if suspeitas else None},
            "aviso": AVISO, "fonte": "ObrasGov (Ministério da Gestão e Inovação / Ministério da Integração)", "data": hoje}


CAMPOS_LISTA = ["id", "nome", "cat", "fim", "valor", "tipo", "municipio", "executor", "tipo_obra", "suspeito"]


def lista_compacta(obras) -> list:
    """Todas as obras de um estado em linhas curtas (uma lista por UF na cópia do site). cat: concluida, execucao, parada, nao_iniciada,
    sem_situacao ou cancelada; tipo: E (executor estadual), M (prefeitura) ou F (outro); municipio: nome sem acento da prefeitura."""
    out = []
    for o in obras:
        mun = nome_municipio(o.executor)
        tipo = "M" if mun else ("E" if eh_estadual(o.executor) else "F")
        fim = o.fim_previsto.isoformat() if o.fim_previsto and o.fim_previsto.year >= 1990 else ""
        suspeita = _suspeita(o)  # valor que parece erro de cadastro: vai como 0 (fora das somas) e marcado em `suspeito`
        out.append([o.id, (o.descricao or o.nome or "Obra")[:110], categoria(o.situacao), fim, 0 if suspeita else round(o.valor_previsto or 0), tipo,
                    mun or "", (o.executor or "")[:70], (getattr(o, "tipo", None) or "")[:60], 1 if suspeita else 0])
    out.sort(key=lambda r: -r[4])
    return out
