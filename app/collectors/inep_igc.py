"""IGC (Índice Geral de Cursos) das instituições de educação superior, do INEP (dados abertos).

A página de dados abertos lista uma aba por ano (`.../indicadores-de-qualidade-da-educacao-superior/<ano>`); cada aba traz os links dos arquivos
(`.../resultados/<ano>/IGC_<ano>.xlsx`). O descobridor lê as abas, acha o IGC de cada ano e baixa pelo cliente do INEP (cadeia de certificados
completada pelo AIA conferido por impressão digital; o TLS continua ligado). Guardamos a nota (contínua e faixa) por instituição, sem inventar
nota que não veio. O IGC não traz município; o município só viria do Censo da Educação Superior (microdados), que não é baixado aqui."""
import html
import logging
import re
from datetime import date

from app.collectors import inep
from app.collectors.base import registrar_coleta
from app.models import Registro
from app.utils import UFS, upsert

log = logging.getLogger("brasilplus.igc")
PAGINA = "https://www.gov.br/inep/pt-br/acesso-a-informacao/dados-abertos/indicadores-educacionais/indicadores-de-qualidade-da-educacao-superior"
MINIMO_IES = 1_500
AVISO = ("IGC é a nota de qualidade da INSTITUIÇÃO de ensino superior (média dos conceitos dos cursos avaliados no triênio, com pós-graduação), de 1 a 5 em faixas. "
         "Instituição sem avaliação aparece sem nota (SC = sem conceito); nenhuma nota é estimada. É um indicador do MEC/INEP e não mede a qualidade de cada curso. O arquivo não traz município.")


def abas(texto_html: str) -> list[int]:
    return sorted({int(a) for a in re.findall(r'data-id="(\d{4})"', texto_html)}, reverse=True)


def link_igc(texto_html: str, ano: int) -> str | None:
    for u in re.findall(r'href="(https://download\.inep\.gov\.br/[^"]+\.xlsx)"', html.unescape(texto_html)):
        if re.search(rf"igc_{ano}\.xlsx$", u, re.I):
            return u
    return None


def _num(v):
    try:
        return float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        return None


def ler(caminho, ano: int) -> list[dict]:
    wb = inep.abrir_xlsx(caminho)
    nome = next((n for n in wb.sheetnames if n.strip().upper().startswith("IGC")), None)
    if nome is None:
        raise ValueError(f"IGC {ano}: aba 'IGC' não encontrada em {wb.sheetnames}")
    linhas = wb[nome].iter_rows(values_only=True)
    cab = [re.sub(r"\s+", " ", str(c or "")).strip().lower() for c in next(linhas)]

    def col(*partes):
        for i, c in enumerate(cab):
            if all(p in c for p in partes):
                return i
        raise ValueError(f"IGC {ano}: coluna {partes} não encontrada em {cab}")
    i = {"cod": col("código da ies"), "nome": col("nome da ies"), "sigla": col("sigla da ies"), "org": col("organização"), "cat": col("categoria"),
         "uf": col("sigla da uf"), "cursos": col("cursos com cpc"), "igc": col("igc (contínuo)"), "faixa": col("igc (faixa)")}
    out = []
    for l in linhas:
        if not l or l[i["cod"]] in (None, ""):
            continue
        igc = _num(l[i["igc"]])
        faixa = str(l[i["faixa"]]).strip() if l[i["faixa"]] not in (None, "") else None
        out.append({"codigo": int(l[i["cod"]]), "nome": str(l[i["nome"]]).strip(), "sigla": (str(l[i["sigla"]]).strip() if l[i["sigla"]] else None),
                    "organizacao": l[i["org"]], "categoria": l[i["cat"]], "uf": str(l[i["uf"]] or "").strip(), "cursos_cpc": l[i["cursos"]],
                    "igc": round(igc, 3) if igc is not None else None, "faixa": faixa})
    return out


def resumir(ies: list[dict], ano: int) -> dict:
    com = [x for x in ies if x["igc"] is not None]
    por_uf: dict[str, list[float]] = {}
    por_cat: dict[str, list[float]] = {}
    for x in com:
        por_uf.setdefault(x["uf"], []).append(x["igc"])
        por_cat.setdefault(str(x["categoria"]), []).append(x["igc"])
    med = lambda v: {"instituicoes": len(v), "igc_medio": round(sum(v) / len(v), 3)}  # noqa: E731
    faixas: dict[str, int] = {}
    for x in ies:
        faixas[x["faixa"] or "sem faixa"] = faixas.get(x["faixa"] or "sem faixa", 0) + 1
    return {"ano": ano, "instituicoes": len(ies), "com_nota": len(com), "sem_nota": len(ies) - len(com), "faixas": faixas,
            "por_uf": {u: med(v) for u, v in por_uf.items() if u in UFS}, "por_categoria": {c: med(v) for c, v in por_cat.items()},
            "melhores": sorted(com, key=lambda x: -x["igc"])[:50], "lista": sorted(ies, key=lambda x: x["nome"]), "aviso": AVISO}


def coletar_inep_igc(edicoes: int = 2):
    """IGC das `edicoes` mais recentes publicadas (anos fechados já gravados não são baixados de novo)."""
    with registrar_coleta("inep", "igc") as (db, n):
        pagina = inep._tentar(lambda: inep.cliente().get(PAGINA)).text
        anos = abas(pagina)
        if not anos:
            raise RuntimeError("INEP: nenhuma aba de ano na página de indicadores (a página mudou?)")
        feitas = 0
        for ano in anos:
            if feitas >= int(edicoes):
                break
            aba = inep._tentar(lambda: inep.cliente().get(f"{PAGINA}/{ano}")).text
            url = link_igc(aba, ano)
            if not url:
                continue   # nem todo ano tem IGC
            feitas += 1
            if db.query(Registro).filter_by(fonte="inep", tipo="igc_edicao", chave=str(ano)).first():
                continue
            try:
                destino = inep.baixar_url(url)
                ies = ler(destino, ano)
                destino.unlink(missing_ok=True)
                if len(ies) < MINIMO_IES:
                    raise RuntimeError(f"IGC {ano}: só {len(ies)} instituições (esperado ≥ {MINIMO_IES}); nada foi gravado")
                d = resumir(ies, ano)
                d["fonte_url"] = url
                upsert(db, Registro, {"fonte": "inep", "tipo": "igc_edicao", "chave": str(ano)},
                       {"ano": ano, "titulo": f"IGC {ano}", "valor": float(len(ies)), "dados": d})
                db.commit()
                n += 1
            except Exception as e:  # noqa: BLE001
                n.avisos.append(f"{ano}: {type(e).__name__}: {str(e)[:150]}")
        if not feitas:
            raise RuntimeError("INEP: nenhum arquivo de IGC achado nas abas")
        if not n.itens and n.avisos:
            raise RuntimeError("; ".join(n.avisos))
    return n.itens
