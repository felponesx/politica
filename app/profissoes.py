"""Salário por profissão (CBO) a partir dos vínculos da RAIS: só SOMAS são guardadas.

Cada vínculo entra como (cbo, remuneração, horas contratadas). Nenhum nome, CPF ou matrícula chega aqui.
Para cada profissão: quantidade, média, mínimo, máximo, faixas de 10% e 90% (nearest-rank) e a divisão por
faixa de horas contratadas, com a % das pessoas e a média de salário de cada faixa.

A RAIS não informa a escala (6x1 ou 5x2): mostramos as horas contratadas, que é o dado oficial."""
from collections import defaultdict

# faixas de horas contratadas semanais: (rótulo, limite inferior inclusive, superior inclusive)
FAIXAS_HORAS = [
    ("até 30 h", 0, 30),
    ("31 a 36 h", 31, 36),
    ("37 a 40 h", 37, 40),
    ("41 a 44 h", 41, 44),
    ("mais de 44 h", 45, 10_000),
]
MINIMO_VINCULOS = 30  # abaixo disso a profissão não sai publicada (amostra pequena demais)


def faixa_de_horas(horas):
    for rotulo, lo, hi in FAIXAS_HORAS:
        if lo <= horas <= hi:
            return rotulo
    return None


def _quantil(valores_ordenados, q):
    """nearest-rank: o valor da posição ceil(q·n) (1-based), sem interpolação."""
    import math
    n = len(valores_ordenados)
    k = max(1, min(n, math.ceil(q * n)))
    return valores_ordenados[k - 1]


def resumir(vinculos):
    """vinculos: iterável de (cbo:str, remuneracao:float, horas:int). Devolve {cbo: resumo}."""
    por_cbo = defaultdict(list)
    for cbo, rem, horas in vinculos:
        if cbo is None or rem is None or rem < 0:
            continue
        por_cbo[str(cbo)].append((float(rem), int(horas or 0)))

    saida = {}
    for cbo, itens in por_cbo.items():
        n = len(itens)
        if n < MINIMO_VINCULOS:
            continue
        rems = sorted(r for r, _ in itens)
        media = sum(rems) / n
        faixas = []
        por_faixa = defaultdict(list)
        for r, h in itens:
            f = faixa_de_horas(h)
            if f:
                por_faixa[f].append(r)
        for rotulo, _, _ in FAIXAS_HORAS:
            lista = por_faixa.get(rotulo)
            if not lista:
                continue
            faixas.append({
                "faixa": rotulo,
                "pct": round(100 * len(lista) / n, 1),
                "media": round(sum(lista) / len(lista), 2),
            })
        saida[cbo] = {
            "vinculos": n,
            "media": round(media, 2),
            "minimo": round(rems[0], 2),
            "maximo": round(rems[-1], 2),
            "p10": round(_quantil(rems, 0.10), 2),
            "p90": round(_quantil(rems, 0.90), 2),
            "horas": faixas,
        }
    return saida


def ranking(resumo, campo="media", maior_primeiro=True, limite=10):
    itens = sorted(resumo.items(), key=lambda kv: kv[1][campo], reverse=maior_primeiro)
    return [{"cbo": k, **v} for k, v in itens[:limite]]
