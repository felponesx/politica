"""Padroniza textos e siglas de partido que chegam das fontes oficiais com defeitos de formatação.

O conteúdo não muda; só a forma:
- espaços sobrando no começo e no fim, e espaços repetidos ("EDINA WANDERLEY ", "Altera  disposições");
- entidades HTML que vieram escapadas ("J A SOBRAL &amp; CIA" → "J A SOBRAL & CIA");
- acentos quebrados por leitura com a codificação errada ("AquisiÃ§Ã£o" → "Aquisição");
- traço ou "nan" no lugar de campo vazio;
- a mesma sigla escrita de jeitos diferentes pelo TSE ao longo dos anos ("PC DO B", "PCDOB" → "PCdoB"; "SD" →
  "SOLIDARIEDADE"; "PATRI" → "PATRIOTA"). Nomes antigos de partidos (PMDB, PFL, PRB...) ficam como eram na época.

Usado ao gravar no banco (app/utils.upsert) e ao exportar a cópia estática do site (scripts/exportar_snapshot.py).
"""
from __future__ import annotations

import html
import re

_QUEBRADO = re.compile(r"Ã[\x80-\xbf]|Â[\x80-\xbf]|â€")
_ENTIDADE = re.compile(r"&(?:[a-zA-Z]{2,8}|#\d{2,5}|#x[0-9a-fA-F]{2,4});")
_ESPACOS = re.compile(r"[ \t ]+")
_VAZIOS = {"-", "--", "nan", "none", "null", "#n/d", "n/d"}
CAMPOS_PARTIDO = {"partido", "sigla_partido", "sg_partido", "partido_na_data", "partido_atual", "partido_mais_recente"}
# mesma sigla, grafias diferentes (chave: só letras, maiúsculas)
_SIGLAS = {"PCDOB": "PCdoB", "PTDOB": "PT do B", "SD": "SOLIDARIEDADE", "PATRI": "PATRIOTA", "UNIAO": "UNIÃO"}


def _desquebrar(s: str) -> str:
    """Desfaz UTF-8 lido como Latin-1/Windows-1252 (só quando o resultado volta a ser texto válido)."""
    for cod in ("cp1252", "latin-1"):
        try:
            novo = s.encode(cod).decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
        if not _QUEBRADO.search(novo):
            return novo
    return s


def texto(s, vazio_none: bool = True):
    """Texto padronizado; com vazio_none, devolve None para campo vazio disfarçado ("-", "nan"). Outros tipos passam."""
    if not isinstance(s, str):
        return s
    if _QUEBRADO.search(s):
        s = _desquebrar(s)
    if "&" in s and _ENTIDADE.search(s):
        s = html.unescape(s)
    if "\n" in s:
        s = "\n".join(_ESPACOS.sub(" ", linha).strip() for linha in s.strip().splitlines())
    else:
        s = _ESPACOS.sub(" ", s).strip()
    return None if vazio_none and s.lower() in _VAZIOS else s


def partido(s, vazio_none: bool = True):
    if not isinstance(s, str):
        return s
    s = texto(s, vazio_none)
    if not s:
        return s
    chave = re.sub(r"[^A-Z]", "", s.upper().replace("Ã", "A"))
    return _SIGLAS.get(chave, s)


def limpar(x, campo: str | None = None, vazio_none: bool = True):
    """Aplica a padronização em qualquer estrutura (dict, lista, texto). Chaves de dicionário não mudam."""
    if isinstance(x, str):
        return partido(x, vazio_none) if campo in CAMPOS_PARTIDO else texto(x, vazio_none)
    if isinstance(x, dict):
        return {k: limpar(v, k, vazio_none) for k, v in x.items()}
    if isinstance(x, list):
        return [limpar(v, campo, vazio_none) for v in x]
    return x
