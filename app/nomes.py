"""Achar nome de pessoa mesmo escrito errado ("Nicolas Ferrera" acha "Nikolas Ferreira"). Sem IA, sem custo, no próprio banco.

Duas ideias juntas:
1. chave fonética do português: c/k, ç/s, y/i, ph/f, h inicial mudo, letras dobradas viram uma só (rr, ss, ll...);
2. distância de edição entre as palavras, para erros de digitação (letra trocada, faltando ou sobrando).

A consulta e cada nome são quebrados em palavras; cada palavra da consulta procura a mais parecida do nome (a ordem não importa,
"Ferreira Nikolas" também acha). Palavras de ligação (da, de, dos...) são ignoradas.
"""
import re
import unicodedata
from collections import defaultdict

LIGACAO = {"da", "de", "do", "das", "dos", "e", "d"}
MIN_PALAVRA = 0.62      # cada palavra da consulta precisa de uma parecida pelo menos assim
MIN_TOTAL = 0.76        # nota final mínima para aparecer


def normalizar(texto: str) -> str:
    """Minúsculas, sem acento (ç vira s), só letras, números e espaço."""
    t = texto.lower().replace("ç", "s")
    t = unicodedata.normalize("NFKD", t)
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def fonetica(palavra: str) -> str:
    """Chave de pronúncia aproximada para o português do Brasil."""
    p = palavra
    p = p.replace("ph", "f").replace("th", "t").replace("ck", "k")
    p = re.sub(r"^h", "", p)
    p = re.sub(r"ch|sh", "x", p)
    p = re.sub(r"qu(?=[ei])", "k", p)
    p = re.sub(r"gu(?=[ei])", "g", p)
    p = re.sub(r"c(?=[ei])", "s", p)
    p = re.sub(r"g(?=[ei])", "j", p)
    p = p.replace("c", "k").replace("q", "k").replace("y", "i").replace("w", "v").replace("z", "s")
    return re.sub(r"(.)\1+", r"\1", p)


def distancia(a: str, b: str) -> int:
    """Distância de edição (Levenshtein)."""
    if a == b:
        return 0
    if len(a) < len(b):
        a, b = b, a
    anterior = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        atual = [i]
        for j, cb in enumerate(b, 1):
            atual.append(min(anterior[j] + 1, atual[j - 1] + 1, anterior[j - 1] + (ca != cb)))
        anterior = atual
    return anterior[-1]


def nota_palavra(q: str, c: str) -> float:
    """0 a 1: quão parecidas são duas palavras (já na forma fonética)."""
    if q == c:
        return 1.0
    if len(q) >= 3 and c.startswith(q):   # o usuário ainda está digitando: "nikol" -> "nikolas"
        return 0.95
    return max(0.0, 1.0 - distancia(q, c) / max(len(q), len(c)))


def palavras(texto: str) -> list[str]:
    return [fonetica(w) for w in normalizar(texto).split() if w not in LIGACAO and len(w) > 0]


def nota_nome(consulta: list[str], nome: list[str]) -> float:
    """Nota de 0 a 1 de um nome para a consulta (cada palavra do nome é usada uma vez). 0 se alguma palavra não achar par."""
    if not consulta or not nome:
        return 0.0
    livres = list(nome)
    total = 0.0
    for q in sorted(consulta, key=len, reverse=True):
        melhor, idx = 0.0, -1
        for i, c in enumerate(livres):
            n = nota_palavra(q, c)
            if n > melhor:
                melhor, idx = n, i
        if melhor < MIN_PALAVRA:
            return 0.0
        total += melhor
        livres.pop(idx)
    base = total / len(consulta)
    return base * (0.92 + 0.08 * min(len(consulta), len(nome)) / max(len(consulta), len(nome)))   # nome completo vale um pouco mais


class IndiceNomes:
    """Nomes na memória, com um índice por primeira letra e tamanho para não comparar com todo mundo."""

    LIMITE_AMPLIADO = 60_000   # sem resposta pela primeira letra: tenta todas as palavras, se o vocabulário for pequeno

    def __init__(self, itens: list[tuple[int, str]]):
        self.itens: list[tuple[int, str, list[str]]] = []
        self.vocab: dict[str, list[int]] = defaultdict(list)
        for ident, nome in itens:
            ps = palavras(nome or "")
            if not ps:
                continue
            self.itens.append((ident, nome, ps))
            for p in set(ps):
                self.vocab[p].append(len(self.itens) - 1)
        self.por_inicial: dict[str, list[str]] = defaultdict(list)
        for p in self.vocab:
            self.por_inicial[p[0]].append(p)

    def _candidatos(self, q: str, todas: bool) -> set[int]:
        palavras_proximas = (self.vocab.keys() if todas else self.por_inicial.get(q[0], []))
        achados: set[int] = set()
        for p in palavras_proximas:
            if abs(len(p) - len(q)) > max(2, len(q) // 2):
                continue
            if nota_palavra(q, p) >= MIN_PALAVRA:
                achados.update(self.vocab[p])
        return achados

    def buscar(self, consulta: str, limite: int = 10) -> list[tuple[int, str, float]]:
        qs = palavras(consulta)
        if not qs:
            return []
        for todas in (False, True):
            if todas and len(self.vocab) > self.LIMITE_AMPLIADO:
                break
            base = max(qs, key=len)   # a palavra mais longa é a mais informativa: define quem entra na disputa
            candidatos = self._candidatos(base, todas)
            pontuados = []
            for i in candidatos:
                ident, nome, ps = self.itens[i]
                n = nota_nome(qs, ps)
                if n >= MIN_TOTAL:
                    pontuados.append((ident, nome, round(n, 3)))
            if pontuados:
                pontuados.sort(key=lambda x: (-x[2], len(x[1]), x[1]))
                return pontuados[:limite]
        return []
