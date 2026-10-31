"""Onde cada instituição de ensino superior oferece cursos (Censo da Educação Superior, INEP) — base para ligar o IGC a municípios SEM inventar nota municipal.

O IGC (`inep-igc`) é a nota da INSTITUIÇÃO. Uma instituição pode ter sede num município e cursos em vários. Este coletor lê, por pedidos Range dentro do zip dos microdados
(`download.inep.gov.br/microdados/microdados_censo_da_educacao_superior_AAAA.zip`, cadeia TLS do INEP completada como no IDEB), só dois arquivos:
- `MICRODADOS_ED_SUP_IES_AAAA.CSV` (~1 MB): código, nome, sigla, município e UF da SEDE;
- `MICRODADOS_CADASTRO_CURSOS_AAAA.CSV` (~450 MB compactado): uma linha por curso e município de oferta → por instituição e município: nº de cursos, vagas e matrículas.
Cursos a distância sem polo não trazem município e ficam de fora (a contagem é informada). Nada de microdado de aluno ou docente é lido."""
import csv
import logging
import re
from datetime import date

import httpx

from app.collectors import inep
from app.collectors.base import registrar_coleta
from app.collectors.bcb_scr import entradas_zip, linhas_entrada
from app.models import IesMunicipio
from app.utils import upsert

log = logging.getLogger("brasilplus.censo_ies")
PAGINA = "https://www.gov.br/inep/pt-br/acesso-a-informacao/dados-abertos/microdados/censo-da-educacao-superior"
ZIP = "https://download.inep.gov.br/microdados/microdados_censo_da_educacao_superior_{ano}.zip"
MINIMO_IES = 1_500
MINIMO_PARES = 8_000


def anos_publicados(html: str) -> list[int]:
    return sorted({int(a) for a in re.findall(r"microdados_censo_da_educacao_superior_(\d{4})\.zip", html)}, reverse=True)


def _i(cab: list[str], *nomes: str) -> list[int]:
    try:
        return [cab.index(n) for n in nomes]
    except ValueError as e:
        raise ValueError(f"Arquivo do Censo mudou: coluna não achada ({e}); cabeçalho {cab[:8]}") from None


def ler_ies(linhas) -> dict[int, dict]:
    leitor = csv.reader(linhas, delimiter=";")
    cab = [c.strip() for c in next(leitor)]
    i_ies, i_nome, i_sigla, i_mun, i_nmun, i_uf = _i(cab, "CO_IES", "NO_IES", "SG_IES", "CO_MUNICIPIO_IES", "NO_MUNICIPIO_IES", "SG_UF_IES")
    out = {}
    for l in leitor:
        if len(l) <= max(i_ies, i_nome, i_sigla, i_mun, i_nmun, i_uf):
            continue
        try:
            out[int(l[i_ies])] = {"nome": l[i_nome].strip()[:200], "sigla": l[i_sigla].strip()[:40] or None, "mun": l[i_mun].strip(), "nmun": l[i_nmun].strip(), "uf": l[i_uf].strip()}
        except ValueError:
            continue
    return out


def agregar_cursos(linhas) -> tuple[dict, dict]:
    """({(co_ies, cod_municipio): {...}}, {"linhas": n, "sem_municipio": n})"""
    leitor = csv.reader(linhas, delimiter=";")
    cab = [c.strip() for c in next(leitor)]
    i_ies, i_mun, i_nmun, i_uf, i_vg, i_mat = _i(cab, "CO_IES", "CO_MUNICIPIO", "NO_MUNICIPIO", "SG_UF", "QT_VG_TOTAL", "QT_MAT")
    maximo = max(i_ies, i_mun, i_nmun, i_uf, i_vg, i_mat)
    pares: dict[tuple[int, str], dict] = {}
    n = sem = 0
    for l in leitor:
        if len(l) <= maximo:
            continue
        n += 1
        mun = l[i_mun].strip()
        if not mun:
            sem += 1
            continue
        try:
            ies = int(l[i_ies])
        except ValueError:
            continue
        e = pares.setdefault((ies, mun), {"n": 0, "vagas": 0, "mat": 0, "nmun": l[i_nmun].strip(), "uf": l[i_uf].strip()})
        e["n"] += 1
        e["vagas"] += int(l[i_vg] or 0) if (l[i_vg] or "").isdigit() else 0
        e["mat"] += int(l[i_mat] or 0) if (l[i_mat] or "").isdigit() else 0
    return pares, {"linhas": n, "sem_municipio": sem}


def coletar_inep_censo_ies(ano: int = 0):
    """Instituição × município do Censo da Educação Superior mais recente (ou do `ano` pedido). Reprocessar atualiza pela chave (ano, instituição, município)."""
    with registrar_coleta("inep", "censo_ies", ano=ano or "auto") as (db, n):
        cli = inep.cliente()
        if ano:
            anos = [int(ano)]
        else:
            anos = anos_publicados(inep._tentar(lambda: cli.get(PAGINA)).text)[:2] or [date.today().year - 2]
        escolhido = erro = None
        for a in anos:
            try:
                tam, entradas = entradas_zip(ZIP.format(ano=a), cli)
                f_ies = next((e for e in entradas if e[0].upper().endswith(f"MICRODADOS_ED_SUP_IES_{a}.CSV")), None)
                f_cur = next((e for e in entradas if e[0].upper().endswith(f"MICRODADOS_CADASTRO_CURSOS_{a}.CSV")), None)
                if f_ies and f_cur:
                    escolhido = (a, f_ies, f_cur)
                    break
                erro = f"{a}: arquivos IES/CURSOS não estão no zip"
            except (httpx.HTTPError, RuntimeError) as e:
                erro = f"{a}: {type(e).__name__}"
        if not escolhido:
            raise RuntimeError(f"Censo da Educação Superior indisponível ({erro})")
        a, f_ies, f_cur = escolhido
        url = ZIP.format(ano=a)
        ies = ler_ies(linhas_entrada(url, f_ies[1], f_ies[2], f_ies[3], cli, "latin-1"))
        if len(ies) < MINIMO_IES:
            raise RuntimeError(f"Censo {a}: só {len(ies)} instituições (esperado ≥ {MINIMO_IES}); nada foi gravado")
        pares, cont = agregar_cursos(linhas_entrada(url, f_cur[1], f_cur[2], f_cur[3], cli, "latin-1"))
        if len(pares) < MINIMO_PARES:
            raise RuntimeError(f"Censo {a}: só {len(pares)} pares instituição×município (esperado ≥ {MINIMO_PARES}); nada foi gravado")
        for (co, mun), e in pares.items():
            ref = ies.get(co, {})
            upsert(db, IesMunicipio, {"ano_censo": a, "co_ies": co, "cod_municipio": mun},
                   {"nome": ref.get("nome"), "sigla": ref.get("sigla"), "municipio": e["nmun"], "uf": e["uf"], "sede": ref.get("mun") == mun, "n_cursos": e["n"], "vagas": e["vagas"], "matriculas": e["mat"]})
            n += 1
            if n.itens % 5000 == 0:
                db.commit()
        # sede sem curso presencial no próprio município: registra a sede com zero cursos, para a instituição aparecer onde fica o endereço
        for co, ref in ies.items():
            if ref["mun"] and (co, ref["mun"]) not in pares:
                upsert(db, IesMunicipio, {"ano_censo": a, "co_ies": co, "cod_municipio": ref["mun"]},
                       {"nome": ref["nome"], "sigla": ref["sigla"], "municipio": ref["nmun"], "uf": ref["uf"], "sede": True, "n_cursos": 0, "vagas": 0, "matriculas": 0})
                n += 1
        db.commit()
        if cont["sem_municipio"]:
            n.avisos.append(f"{cont['sem_municipio']:,} de {cont['linhas']:,} ofertas de curso sem município (a distância, sem polo) ficaram de fora")
    return n.itens
