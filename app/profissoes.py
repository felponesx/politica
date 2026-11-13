"""Salário por profissão (CBO) a partir dos vínculos da RAIS: só SOMAS são guardadas.

Cada vínculo entra como (cbo, remuneração, horas contratadas). Nenhum nome, CPF ou matrícula chega aqui.
Para cada profissão: quantidade, média, mínimo, máximo, faixas de 10% e 90% (nearest-rank) e a divisão por
faixa de horas contratadas, com a % das pessoas e a média de salário de cada faixa.

A RAIS não informa a escala (6x1 ou 5x2): mostramos as horas contratadas, que é o dado oficial."""
from collections import defaultdict

# faixas de horas contratadas (campo "Faixa Hora Contrat - Código" da RAIS).
# Códigos 1 a 6 vêm do dicionário de 2020; o código 7 aparece no arquivo de 2025 (45 h ou mais) e não está no dicionário de 2020.
FAIXA_HORAS_OFICIAL = {
    1: "até 12 h",
    2: "13 a 15 h",
    3: "16 a 20 h",
    4: "21 a 30 h",
    5: "31 a 40 h",
    6: "41 a 44 h",
    7: "mais de 44 h",  # observado no arquivo de 2025; ausente do dicionário de 2020
}
MINIMO_VINCULOS = 30  # abaixo disso a profissão não sai publicada (amostra pequena demais)


def faixa_de_horas(codigo):
    """código oficial 1..6 -> rótulo; qualquer outra coisa fica de fora."""
    return FAIXA_HORAS_OFICIAL.get(int(codigo)) if codigo is not None else None


def _quantil(valores_ordenados, q):
    """nearest-rank: o valor da posição ceil(q·n) (1-based), sem interpolação."""
    import math
    n = len(valores_ordenados)
    k = max(1, min(n, math.ceil(q * n)))
    return valores_ordenados[k - 1]


def resumir(vinculos):
    """vinculos: iterável de rais_leitor.Vinculo. Devolve {cbo: resumo}."""
    por_cbo = defaultdict(list)
    for v in vinculos:
        cbo, rem, faixa = v.cbo, v.remuneracao, v.faixa_horas
        if cbo is None or rem is None or rem <= 0:
            continue
        por_cbo[str(cbo)].append((float(rem), faixa))

    saida = {}
    for cbo, itens in por_cbo.items():
        n = len(itens)
        if n < MINIMO_VINCULOS:
            continue
        rems = sorted(r for r, _ in itens)
        media = sum(rems) / n
        faixas = []
        por_faixa = defaultdict(list)
        for r, faixa in itens:
            f = faixa_de_horas(faixa)
            if f:
                por_faixa[f].append(r)
        for rotulo in FAIXA_HORAS_OFICIAL.values():
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


# ---------- acumulação em streaming (usada pelo coletor: não guarda os vínculos, só contagens) ----------
PASSO_FAIXA_REM = 10  # resolução dos percentis: R$ 10 (o mínimo e o máximo são exatos)


class Acumulador:
    """Soma vínculos um a um. Por profissão guarda: contagem, soma, mínimo, máximo, histograma de
    remuneração (em degraus de R$ 10) e contagem por faixa de horas. Nenhum vínculo individual fica na memória."""

    def __init__(self):
        self.prof = {}

    def add(self, cbo, remuneracao, faixa_horas):
        if not cbo or remuneracao is None or remuneracao <= 0 or faixa_horas is None:
            return
        p = self.prof.get(cbo)
        if p is None:
            p = self.prof[cbo] = {"n": 0, "soma": 0.0, "min": None, "max": None, "hist": {}, "faixas": {}}
        p["n"] += 1
        p["soma"] += remuneracao
        p["min"] = remuneracao if p["min"] is None else min(p["min"], remuneracao)
        p["max"] = remuneracao if p["max"] is None else max(p["max"], remuneracao)
        bucket = int(remuneracao // PASSO_FAIXA_REM)
        p["hist"][bucket] = p["hist"].get(bucket, 0) + 1
        f = p["faixas"].get(faixa_horas)
        if f is None:
            f = p["faixas"][faixa_horas] = [0, 0.0]
        f[0] += 1
        f[1] += remuneracao

    def total(self):
        return sum(p["n"] for p in self.prof.values())

    def resultado(self, minimo=MINIMO_VINCULOS):
        saida = {}
        for cbo, p in self.prof.items():
            n = p["n"]
            if n < minimo:
                continue
            hist = sorted(p["hist"].items())

            def quantil(q):
                k = max(1, min(n, -(-int(q * n * 1000) // 1000)))
                acumulado = 0
                for bucket, c in hist:
                    acumulado += c
                    if acumulado >= k:
                        return float(bucket * PASSO_FAIXA_REM)
                return float(hist[-1][0] * PASSO_FAIXA_REM)

            faixas = []
            for cod in sorted(p["faixas"]):
                rotulo = faixa_de_horas(cod)
                if rotulo is None:
                    continue
                k, soma = p["faixas"][cod]
                faixas.append({"faixa": rotulo, "pct": round(100 * k / n, 1), "media": round(soma / k, 2)})
            saida[cbo] = {
                "vinculos": n,
                "media": round(p["soma"] / n, 2),
                "minimo": round(p["min"], 2),
                "maximo": round(p["max"], 2),
                "p10": quantil(0.10),
                "p90": quantil(0.90),
                "horas": faixas,
            }
        return saida
