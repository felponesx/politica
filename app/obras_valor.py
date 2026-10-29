"""Valor de obra que parece erro de cadastro do ObrasGov.

O ObrasGov é preenchido pelos próprios órgãos e há valores claramente digitados a mais (ex.: a dragagem de um porto com R$ 403 bi, um bloco
de hospital com R$ 81 bi, uma delegacia com R$ 15,8 bi). Não dá para corrigir o número, então ele continua aparecendo como foi declarado, mas
marcado ("valor a conferir") e FORA das somas e dos percentuais. A regra é conservadora e só olha obras de R$ 1 bi para cima:
- R$ 100 bi ou mais: sempre suspeito;
- obras de Defesa (aviões, submarinos, estaleiro) valem bilhões: ficam;
- R$ 10 bi ou mais, fora a Defesa: suspeito;
- de R$ 1 bi a R$ 10 bi: suspeito só quando o nome é de obra pequena (bloco, vestiário, alojamento, escola, delegacia, campus...) ou de
  estradas de um município. Grandes obras reais (transposição do São Francisco, ferrovias, canais, metrôs) ficam.
"""
import re
import unicodedata

LIMITE_REVISAO = 1e9
SEMPRE = 100e9
MUITO_GRANDE = 10e9
_PEQUENA = re.compile(
    r"\b(bloco|vestiario|alojamento|escola|creche|posto de|quadra|ginasio|delegacia|readequa\w*|reforma|edificio|campus|sede|ubs|"
    r"unidade basica|unidade de alimentacao|centro cirurgico|uti|salas?|laboratorio|biblioteca|cobertura|muro|calcada|praca)\b")
_ESTRADAS_MUNICIPIO = re.compile(r"estradas?\b.*\bmunic")
AVISO_VALOR = ("Valor declarado pelo órgão no ObrasGov que parece erro de cadastro (alto demais para esse tipo de obra). "
               "Fica visível, mas não entra nas somas nem nos percentuais. Confira na fonte.")


def _sem_acento(s: str) -> str:
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()


def valor_suspeito(nome: str | None, descricao: str | None, tipo: str | None, valor: float | None) -> bool:
    if not valor or valor < LIMITE_REVISAO:
        return False
    if valor >= SEMPRE:
        return True
    if "defesa" in _sem_acento(tipo):
        return False
    if valor >= MUITO_GRANDE:
        return True
    texto = _sem_acento(f"{nome or ''} {descricao or ''}")
    return bool(_PEQUENA.search(texto) or _ESTRADAS_MUNICIPIO.search(texto))
