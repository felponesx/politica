"""Servidores federais civis (SIAPE) e remuneração por órgão, do Portal da Transparência (sem chave).

Arquivo mensal `download-de-dados/servidores/AAAAMM_Servidores_SIAPE` (o endereço `servidores/AAAAMM` sem o sufixo devolve 403): zip com
`_Cadastro.csv` (lotação, órgão, UF) e `_Remuneracao.csv`, ligados por `Id_SERVIDOR_PORTAL`. Só somas por órgão e estado são guardadas:
nome, CPF e matrícula NÃO. Contar remuneração acima do teto não classifica nada como ilegal (há parcelas legais fora do teto)."""
import csv
import io
import logging
import tempfile
import zipfile
from datetime import date
from pathlib import Path

from app import http
from app.collectors.base import registrar_coleta
from app.models import Registro
from app.utils import UFS, upsert

log = logging.getLogger("brasilplus.servidores")
URL = "https://portaldatransparencia.gov.br/download-de-dados/servidores/{periodo}_Servidores_SIAPE"
# Teto de referência: subsídio mensal de ministro do STF (R$ 46.366,19 desde fev/2025). Mude aqui se a lei mudar.
TETO_REFERENCIA = 46366.19
MINIMO_SERVIDORES = 500_000
ORGAOS = 80


def num(v) -> float:
    v = (v or "").strip()
    if not v:
        return 0.0
    try:
        return float(v.replace(".", "").replace(",", "."))
    except ValueError:
        return 0.0


def _leitor(z: zipfile.ZipFile, sufixo: str):
    nome = next(n for n in z.namelist() if n.lower().endswith(sufixo.lower()))
    leitor = csv.reader(io.TextIOWrapper(z.open(nome), encoding="latin-1", newline=""), delimiter=";")
    return next(leitor), leitor


def _idx(cab, *nomes):
    norm = [c.strip().upper() for c in cab]
    out = []
    for n in nomes:
        if n not in norm:
            raise ValueError(f"Arquivo de servidores mudou: falta a coluna {n!r} em {cab[:6]}")
        out.append(norm.index(n))
    return out


def agregar(z: zipfile.ZipFile, teto: float = TETO_REFERENCIA) -> dict:
    """{'servidores', 'orgaos': {cod: {...}}, 'ufs': {uf: {...}}} ligando cadastro e remuneração pelo Id do servidor."""
    cab, linhas = _leitor(z, "_Cadastro.csv")
    i_id, i_cod, i_org, i_sup, i_uf = _idx(cab, "ID_SERVIDOR_PORTAL", "COD_ORG_EXERCICIO", "ORG_EXERCICIO", "ORGSUP_EXERCICIO", "UF_EXERCICIO")
    maximo = max(i_id, i_cod, i_org, i_sup, i_uf)
    orgaos: dict[str, list] = {}   # código -> [nome, órgão superior]
    lotacao: dict[int, tuple] = {}   # id -> (código do órgão, UF)
    for l in linhas:
        if len(l) <= maximo:
            continue
        try:
            sid = int(l[i_id])
        except ValueError:
            continue
        cod = l[i_cod].strip()
        orgaos.setdefault(cod, [l[i_org].strip(), l[i_sup].strip()])
        uf = l[i_uf].strip()
        lotacao[sid] = (cod, uf if uf in UFS else "")   # "-1" = sem estado informado (exterior ou sem lotação)
    cab, linhas = _leitor(z, "_Remuneracao.csv")
    (i_id, i_bruta, i_abate, i_liq) = _idx(cab, "ID_SERVIDOR_PORTAL", "REMUNERAÇÃO BÁSICA BRUTA (R$)", "ABATE-TETO (R$)", "REMUNERAÇÃO APÓS DEDUÇÕES OBRIGATÓRIAS (R$)")
    maximo = max(i_id, i_bruta, i_abate, i_liq)
    por_org: dict[str, dict] = {}
    por_uf: dict[str, dict] = {}
    total = 0
    sem_cadastro = 0
    for l in linhas:
        if len(l) <= maximo:
            continue
        try:
            sid = int(l[i_id])
        except ValueError:
            continue
        cod, uf = lotacao.get(sid, ("", ""))
        if not cod:
            sem_cadastro += 1
        bruta, abate, liq = num(l[i_bruta]), num(l[i_abate]), num(l[i_liq])
        total += 1
        for dic, chave in ((por_org, cod or "sem cadastro"), (por_uf, uf or "sem UF")):
            e = dic.setdefault(chave, {"n": 0, "bruta": 0.0, "abate_teto": 0.0, "liquida": 0.0, "acima_teto": 0, "cortados_pelo_teto": 0})
            e["n"] += 1
            e["bruta"] += bruta
            e["abate_teto"] += abate
            e["liquida"] += liq
            if bruta > teto:
                e["acima_teto"] += 1
            if abate:
                e["cortados_pelo_teto"] += 1
    return {"servidores": total, "sem_cadastro": sem_cadastro, "orgaos": por_org, "ufs": por_uf, "nomes": orgaos}


def _arred(e: dict) -> dict:
    return {**e, "bruta": round(e["bruta"], 2), "abate_teto": round(e["abate_teto"], 2), "liquida": round(e["liquida"], 2)}


def resumir(ag: dict, competencia: str) -> dict:
    lista = []
    for cod, e in ag["orgaos"].items():
        nome, sup = ag["nomes"].get(cod, ["Sem cadastro", ""])
        lista.append({"codigo": cod, "orgao": nome, "orgao_superior": sup, **_arred(e), "media": round(e["bruta"] / e["n"], 2) if e["n"] else 0})
    lista.sort(key=lambda x: -x["n"])
    ufs = {uf: _arred(e) for uf, e in ag["ufs"].items()}
    tot = {k: round(sum(x[k] for x in lista), 2) for k in ("bruta", "abate_teto", "liquida")}
    tot.update({k: sum(x[k] for x in lista) for k in ("acima_teto", "cortados_pelo_teto")})
    return {"competencia": competencia, "servidores": ag["servidores"], "sem_cadastro": ag["sem_cadastro"], "teto_referencia": TETO_REFERENCIA,
            "total": tot, "orgaos": lista[:ORGAOS], "n_orgaos": len(lista), "ufs": ufs}


def baixar(periodos: list[str]) -> tuple[str, Path]:
    for per in periodos:
        destino = Path(tempfile.mkdtemp(prefix="servidores-")) / f"{per}.zip"
        try:
            http.baixar(URL.format(periodo=per), str(destino))
            return per, destino
        except Exception as e:  # noqa: BLE001
            resp = getattr(e, "response", None)
            if resp is not None and resp.status_code in (403, 404):
                continue
            raise
    raise RuntimeError(f"Portal da Transparência: nenhum arquivo de servidores em {periodos}")


def coletar_servidores(meses: int = 1, refazer: bool = False):
    """Último mês publicado (ou os `meses` mais recentes; competências já gravadas não são baixadas de novo)."""
    with registrar_coleta("transparencia", "servidores") as (db, n):
        hoje = date.today()
        periodos, a, m = [], hoje.year, hoje.month
        for _ in range(8):
            periodos.append(f"{a}{m:02d}")
            m -= 1
            if m == 0:
                a, m = a - 1, 12
        feitos = 0
        for per in periodos:
            if feitos >= int(meses):
                break
            if not refazer and db.query(Registro).filter_by(fonte="transparencia", tipo="servidores_mes", chave=per).first():
                feitos += 1
                continue
            try:
                _, arq = baixar([per])
            except RuntimeError:
                continue   # ainda não saiu
            with zipfile.ZipFile(arq) as z:
                ag = agregar(z)
            arq.unlink(missing_ok=True)
            if ag["servidores"] < MINIMO_SERVIDORES:
                raise RuntimeError(f"servidores {per}: só {ag['servidores']:,} remunerações (esperado ≥ {MINIMO_SERVIDORES:,}); nada foi gravado")
            if ag["sem_cadastro"] > 0.05 * ag["servidores"]:
                raise RuntimeError(f"servidores {per}: {ag['sem_cadastro']:,} remunerações sem cadastro; nada foi gravado")
            d = resumir(ag, per)
            upsert(db, Registro, {"fonte": "transparencia", "tipo": "servidores_mes", "chave": per},
                   {"ano": int(per[:4]), "titulo": f"Servidores federais {per[4:]}/{per[:4]}", "valor": d["total"]["bruta"], "dados": d})
            db.commit()
            n += 1
            feitos += 1
        if not n.itens and not feitos:
            raise RuntimeError("nenhuma competência de servidores foi lida")
    return n.itens
