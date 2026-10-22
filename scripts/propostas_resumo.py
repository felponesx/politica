"""Resumo das propostas de governo registradas no TSE (presidente, governador e prefeito das capitais).

  python -m scripts.propostas_resumo [site/midia] [site/dados] [ano ...]

Fonte: dados abertos do TSE, "Proposta de governo" (cdn.tse.jus.br/estatistica/sead/odsele/proposta_governo/proposta_governo_<ano>_<UF>.zip, um PDF por
candidato, `<ano><UF><sq>.pdf`). O texto de cada PDF sai pelo `pdftotext`; para cada tema (segurança, transporte, economia, saúde, educação...) ficam até
3 trechos do próprio documento, escolhidos por palavras-chave e verbos de ação ("vamos implantar", "ampliar"...). É um resumo por trechos, sem interpretar nem
conferir nada. PDF sem texto (digitalizado) fica marcado como ilegível. Grava `site/midia/propostas.json`: {sq: {ano, uf, paginas, temas, legivel}}.
Prefeitos: só os das capitais (zips grandes, lidos por pedido Range, só os bytes de cada PDF).
"""
import io
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

log = logging.getLogger("brasilplus.propostas")
BASE = "https://cdn.tse.jus.br/estatistica/sead/odsele/proposta_governo/proposta_governo_{ano}_{uf}.zip"
UFS = ["AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG", "MS", "MT", "PA", "PB", "PE", "PI", "PR", "RJ", "RN", "RO", "RR", "RS", "SC", "SE", "SP", "TO"]

# tema: (rótulo, palavras-chave em minúsculas e sem acento)
TEMAS = {
    "seguranca": ("Segurança", ["seguranca publica", "policia", "policiamento", "violencia", "criminalidade", "crime$", "presidio", "sistema prisional", "guarda municipal", "homicidio", "faccao"]),
    "transporte": ("Transporte e mobilidade", ["transporte", "mobilidade", "onibus", "metro$", "trem$", "rodovia", "estrada", "ciclovia", "transito", "aeroporto", "porto", "pavimenta", "ferrovia", "logistica", "ponte$"]),
    "economia": ("Economia e emprego", ["economia", "economico", "emprego", "renda", "empreend", "investimento", "industria", "crescimento", "inflacao", "tributari", "imposto", "fiscal", "agronegocio", "comercio", "turismo", "microempresa", "pib$", "competitividade"]),
    "saude": ("Saúde", ["saude", "hospital", "sus$", "medico", "atencao basica", "vacina", "upa$", "ubs$", "medicamento"]),
    "educacao": ("Educação", ["educacao", "escola", "ensino", "professor", "creche", "alfabetizacao", "universidade", "estudante", "tempo integral"]),
    "social": ("Assistência e moradia", ["assistencia social", "moradia", "habitacao", "saneamento", "fome", "pobreza", "bolsa", "vulnerabilidade", "programa social", "esgoto", "agua$"]),
    "ambiente": ("Meio ambiente", ["meio ambiente", "ambiental", "sustentabilidade", "clima$", "floresta", "desmatamento", "residuos", "energia limpa", "renovavel"]),
}
VERBOS = ["vamos", "implant", "ampli", "cri", "constru", "garant", "reduz", "invest", "fortalec", "promov", "modern", "reforma", "oferec", "expand", "combat", "priorizar", "instituir", "universaliz", "zerar"]


def _tem(n: str, kw: str) -> bool:
    """palavra-chave no começo de uma palavra do texto sem acento; com `$` no fim, a palavra inteira."""
    return re.search(r"\b" + re.escape(kw[:-1]) + r"\b", n) is not None if kw.endswith("$") else re.search(r"\b" + re.escape(kw), n) is not None


def _sem_acento(t: str) -> str:
    import unicodedata
    return unicodedata.normalize("NFD", t).encode("ascii", "ignore").decode().lower()


def texto_pdf(pdf: bytes) -> tuple[str, int]:
    """(texto, páginas) de um PDF; vazio quando é digitalizado."""
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "a.pdf")
        Path(p).write_bytes(pdf)
        try:
            txt = subprocess.run(["pdftotext", "-enc", "UTF-8", "-nopgbrk", p, "-"], capture_output=True, timeout=120).stdout.decode("utf-8", "ignore")
            info = subprocess.run(["pdfinfo", p], capture_output=True, timeout=30).stdout.decode("utf-8", "ignore")
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return "", 0
    m = re.search(r"Pages:\s+(\d+)", info)
    return txt, int(m.group(1)) if m else 0


def frases(texto: str) -> list[str]:
    t = re.sub(r"-\n(?=[a-zà-ú])", "", texto)  # palavra partida no fim da linha
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n(?=[a-zà-ú(])", " ", t)  # quebra no meio da frase
    out = []
    for bloco in re.split(r"\n\s*\n|(?<=[.!?;])\s+(?=[A-ZÀ-Ú•\-–▶►■●])|\s*[▶►■●▪•]\s*|\n\s*[\-–]\s*", t):
        b = re.sub(r"\s+", " ", bloco).strip(" •-–●▪\t")
        if 55 <= len(b) <= 420 and not re.fullmatch(r"[\d\W]+", b) and sum(c.isalpha() for c in b) > 0.6 * len(b) and not re.search(r"\d\)\s.*\d\)\s", b) and sum(c.isupper() for c in b) < 0.5 * sum(c.isalpha() for c in b):
            out.append(b)
    return out


def resumir(texto: str, por_tema: int = 3) -> dict:
    fs = frases(texto)
    achados = {}
    usadas = set()
    for k, (rot, kws) in TEMAS.items():
        pont = []
        for f in fs:
            n = _sem_acento(f)
            hits = sum(1 for w in kws if _tem(n, w))
            if not hits:
                continue
            # frase que lista quase todos os assuntos de uma vez ("saúde, educação, segurança...") não resume nenhum
            gerais = sum(1 for _, (_, ws) in TEMAS.items() if any(_tem(n, w) for w in ws))
            v = sum(1 for w in VERBOS if w in n)
            comp = len(f)
            ideal = 0 if 90 <= comp <= 260 else -1
            pont.append((hits * 2 + min(v, 2) + ideal - 3 * max(0, gerais - 2), -comp, f))
        pont.sort(reverse=True)
        sel = []
        for _, _, f in pont:
            chave = _sem_acento(f)[:60]
            if chave in usadas:
                continue
            usadas.add(chave)
            sel.append(f if len(f) <= 260 else f[:257].rsplit(" ", 1)[0] + "…")
            if len(sel) >= por_tema:
                break
        if sel:
            achados[k] = sel
    return achados


def processar_zip(ano: int, uf: str, so_sq: set | None = None) -> dict:
    """{sq: resumo} de todos os PDFs do zip de (ano, uf); com `so_sq`, só desses candidatos (zips grandes, por Range)."""
    from app.collectors.bcb_scr import entradas_zip
    from scripts.midia_site import _foto_do_zip
    url = BASE.format(ano=ano, uf=uf)
    out = {}
    try:
        if so_sq is None:
            import httpx
            r = httpx.get(url, timeout=300, follow_redirects=True)
            if r.status_code != 200:
                return {}
            z = zipfile.ZipFile(io.BytesIO(r.content))
            itens = [(n, z.read(n)) for n in z.namelist() if re.search(r"\d{10,13}(?:_\d+)?\.pdf$", n)]
        else:
            _, entradas = entradas_zip(url)
            itens = []
            for nome, comp, metodo, off in entradas:
                m = re.search(r"(\d{10,13})(?:_\d+)?\.pdf$", nome)
                if m and m.group(1) in so_sq:
                    b = _foto_do_zip(url, len(nome), comp, metodo, off)
                    if b:
                        itens.append((nome, b))
    except Exception as e:  # noqa: BLE001 - um estado fora do ar não derruba os outros
        log.warning("propostas %s %s: %s", ano, uf, e)
        return {}
    for nome, pdf in itens:
        sq = re.search(r"(\d{10,13})(?:_\d+)?\.pdf$", nome).group(1)
        txt, pag = texto_pdf(pdf)
        legivel = len(txt.strip()) >= 800
        out[sq] = {"ano": ano, "uf": uf, "paginas": pag, "legivel": legivel, "temas": resumir(txt) if legivel else {}}
    return out


def capitais_2024(dados: str) -> dict[str, set]:
    """{UF: {sq}} dos prefeitos eleitos das capitais, pela cópia dos dados."""
    from scripts.revisar_dados import Copia
    caps = {"AC": "RIO BRANCO", "AL": "MACEIO", "AM": "MANAUS", "AP": "MACAPA", "BA": "SALVADOR", "CE": "FORTALEZA", "ES": "VITORIA", "GO": "GOIANIA", "MA": "SAO LUIS", "MG": "BELO HORIZONTE",
            "MS": "CAMPO GRANDE", "MT": "CUIABA", "PA": "BELEM", "PB": "JOAO PESSOA", "PE": "RECIFE", "PI": "TERESINA", "PR": "CURITIBA", "RJ": "RIO DE JANEIRO", "RN": "NATAL", "RO": "PORTO VELHO",
            "RR": "BOA VISTA", "RS": "PORTO ALEGRE", "SC": "FLORIANOPOLIS", "SE": "ARACAJU", "SP": "SAO PAULO", "TO": "PALMAS"}
    out: dict[str, set] = {}
    for x in (Copia(Path(dados)).get("/candidatos?cargo=PREFEITO&eleitos=true") or {}).get("itens") or []:
        if x.get("uf") in caps and _sem_acento(x.get("unidade") or "").upper() == caps[x["uf"]] and x.get("sq_candidato"):
            out.setdefault(x["uf"], set()).add(str(x["sq_candidato"]))
    return out


def main(argv):
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    pasta = argv[0] if argv else "site/midia"
    dados = argv[1] if len(argv) > 1 else "site/dados"
    anos = [int(a) for a in argv[2:]] or [2022, 2026]
    arq = os.path.join(pasta, "propostas.json")
    try:
        todos = json.load(open(arq, encoding="utf-8"))
    except (OSError, ValueError):
        todos = {}
    for ano in anos:
        for uf in ["BR"] + UFS:
            novos = processar_zip(ano, uf)
            todos.update(novos)
            log.info("propostas %s %s: %d candidatos", ano, uf, len(novos))
            _gravar(arq, todos)
    if 2024 in anos or not argv[2:]:
        for uf, sqs in sorted(capitais_2024(dados).items()):
            novos = processar_zip(2024, uf, sqs)
            todos.update(novos)
            log.info("propostas 2024 %s (capital): %d", uf, len(novos))
            _gravar(arq, todos)
    log.info("propostas: %d candidatos, %d com texto", len(todos), sum(1 for v in todos.values() if v["legivel"]))


def _gravar(arq: str, todos: dict):
    with open(arq, "w", encoding="utf-8") as f:
        json.dump(todos, f, ensure_ascii=False, separators=(",", ":"))


if __name__ == "__main__":
    main(sys.argv[1:])
