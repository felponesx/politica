"""Justiça em Números (CNJ): casos novos, pendentes, baixados, taxa de congestionamento e magistrados de cada tribunal, por ano.

O CNJ publica um zip na página https://www.cnj.jus.br/pesquisas-judiciarias/justica-em-numeros/ com `JN_<data>.csv` (uma linha por tribunal e ano; colunas em código,
dicionário em `Variáveis - JN.csv`; decimal com vírgula, "nd" = não disponível). Guardamos as medidas gerais (sem os detalhes por grau/fase)."""
import csv
import io
import re
import zipfile

from app import http
from app.collectors.base import registrar_coleta
from app.models import Registro
from app.utils import sem_acento, upsert

PAGINA = "https://www.cnj.jus.br/pesquisas-judiciarias/justica-em-numeros/"
MEDIDAS = {"cn": "Casos novos", "cp": "Casos pendentes", "tbaix": "Processos baixados", "tc": "Taxa de congestionamento (%)",
           "iad": "Baixados por caso novo", "mag": "Magistrados", "k": "Carga de trabalho por magistrado", "ipm": "Produtividade por magistrado",
           "f2": "Magistrados por 100 mil habitantes"}
MINIMO_TRIBUNAIS = 60   # a tabela tem ~90 tribunais por ano (guarda contra arquivo cortado)


def numero(v) -> float | None:
    s = str(v or "").strip().replace(" ", "")
    if not s or s.lower() in ("nd", "na", "-"):
        return None
    try:
        return float(s.replace(".", "").replace(",", ".")) if "," in s and "." in s else float(s.replace(",", "."))
    except ValueError:
        return None


def links_de_zip(html: str) -> list[str]:
    achados = list(dict.fromkeys(re.findall(r'href="([^"]+\.zip)"', html, re.I)))
    achados = [a if a.startswith("http") else "https://www.cnj.jus.br" + a for a in achados if "dea" not in a.lower().rsplit("/", 1)[-1]]
    # mais novos primeiro: o caminho carrega /uploads/AAAA/MM/
    return sorted(achados, key=lambda u: tuple(int(x) for x in (re.findall(r"/uploads/(\d{4})/(\d{2})/", u) or [("0", "0")])[0]), reverse=True)


def ler_jn(texto: str) -> dict:
    """{sigla: {"justica", "anos": {ano: {medida: valor}}}} a partir do CSV JN."""
    leitor = csv.DictReader(io.StringIO(texto), delimiter=";")
    cab = {sem_acento(c).lower().strip(): c for c in (leitor.fieldnames or [])}
    for obrig in ("ano", "sigla", "justica"):
        if obrig not in cab:
            raise ValueError(f"CNJ: coluna '{obrig}' não encontrada ({list(cab)[:6]})")
    saida: dict = {}
    for lin in leitor:
        sigla = (lin.get(cab["sigla"]) or "").strip()
        ano = (lin.get(cab["ano"]) or "").strip()
        if not sigla or not ano.isdigit():
            continue
        t = saida.setdefault(sigla, {"justica": (lin.get(cab["justica"]) or "").strip(), "anos": {}})
        m = {k: numero(lin.get(cab[k])) for k in MEDIDAS if k in cab}
        t["anos"][ano] = {k: v for k, v in m.items() if v is not None}
    return saida


def baixar_jn() -> tuple[str, str]:
    html = http.get(PAGINA, headers={"Accept": "text/html"}).text
    for url in links_de_zip(html):
        z = zipfile.ZipFile(io.BytesIO(http.get(url, headers={"Accept": "*/*"}).content))
        nomes = [n for n in z.namelist() if re.match(r"^JN.*\.csv$", n.rsplit("/", 1)[-1], re.I)]
        if nomes:
            bruto = z.read(nomes[0])
            try:
                return url, bruto.decode("utf-8-sig")
            except UnicodeDecodeError:
                return url, bruto.decode("latin-1")
    raise RuntimeError("CNJ: nenhum zip da página trouxe o arquivo JN_*.csv")


def coletar_cnj_justica():
    with registrar_coleta("cnj", "justica_em_numeros") as (db, n):
        url, texto = baixar_jn()
        dados = ler_jn(texto)
        if len(dados) < MINIMO_TRIBUNAIS:
            raise RuntimeError(f"vieram {len(dados)} tribunais (esperado ao menos {MINIMO_TRIBUNAIS}); nada foi gravado")
        upsert(db, Registro, {"fonte": "cnj", "tipo": "justica_em_numeros", "chave": "BR"},
               {"titulo": "Justiça em Números", "valor": float(len(dados)), "dados": {"tribunais": dados, "medidas": MEDIDAS, "arquivo": url}})
        db.commit()
        n += len(dados)
    return n.itens
