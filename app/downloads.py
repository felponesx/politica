"""Download grande em streaming, com retomada (Range) e conferência de tamanho; usado pelo PRODES (shapefile) e pelo extrato do OpenStreetMap (PBF)."""
import hashlib
import logging
import time
from pathlib import Path

import httpx

from app import http

log = logging.getLogger("brasilplus.downloads")


def cabecalho(url: str) -> dict:
    r = http._cliente.head(url, headers={"Accept": "*/*"}, timeout=60)
    r.raise_for_status()
    return {"tamanho": int(r.headers.get("content-length") or 0), "etag": (r.headers.get("etag") or "").strip('"'), "modificado": r.headers.get("last-modified"),
            "aceita_range": "bytes" in (r.headers.get("accept-ranges") or "")}


def baixar(url: str, destino: Path, tentativas: int = 8) -> dict:
    """Download em streaming com retomada: guarda em `<arquivo>.parcial` e continua do byte onde parou (Range) depois de queda. Só renomeia quando o tamanho confere com o do servidor."""
    cab = cabecalho(url)
    final, parcial = destino, destino.with_name(destino.name + ".parcial")
    if final.exists() and final.stat().st_size == cab["tamanho"]:
        return {**cab, "retomado": False, "reutilizado": True}
    retomado = False
    for i in range(tentativas):
        ja = parcial.stat().st_size if parcial.exists() else 0
        if cab["tamanho"] and ja > cab["tamanho"]:
            parcial.unlink()
            ja = 0
        if cab["tamanho"] and ja == cab["tamanho"]:
            break
        headers = {"Accept": "*/*", **({"Range": f"bytes={ja}-"} if ja and cab["aceita_range"] else {})}
        try:
            with http._cliente.stream("GET", url, headers=headers, timeout=httpx.Timeout(60.0, read=120.0)) as r:
                if r.status_code == 200 and ja:   # o servidor ignorou o Range: recomeça do zero
                    ja = 0
                elif r.status_code not in (200, 206):
                    raise httpx.HTTPStatusError(f"HTTP {r.status_code}", request=r.request, response=r)
                retomado = retomado or bool(ja)
                with open(parcial, "ab" if ja else "wb") as f:
                    for pedaco in r.iter_bytes(1 << 20):
                        f.write(pedaco)
        except (httpx.TransportError, httpx.HTTPStatusError) as e:
            log.warning("download interrompido (%s); tentativa %s/%s, %s bytes já gravados", type(e).__name__, i + 1, tentativas, parcial.stat().st_size if parcial.exists() else 0)
            time.sleep(min(5 * (i + 1), 60))
            continue
        if not cab["tamanho"] or parcial.stat().st_size == cab["tamanho"]:
            break
    tam = parcial.stat().st_size if parcial.exists() else 0
    if cab["tamanho"] and tam != cab["tamanho"]:
        raise RuntimeError(f"download incompleto: {tam:,} de {cab['tamanho']:,} bytes; o arquivo parcial foi mantido para retomar")
    parcial.replace(final)
    return {**cab, "retomado": retomado, "reutilizado": False}


def sha256(caminho: Path) -> str:
    h = hashlib.sha256()
    with open(caminho, "rb") as f:
        for b in iter(lambda: f.read(1 << 22), b""):
            h.update(b)
    return h.hexdigest()


def md5(caminho: Path) -> str:
    h = hashlib.md5()  # noqa: S324 - só confere o arquivo contra o .md5 que a Geofabrik publica, não protege nada
    with open(caminho, "rb") as f:
        for b in iter(lambda: f.read(1 << 22), b""):
            h.update(b)
    return h.hexdigest()
