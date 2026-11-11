"""Cadastro de fontes pela tela (sem git). Regras de entrada, antes de qualquer coisa ser gravada.

- nome curto e seguro (vira nome de pasta e de tarefa);
- só https, e nunca endereço interno (localhost, rede local, metadados da nuvem);
- formato de arquivo conhecido (json, csv, xml, zip);
- intervalo entre 5 minutos e 30 dias;
- campo de pessoa (nome, CPF, e-mail, telefone, endereço) só com permissão explícita da fonte.
"""
import ipaddress
import re
from urllib.parse import urlparse

FORMATOS = ("json", "csv", "xml", "zip")
NOME = re.compile(r"^[a-z0-9][a-z0-9_-]{2,63}$")
CAMPO = re.compile(r"^[A-Za-z0-9_.\-]{1,120}$")
TIPO = re.compile(r"^[a-z0-9_:\-]{1,60}$")
PESSOA = re.compile(r"(cpf|nome|e-?mail|telefone|celular|endere[cç]o)", re.I)
INTERVALO = (5, 43200)
CAMPOS_PERMITIDOS = {"tipo", "chave", "valor", "titulo", "uf", "data", "lista", "dados"}


def _interno(host: str) -> bool:
    h = host.lower().strip("[]")
    if h in ("localhost",) or h.endswith((".local", ".internal", ".localhost")):
        return True
    try:
        ip = ipaddress.ip_address(h)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified


def validar_url(url: str) -> str:
    u = urlparse(url)
    if u.scheme != "https" or not u.hostname:
        raise ValueError("o endereço precisa começar com https://")
    if _interno(u.hostname):
        raise ValueError("endereço interno não é permitido")
    return url


def _textos_do_mapa(campos: dict):
    """Todos os caminhos de campo que o mapa usa (inclusive os de `dados`)."""
    for k, v in campos.items():
        if k == "dados" and isinstance(v, dict):
            for nome_extra, caminho in v.items():
                yield nome_extra
                yield caminho
        elif isinstance(v, str):
            yield v


def validar(entrada: dict) -> dict:
    """Devolve a fonte já normalizada, ou levanta ValueError com a mensagem para quem cadastrou."""
    nome = str(entrada.get("nome", "")).strip()
    if not NOME.match(nome):
        raise ValueError("nome: use 3 a 64 caracteres minúsculos, números, - ou _ (ex.: senado-senadores)")
    url = validar_url(str(entrada.get("url", "")).strip())
    formato = str(entrada.get("formato", "")).strip().lower()
    if formato not in FORMATOS:
        raise ValueError(f"formato: use um de {', '.join(FORMATOS)}")
    try:
        intervalo = int(entrada.get("intervalo_min", 1440))
    except (TypeError, ValueError):
        raise ValueError("intervalo_min precisa ser um número de minutos")
    if not INTERVALO[0] <= intervalo <= INTERVALO[1]:
        raise ValueError(f"intervalo_min: entre {INTERVALO[0]} minutos e {INTERVALO[1] // 1440} dias")
    campos = entrada.get("campos")
    if not isinstance(campos, dict):
        raise ValueError("campos: informe o mapa (chave, valor, titulo, uf, data, lista, dados)")
    extra = set(campos) - CAMPOS_PERMITIDOS
    if extra:
        raise ValueError(f"campos desconhecidos: {', '.join(sorted(extra))}")
    if not campos.get("chave"):
        raise ValueError("campos.chave é obrigatório (o campo que identifica cada linha)")
    tipo = str(campos.get("tipo") or nome.replace("-", "_"))
    if not TIPO.match(tipo):
        raise ValueError("campos.tipo: use letras minúsculas, números, _ : -")
    campos = {**campos, "tipo": tipo}
    for caminho in _textos_do_mapa(campos):
        if not CAMPO.match(str(caminho)):
            raise ValueError(f"caminho de campo inválido: {caminho!r}")
    permitir = bool(entrada.get("permitir_pessoas", False))
    if not permitir:
        for caminho in _textos_do_mapa(campos):
            if PESSOA.search(str(caminho)):
                raise ValueError(f"o campo {caminho!r} parece dado de pessoa: marque 'permitir pessoas' para esta fonte")
    return {"nome": nome, "produto": str(entrada.get("produto") or "BRASIL+")[:60], "url": url,
            "intervalo_min": intervalo, "formato": formato, "campos": campos, "permitir_pessoas": permitir}


def para_coletor(fonte) -> dict:
    """Forma que o coletor do PC entende (mesmo formato de um [[fonte]] do vínculo TOML)."""
    campos = fonte.campos or {}
    return {"nome": fonte.nome, "url": fonte.url, "intervalo_min": fonte.intervalo_min,
            "publicar_dados": True, "adaptador": "linhas", "mapa": campos,
            "headers": {"Accept": "application/json"},
            "esperado": f"Lista de registros da fonte {fonte.nome} em {fonte.formato}, mapeada pelos campos cadastrados."}
