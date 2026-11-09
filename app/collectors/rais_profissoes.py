"""Coletor da RAIS por profissão (CBO): lê os vínculos regionais de um ano e grava só agregados.

Regras (pedidas no projeto):
- ano: o mais recente com TODOS os arquivos regionais de vínculos (prioridade 2025, contingência 2024);
- nada de nome, CPF ou matrícula é lido para o resultado: só contagens por CBO e faixa de horas;
- leitura em streaming: cada .7z é baixado, lido vínculo a vínculo e apagado;
- se algum arquivo faltar, falhar ou a contagem total parecer baixa demais, NADA é gravado e o dado anterior fica;
- o arquivo gravado traz ano de referência, fonte, data de atualização e a lista de arquivos usados.
"""
import ftplib
import json
import logging
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from app import profissoes as P
from app import rais_leitor as L

log = logging.getLogger("coletor.rais")

HOST = "ftp.mtps.gov.br"
RAIZ = "/pdet/microdados/RAIS"
ANOS_PREFERIDOS = (2025, 2024)  # 2025 primeiro; 2024 só se 2025 estiver incompleto
ARQUIVOS_REGIONAIS = (
    "RAIS_VINC_PUB_CENTRO_OESTE.7z",
    "RAIS_VINC_PUB_MG_ES_RJ.7z",
    "RAIS_VINC_PUB_NI.7z",
    "RAIS_VINC_PUB_NORDESTE.7z",
    "RAIS_VINC_PUB_NORTE.7z",
    "RAIS_VINC_PUB_SP.7z",
    "RAIS_VINC_PUB_SUL.7z",
)
MINIMO_VINCULOS_ATIVOS = 30_000_000  # abaixo disso a leitura está incompleta: não grava
DESTINO = Path(__file__).resolve().parent.parent / "dados" / "profissoes_rais.json"


class ColetaIncompleta(RuntimeError):
    """Algo faltou ou pareceu errado: o dado anterior é mantido."""


def conectar() -> ftplib.FTP:
    ftp = ftplib.FTP(HOST, timeout=300, encoding="latin-1")
    ftp.login()
    return ftp


def escolher_ano(nomes_raiz: list[str], listar_pasta) -> int:
    """Devolve o primeiro ano preferido cuja pasta tem todos os arquivos regionais."""
    for ano in ANOS_PREFERIDOS:
        if str(ano) not in nomes_raiz:
            continue
        arquivos = set(listar_pasta(str(ano)))
        if all(a in arquivos for a in ARQUIVOS_REGIONAIS):
            return ano
        log.warning("RAIS %s incompleta (faltam %s)", ano, [a for a in ARQUIVOS_REGIONAIS if a not in arquivos])
    raise ColetaIncompleta("nenhum ano preferido está completo: " + ", ".join(map(str, ANOS_PREFERIDOS)))


def baixar_regional(ftp: ftplib.FTP, ano: int, nome: str, destino: Path) -> Path:
    ftp.cwd(f"{RAIZ}/{ano}")
    tamanho = ftp.size(nome)
    with open(destino, "wb") as fh:
        ftp.retrbinary(f"RETR {nome}", fh.write, blocksize=1 << 20)
    if destino.stat().st_size != tamanho:
        raise ColetaIncompleta(f"{nome}: baixou {destino.stat().st_size} de {tamanho} bytes")
    return destino


def agregar_arquivo(caminho_7z: Path, acc: P.Acumulador) -> int:
    """Lê um .7z em streaming, soma no acumulador e devolve quantos vínculos válidos ele trouxe."""
    antes = acc.total()
    for v in L.ler_7z(str(caminho_7z)):
        acc.add(v.cbo, v.remuneracao, v.faixa_horas)
    trouxe = acc.total() - antes
    log.info("RAIS %s: %s vínculos válidos", caminho_7z.name, trouxe)
    return trouxe


def montar_documento(ano: int, acc: P.Acumulador, por_arquivo: dict) -> dict:
    total = acc.total()
    if total < MINIMO_VINCULOS_ATIVOS:
        raise ColetaIncompleta(f"só {total:,} vínculos válidos (mínimo {MINIMO_VINCULOS_ATIVOS:,}): nada gravado")
    return {
        "fonte": "RAIS — Ministério do Trabalho e Emprego (microdados públicos de vínculos)",
        "ano_referencia": ano,
        "atualizado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "vinculos_validos": total,
        "arquivos": por_arquivo,
        "observacao": "Vínculos ativos em 31/12. Remuneração média nominal. Horas contratadas (a escala 6x1/5x2 não é informada pela RAIS). "
                      "Percentis com precisão de R$ 10. Profissões com menos de 30 vínculos não aparecem.",
        "profissoes": acc.resultado(),
    }


def gravar_se_valido(doc: dict, destino: Path = DESTINO) -> Path:
    """Escreve de forma atômica. Não sobrescreve um arquivo de ano mais novo com um mais antigo."""
    if destino.exists():
        atual = json.loads(destino.read_text(encoding="utf-8"))
        if int(atual.get("ano_referencia", 0)) > int(doc["ano_referencia"]):
            raise ColetaIncompleta("já existe um ano mais novo gravado: nada foi trocado")
    destino.parent.mkdir(parents=True, exist_ok=True)
    tmp = destino.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, destino)
    return destino


def coletar(destino: Path = DESTINO) -> dict:
    """Coleta completa (roda no robô). Baixa um arquivo regional por vez, lê, soma e apaga.
    Qualquer falha antes de gravar deixa o arquivo anterior intacto."""
    ftp = conectar()
    try:
        ftp.cwd(RAIZ)
        ano = escolher_ano(ftp.nlst(), _listar_ano(ftp))
        acc = P.Acumulador()
        por_arquivo = {}
        with tempfile.TemporaryDirectory(prefix="rais_dl_") as pasta:
            for nome in ARQUIVOS_REGIONAIS:
                caminho = baixar_regional(ftp, ano, nome, Path(pasta) / nome)
                trouxe = agregar_arquivo(caminho, acc)
                por_arquivo[nome] = trouxe
                caminho.unlink()  # libera o disco antes do próximo arquivo
                if trouxe == 0 and nome != "RAIS_VINC_PUB_NI.7z":
                    raise ColetaIncompleta(f"{nome} não trouxe nenhum vínculo válido")
    finally:
        try:
            ftp.quit()
        except ftplib.Error:
            pass
    doc = montar_documento(ano, acc, por_arquivo)
    gravar_se_valido(doc, destino)
    return {"ano": ano, "vinculos": doc["vinculos_validos"], "profissoes": len(doc["profissoes"])}


def _listar_ano(ftp):
    def listar(pasta: str) -> list[str]:
        ftp.cwd(f"{RAIZ}/{pasta}")
        nomes = ftp.nlst()
        ftp.cwd(RAIZ)
        return nomes
    return listar
