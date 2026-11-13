"""Transferências da União para ações de defesa civil (Portal da Transparência, arquivo mensal de transferências).

Filtro: subfunção "Defesa civil" ou ação com "DEFESA CIVIL", "DESASTRE", "CALAMIDADE" ou "RESPOSTA E RECUPERACAO" no nome. Guardamos a soma por mês e
estado (e o total por tipo de transferência). O valor é o da linha do arquivo (pode ser negativo: estorno é dado real).
NÃO é o gasto do estado: é o dinheiro federal repassado. Não separa por desastre (o arquivo não tem o evento).
"""
import csv
import hashlib
import io
import logging
import tempfile
import time
import zipfile
from datetime import date
from pathlib import Path

import httpx

from app import http
from app.collectors.base import registrar_coleta
from app.models import Registro
from app.utils import UFS, upsert

log = logging.getLogger("brasilplus.defesa_civil_transf")
URL = "https://dadosabertos-download.cgu.gov.br/PortalDaTransparencia/saida/transferencias/{ym}_Transferencias.zip"
PALAVRAS = ("DEFESA CIVIL", "DESASTRE", "CALAMIDADE", "RESPOSTA E RECUPERACAO")


def _valor(s: str) -> float:
    try:
        return float((s or "0").replace(".", "").replace(",", ".")) if "," in (s or "") else float(s or 0)
    except ValueError:
        return 0.0


def agregar(linhas, cab: list[str]) -> dict:
    """{uf: {valor, linhas, por_tipo: {tipo: valor}}} só das linhas de defesa civil."""
    need = ("ANO / MÊS", "UF", "NOME SUBFUNÇÃO", "NOME AÇÃO", "TIPO TRANSFERÊNCIA", "VALOR TRANSFERIDO")
    faltam = [c for c in need if c not in cab]
    if faltam:
        raise ValueError(f"Arquivo de transferências mudou: faltam {faltam}")
    i = {c: cab.index(c) for c in need}
    out: dict[str, dict] = {}
    for l in linhas:
        if len(l) <= max(i.values()):
            continue
        sub = (l[i["NOME SUBFUNÇÃO"]] or "").upper()
        acao = (l[i["NOME AÇÃO"]] or "").upper()
        if not ("DEFESA CIVIL" in sub or any(p in acao for p in PALAVRAS)):
            continue
        uf = (l[i["UF"]] or "").strip()
        if uf not in UFS:
            continue
        u = out.setdefault(uf, {"valor": 0.0, "linhas": 0, "por_tipo": {}})
        v = _valor(l[i["VALOR TRANSFERIDO"]])
        u["valor"] += v
        u["linhas"] += 1
        t = (l[i["TIPO TRANSFERÊNCIA"]] or "Sem tipo").strip()
        u["por_tipo"][t] = u["por_tipo"].get(t, 0.0) + v
    for u in out.values():
        u["valor"] = round(u["valor"], 2)
        u["por_tipo"] = {k: round(v, 2) for k, v in u["por_tipo"].items()}
    return out


def _baixar_com_espera(url: str, destino: Path, tentativas: int = 5):
    """O servidor da CGU responde 405/429 em rajadas: espera e tenta de novo (como o coletor da PRF)."""
    for t in range(tentativas):
        try:
            http.baixar(url, str(destino))
            return
        except httpx.HTTPStatusError as e:
            if e.response.status_code not in (405, 429, 503) or t == tentativas - 1:
                raise
            time.sleep(15 * (2 ** t))


def coletar_defesa_civil_transf(periodo: str = "2020-2026"):
    """Baixa os 12 arquivos mensais de cada ano (intervalo 'A-B' ou 'A'). Meses já gravados de anos fechados não são baixados de novo."""
    ini, _, fim = str(periodo).partition("-")
    ano_ini, ano_fim = int(ini), int(fim or ini)
    with registrar_coleta("portal", "defesa-civil-transferencias", periodo=str(periodo)) as (db, n):
        for ano in range(ano_ini, ano_fim + 1):
            for mes in range(1, 13):
                ym = f"{ano}{mes:02d}"
                ja = db.query(Registro).filter_by(fonte="portal", tipo="defesa_civil_mes", chave=f"{ym}").first()
                if ja and ano < date.today().year:
                    continue
                try:
                    destino = Path(tempfile.mkdtemp(prefix="dc-")) / f"{ym}.zip"
                    _baixar_com_espera(URL.format(ym=ym), destino)
                    if not zipfile.is_zipfile(destino):
                        raise RuntimeError("o servidor não devolveu um zip")
                    sha = hashlib.sha256(destino.read_bytes()).hexdigest()
                    with zipfile.ZipFile(destino) as z:
                        if z.testzip() is not None:
                            raise RuntimeError("zip corrompido")
                        nome = next(x for x in z.namelist() if x.lower().endswith(".csv"))
                        r = csv.reader(io.TextIOWrapper(z.open(nome), encoding="latin-1", newline=""), delimiter=";")
                        ag = agregar(r, [c.strip() for c in next(r)])
                    destino.unlink(missing_ok=True)
                    total = round(sum(u["valor"] for u in ag.values()), 2)
                    upsert(db, Registro, {"fonte": "portal", "tipo": "defesa_civil_mes", "chave": ym},
                           {"ano": ano, "titulo": f"Transferências da União para defesa civil {ym}", "valor": total,
                            "dados": {"ano_mes": ym, "total": total, "por_uf": ag, "sha256": sha, "url": URL.format(ym=ym),
                                      "filtro": "subfunção Defesa civil ou ação com " + ", ".join(PALAVRAS),
                                      "aviso": "Repasse federal (não é o gasto do estado nem separa por desastre)."}})
                    db.commit()
                    n += 1
                except Exception as e:  # noqa: BLE001 - um mês que falha não derruba os outros
                    n.avisos.append(f"{ym}: {type(e).__name__}: {str(e)[:120]}")
        if not n.itens and n.avisos:
            raise RuntimeError("; ".join(n.avisos[:5]))
    return n.itens
