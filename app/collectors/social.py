"""Bolsa Família, BPC e viagens a serviço do governo federal (Portal da Transparência, sem chave).

Arquivos mensais/anuais em https://portaldatransparencia.gov.br/download-de-dados/{novo-bolsa-familia|bpc}/AAAAMM e /viagens/AAAA (zip com CSV ';').
Guardamos só somas por estado, município e órgão. Nome, CPF e NIS de beneficiários e viajantes NÃO são guardados.
Bolsa Família e BPC: contam-se só as parcelas do próprio mês (referência = competência); o que vem de meses atrasados soma à parte (`retroativo`)."""
import csv
import io
import logging
import re
import tempfile
import zipfile
from datetime import date
from pathlib import Path

from app import http
from app.collectors.base import registrar_coleta
from app.models import Registro
from app.utils import UFS, sem_acento, upsert

log = logging.getLogger("brasilplus.social")
URL = "https://portaldatransparencia.gov.br/download-de-dados/{base}/{periodo}"
UA = {"Accept": "*/*", "User-Agent": "Mozilla/5.0 (BRASIL+ coletor de dados publicos)"}
MINIMO = {"novo-bolsa-familia": 5_000_000, "bpc": 3_000_000}   # linhas esperadas (guarda contra arquivo cortado)
ORGAOS = 40


def valor(v) -> float:
    try:
        return float(str(v).replace(".", "").replace(",", ".")) if str(v or "").strip() else 0.0
    except ValueError:
        return 0.0


def _col(cab, *padroes):
    norm = [re.sub(r"\s+", " ", sem_acento(c).lower()).strip() for c in cab]
    for p in padroes:
        for i, h in enumerate(norm):
            if re.search(p, h):
                return i
    return None


def baixar_zip(base: str, periodos: list[str]) -> tuple[str, Path]:
    """Baixa o primeiro período publicado da lista; 403/404 = ainda não saiu."""
    for per in periodos:
        destino = Path(tempfile.mkdtemp(prefix="social-")) / f"{base}-{per}.zip"
        try:
            http.baixar(URL.format(base=base, periodo=per), str(destino))
            return per, destino
        except Exception as e:  # noqa: BLE001
            resp = getattr(e, "response", None)
            if resp is not None and resp.status_code in (403, 404):
                continue
            raise
    raise RuntimeError(f"Portal da Transparência: nenhum arquivo de {base} em {periodos}")


def linhas_csv(caminho: Path, sufixo: str = ""):
    """(cabeçalho, iterador de linhas) do primeiro CSV do zip cujo nome termina em `sufixo`."""
    z = zipfile.ZipFile(caminho)
    nome = next(n for n in z.namelist() if n.lower().endswith(".csv") and n.lower().endswith(sufixo.lower() + ".csv" if sufixo else ".csv"))
    bruto = z.open(nome)
    inicio = bruto.read(4096)
    bruto.close()
    try:
        inicio.decode("utf-8")
        enc = "utf-8-sig"
    except UnicodeDecodeError:
        enc = "latin-1"
    leitor = csv.reader(io.TextIOWrapper(z.open(nome), encoding=enc, newline=""), delimiter=";")
    return next(leitor), leitor


def agregar_beneficios(cab, linhas, competencia_unica: bool = True) -> dict:
    """{UF: {n, valor, retroativo, municipios: {codigo: {nome, n, valor}}}} das parcelas do mês de competência."""
    i = {"comp": _col(cab, r"^mes competencia"), "ref": _col(cab, r"^mes referencia"), "uf": _col(cab, r"^uf$"), "cod": _col(cab, r"^codigo municipio"),
         "mun": _col(cab, r"^nome municipio"), "valor": _col(cab, r"^valor parcela")}
    faltam = [k for k, v in i.items() if v is None]
    if faltam:
        raise ValueError(f"Arquivo mudou: faltam {faltam} em {cab[:6]}")
    out: dict[str, dict] = {}
    total = 0
    for l in linhas:
        if len(l) <= max(i.values()):
            continue
        total += 1
        uf = l[i["uf"]].strip()
        if uf not in UFS:
            continue
        e = out.setdefault(uf, {"n": 0, "valor": 0.0, "retroativo": 0.0, "municipios": {}})
        v = valor(l[i["valor"]])
        if l[i["ref"]].strip() != l[i["comp"]].strip():
            e["retroativo"] += v
            continue
        e["n"] += 1
        e["valor"] += v
        m = e["municipios"].setdefault(l[i["cod"]].strip(), {"nome": l[i["mun"]].strip(), "n": 0, "valor": 0.0})
        m["n"] += 1
        m["valor"] += v
    out["_linhas"] = total
    return out


def _guardar(db, tipo: str, mes: str, base: str, ag: dict, minimo: int):
    total = ag.pop("_linhas")
    if total < minimo:
        raise RuntimeError(f"{base}: só {total:,} linhas (esperado ≥ {minimo:,}); nada foi gravado")
    if len(ag) < 27:
        raise RuntimeError(f"{base}: vieram {len(ag)} estados (esperado 27); nada foi gravado")
    for uf, e in ag.items():
        mun = sorted(({"codigo": c, **m, "valor": round(m["valor"], 2)} for c, m in e["municipios"].items()), key=lambda x: -x["n"])
        dados = {"mes": mes, "n": e["n"], "valor": round(e["valor"], 2), "retroativo": round(e["retroativo"], 2), "municipios": mun}
        upsert(db, Registro, {"fonte": "transparencia", "tipo": tipo, "chave": uf}, {"uf": uf, "titulo": f"{base} {uf}", "valor": dados["valor"], "dados": dados})


def coletar_social():
    """Bolsa Família e BPC por estado e município, no último mês publicado."""
    with registrar_coleta("transparencia", "social") as (db, n):
        hoje = date.today()
        periodos = []
        a, m = hoje.year, hoje.month
        for _ in range(6):
            periodos.append(f"{a}{m:02d}")
            m -= 1
            if m == 0:
                a, m = a - 1, 12
        for base, tipo in (("novo-bolsa-familia", "bolsa_familia_uf"), ("bpc", "bpc_uf")):
            try:
                mes, arq = baixar_zip(base, periodos)
                cab, linhas = linhas_csv(arq)
                ag = agregar_beneficios(cab, linhas)
                _guardar(db, tipo, mes, base, ag, MINIMO[base])
                db.commit()
                n += len(ag)
                arq.unlink(missing_ok=True)
            except Exception as e:  # noqa: BLE001 - um programa que falha não derruba o outro
                n.avisos.append(f"{base}: {type(e).__name__}: {str(e)[:150]}")
                log.warning("social %s: %s", base, e)
        if not n.itens:
            raise RuntimeError("; ".join(n.avisos) or "nenhum programa foi lido")
    return n.itens


def agregar_viagens(cab, linhas) -> dict:
    i = {"orgao": _col(cab, r"^nome do orgao superior"), "sit": _col(cab, r"^situacao"), "diarias": _col(cab, r"^valor diarias"),
         "passagens": _col(cab, r"^valor passagens"), "devolucao": _col(cab, r"^valor devolucao"), "outros": _col(cab, r"^valor outros")}
    faltam = [k for k, v in i.items() if v is None]
    if faltam:
        raise ValueError(f"Arquivo de viagens mudou: faltam {faltam} em {cab[:8]}")
    orgaos: dict[str, dict] = {}
    n = 0
    for l in linhas:
        if len(l) <= max(i.values()):
            continue
        n += 1
        o = orgaos.setdefault(l[i["orgao"]].strip() or "Sem órgão", {"viagens": 0, "diarias": 0.0, "passagens": 0.0, "outros": 0.0, "devolucao": 0.0})
        o["viagens"] += 1
        o["diarias"] += valor(l[i["diarias"]])
        o["passagens"] += valor(l[i["passagens"]])
        o["outros"] += valor(l[i["outros"]])
        o["devolucao"] += valor(l[i["devolucao"]])
    lista = []
    for nome, o in orgaos.items():
        gasto = o["diarias"] + o["passagens"] + o["outros"] - o["devolucao"]
        lista.append({"orgao": nome, "viagens": o["viagens"], "diarias": round(o["diarias"], 2), "passagens": round(o["passagens"], 2),
                      "outros": round(o["outros"], 2), "devolucao": round(o["devolucao"], 2), "gasto": round(gasto, 2)})
    lista.sort(key=lambda x: -x["gasto"])
    tot = {k: round(sum(x[k] for x in lista), 2) for k in ("diarias", "passagens", "outros", "devolucao", "gasto")}
    return {"viagens": n, **tot, "orgaos": lista[:ORGAOS], "n_orgaos": len(lista)}


def coletar_viagens(anos: int = 3):
    """Viagens a serviço (diárias e passagens) por órgão superior, nos últimos anos."""
    with registrar_coleta("transparencia", "viagens") as (db, n):
        for ano in range(date.today().year, date.today().year - int(anos), -1):
            try:
                _, arq = baixar_zip("viagens", [str(ano)])
                cab, linhas = linhas_csv(arq, "_Viagem")
                d = agregar_viagens(cab, linhas)
                if d["viagens"] < 100_000:
                    raise RuntimeError(f"viagens {ano}: só {d['viagens']:,} viagens; nada foi gravado")
                upsert(db, Registro, {"fonte": "transparencia", "tipo": "viagens_ano", "chave": str(ano)},
                       {"ano": ano, "titulo": f"Viagens a serviço {ano}", "valor": d["gasto"], "dados": {**d, "ano": ano}})
                db.commit()
                n += 1
                arq.unlink(missing_ok=True)
            except Exception as e:  # noqa: BLE001
                n.avisos.append(f"{ano}: {type(e).__name__}: {str(e)[:150]}")
        if not n.itens:
            raise RuntimeError("; ".join(n.avisos) or "nenhum ano de viagens foi lido")
    return n.itens
