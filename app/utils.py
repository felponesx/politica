import hashlib
from datetime import date, datetime, timedelta

from sqlalchemy import select

UF_POR_CODIGO_IBGE = {
    11: "RO", 12: "AC", 13: "AM", 14: "RR", 15: "PA", 16: "AP", 17: "TO",
    21: "MA", 22: "PI", 23: "CE", 24: "RN", 25: "PB", 26: "PE", 27: "AL", 28: "SE", 29: "BA",
    31: "MG", 32: "ES", 33: "RJ", 35: "SP", 41: "PR", 42: "SC", 43: "RS",
    50: "MS", 51: "MT", 52: "GO", 53: "DF",
}
CODIGO_IBGE_POR_UF = {v: k for k, v in UF_POR_CODIGO_IBGE.items()}
UFS = list(CODIGO_IBGE_POR_UF)

NOME_PARA_UF = {
    "ACRE": "AC", "ALAGOAS": "AL", "AMAPA": "AP", "AMAZONAS": "AM", "BAHIA": "BA", "CEARA": "CE",
    "DISTRITO FEDERAL": "DF", "ESPIRITO SANTO": "ES", "GOIAS": "GO", "MARANHAO": "MA",
    "MATO GROSSO": "MT", "MATO GROSSO DO SUL": "MS", "MINAS GERAIS": "MG", "PARA": "PA",
    "PARAIBA": "PB", "PARANA": "PR", "PERNAMBUCO": "PE", "PIAUI": "PI", "RIO DE JANEIRO": "RJ",
    "RIO GRANDE DO NORTE": "RN", "RIO GRANDE DO SUL": "RS", "RONDONIA": "RO", "RORAIMA": "RR",
    "SANTA CATARINA": "SC", "SAO PAULO": "SP", "SERGIPE": "SE", "TOCANTINS": "TO",
}
MESES = {"JANEIRO": 1, "FEVEREIRO": 2, "MARCO": 3, "ABRIL": 4, "MAIO": 5, "JUNHO": 6, "JULHO": 7,
         "AGOSTO": 8, "SETEMBRO": 9, "OUTUBRO": 10, "NOVEMBRO": 11, "DEZEMBRO": 12}


def sem_acento(s: str) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", str(s)) if unicodedata.category(c) != "Mn").upper().strip()


def para_uf(valor) -> str | None:
    """Aceita sigla ('SP'), nome ('São Paulo') ou código IBGE (35)."""
    if valor is None:
        return None
    s = sem_acento(valor)
    if s in CODIGO_IBGE_POR_UF:
        return s
    if s.isdigit():
        return UF_POR_CODIGO_IBGE.get(int(s))
    return NOME_PARA_UF.get(s)


def para_mes(valor) -> int | None:
    s = sem_acento(valor or "")
    if not s:
        return None
    if s.isdigit():
        return int(s) if 1 <= int(s) <= 12 else None
    return MESES.get(s) or MESES.get(next((m for m in MESES if m.startswith(s[:3])), ""), None)


def upsert(db, model, chaves: dict, valores: dict):
    """Insere ou atualiza pelo conjunto de chaves únicas (portável entre SQLite e Postgres).
    Textos e siglas de partido dos valores são padronizados (app/limpeza.py); as chaves ficam como vieram."""
    from app.limpeza import limpar
    valores = limpar(valores, vazio_none=False)
    obj = db.execute(select(model).filter_by(**chaves)).scalar_one_or_none()
    if obj is None:
        obj = model(**chaves, **valores)
        db.add(obj)
    else:
        for k, v in valores.items():
            setattr(obj, k, v)
    return obj


def hash_curto(*partes) -> str:
    return hashlib.sha1("|".join(str(p) for p in partes).encode(), usedforsecurity=False).hexdigest()[:24]


def para_data(valor) -> date | None:
    if not valor:
        return None
    if isinstance(valor, date):
        return valor
    s = str(valor).strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d", "%d/%m/%Y", "%Y%m%d"):
        try:
            return datetime.strptime(s[: len(datetime.now().strftime(fmt))], fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s[:10]).date()
    except ValueError:
        return None


def para_float(valor) -> float | None:
    if valor in (None, "", "-"):
        return None
    if isinstance(valor, (int, float)):
        return float(valor)
    s = str(valor).strip()
    if "," in s:  # formato brasileiro 1.234,56
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def meses(inicio: date, fim: date):
    """Quebra um intervalo em janelas mensais (várias APIs limitam o período por chamada)."""
    atual = inicio
    while atual <= fim:
        prox = (atual.replace(day=1) + timedelta(days=32)).replace(day=1)
        yield atual, min(prox - timedelta(days=1), fim)
        atual = prox


def como_lista(x):
    if x is None:
        return []
    return x if isinstance(x, list) else [x]


def cavar(d, *chaves, padrao=None):
    for c in chaves:
        if not isinstance(d, dict):
            return padrao
        d = d.get(c)
    return d if d is not None else padrao


def primeiro(d: dict, *chaves):
    for c in chaves:
        if isinstance(d, dict) and d.get(c) not in (None, ""):
            return d[c]
    return None


def achar_lista(d, chaves_obrigatorias=("Codigo",), profundidade=6):
    """Procura recursivamente a primeira lista de dicts que tenha alguma das chaves indicadas.
    Útil para APIs cujo aninhamento muda de versão para versão (Senado)."""
    if profundidade < 0:
        return []
    if isinstance(d, list) and d and isinstance(d[0], dict) and any(
            any(k.lower() == c.lower() for k in d[0]) for c in chaves_obrigatorias):
        return d
    if isinstance(d, dict):
        if any(any(k.lower() == c.lower() for k in d) for c in chaves_obrigatorias) and profundidade < 6:
            return [d]
        for v in d.values():
            achado = achar_lista(v, chaves_obrigatorias, profundidade - 1)
            if achado:
                return achado
    return []


def pegar(d: dict, *chaves):
    """Como `primeiro`, mas sem diferenciar maiúsculas/minúsculas."""
    if not isinstance(d, dict):
        return None
    baixo = {k.lower(): v for k, v in d.items()}
    for c in chaves:
        v = baixo.get(c.lower())
        if v not in (None, ""):
            return v
    return None


_TIPOS_MATERIA = [  # do mais específico para o mais genérico
    ("Proposta de Emenda à Constituição", "PEC"), ("Projeto de Lei Complementar", "PLP"),
    ("Projeto de Lei de Conversão", "PLV"), ("Projeto de Decreto Legislativo", "PDL"),
    ("Projeto de Resolução", "PRC"), ("Medida Provisória", "MPV"), ("Projeto de Lei", "PL"),
]


def extrair_materia(texto: str | None) -> str | None:
    """'...Projeto de Lei Complementar nº 74, de 2026...' -> 'PLP 74/2026'"""
    if not texto:
        return None
    import re
    for nome, sigla in _TIPOS_MATERIA:
        m = re.search(re.escape(nome) + r"\s+n[ºo°.]*\s*([\d.]+)\s*,?\s*de\s+(\d{4})", texto, re.IGNORECASE)
        if m:
            return f"{sigla} {m.group(1).replace('.', '')}/{m.group(2)}"
    return None


def extrair_placar(texto: str | None) -> dict | None:
    """'Sim: 346; Não: 46; Abstenção: 3' -> {'sim': 346, 'nao': 46, 'abstencao': 3}"""
    if not texto:
        return None
    import re
    out = {}
    for chave, padrao in (("sim", r"Sim:?\s*(\d+)"), ("nao", r"N[ãa]o:?\s*(\d+)"),
                          ("abstencao", r"Absten[çc][ãa]o:?\s*(\d+)"), ("obstrucao", r"Obstru[çc][ãa]o:?\s*(\d+)")):
        m = re.search(padrao, texto, re.IGNORECASE)
        if m:
            out[chave] = int(m.group(1))
    return out if "sim" in out else None


def so_digitos(doc) -> str | None:
    """CNPJ/CPF sem pontuação ('07.954.480/0001-79' -> '07954480000179')."""
    if not doc:
        return None
    d = "".join(ch for ch in str(doc) if ch.isdigit())
    return d or None


def formatar_documento(d: str | None) -> str | None:
    if not d:
        return None
    if len(d) == 14:
        return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"
    if len(d) == 11:
        return f"***.{d[3:6]}.{d[6:9]}-**"  # CPF de pessoa física: mostra só o miolo
    return d


# ---------- cache de respostas pesadas (por processo, com validade curta) ----------
import threading as _threading
import time as _time

_MEMO: dict = {}
_MEMO_TRAVA = _threading.Lock()


def memo(chave, fn, ttl: int | None = None):
    """Guarda por `ttl` segundos (settings.cache_segundos) o resultado de `fn()` — consultas agregadas que seriam refeitas a cada visita.
    No máximo 256 respostas guardadas; erro não é guardado."""
    from app.config import settings
    ttl = settings.cache_segundos if ttl is None else min(ttl, settings.cache_segundos)
    if ttl <= 0:
        return fn()
    agora = _time.monotonic()
    with _MEMO_TRAVA:
        hit = _MEMO.get(chave)
        if hit and agora - hit[0] < ttl:
            return hit[1]
    valor = fn()
    with _MEMO_TRAVA:
        if len(_MEMO) >= 256:
            _MEMO.pop(min(_MEMO, key=lambda k: _MEMO[k][0]), None)
        _MEMO[chave] = (agora, valor)
    return valor
