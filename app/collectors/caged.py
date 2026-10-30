"""Novo CAGED (emprego formal): admissões, desligamentos e saldo por estado, mês e seção da CNAE.

As tabelas prontas do PDET não abrem pelo robô (a página `acesso.trabalho.gov.br` falha na verificação do certificado e `pdet.mte.gov.br` dá tempo esgotado); o gov.br
só publica PDF e imagem. Os microdados mensais ficam no FTP do Ministério (`ftp.mtps.gov.br`, `/pdet/microdados/NOVO CAGED/AAAA/AAAAMM/CAGEDMOV/FOR/EXCAAAAMM.7z`, ~50 MB o
principal). O arquivo é lido em fluxo e SÓ AS SOMAS são guardadas: nenhum registro de trabalhador (nem salário, CBO, idade ou sexo) vai para o banco.
`saldo_mov` = admissões − desligamentos dos movimentos declarados no mês (CAGEDMOV). Os números oficiais somam ainda os declarados fora do prazo (CAGEDFOR) e tiram os
excluídos (CAGEDEXC); por isso guardamos também as contagens desses dois arquivos e o saldo oficial pode diferir um pouco. Estoque de empregos não está nestes arquivos."""
import csv
import ftplib
import logging
import random
import re
import shutil
import time
import tempfile
from pathlib import Path

from app.collectors.base import registrar_coleta
from app.models import Registro
from app.utils import sem_acento, upsert

log = logging.getLogger("brasilplus.caged")
HOST = "ftp.mtps.gov.br"
RAIZ = "/pdet/microdados/NOVO CAGED"
UF_IBGE = {"11": "RO", "12": "AC", "13": "AM", "14": "RR", "15": "PA", "16": "AP", "17": "TO", "21": "MA", "22": "PI", "23": "CE", "24": "RN", "25": "PB", "26": "PE", "27": "AL",
           "28": "SE", "29": "BA", "31": "MG", "32": "ES", "33": "RJ", "35": "SP", "41": "PR", "42": "SC", "43": "RS", "50": "MS", "51": "MT", "52": "GO", "53": "DF"}
SECOES = {"A": "Agropecuária", "B": "Indústrias extrativas", "C": "Indústria de transformação", "D": "Eletricidade e gás", "E": "Água, esgoto e resíduos", "F": "Construção",
          "G": "Comércio", "H": "Transporte e armazenagem", "I": "Alojamento e alimentação", "J": "Informação e comunicação", "K": "Financeiras e seguros", "L": "Imobiliárias",
          "M": "Atividades profissionais e científicas", "N": "Atividades administrativas", "O": "Administração pública", "P": "Educação", "Q": "Saúde e serviço social",
          "R": "Artes, cultura e esporte", "S": "Outros serviços", "T": "Serviços domésticos", "U": "Organismos internacionais", "Z": "Não identificada"}
MINIMO_MOV = 1_000_000   # movimentações esperadas num mês (guarda contra arquivo cortado)


def _norm(h: str) -> str:
    return re.sub(r"[^a-z0-9]", "", sem_acento(h).lower())


def agregar(linhas, cab: list[str]) -> dict:
    """{'linhas': n, 'competencias': {AAAAMM: {UF: {'adm','desl','secoes': {letra: [adm, desl]}}}}} — só contagens."""
    ncab = [_norm(c) for c in cab]
    try:
        i_comp = next(i for i, c in enumerate(ncab) if c.startswith("competenciamov"))
        i_uf = ncab.index("uf")
        i_sec = ncab.index("secao")
        i_saldo = next(i for i, c in enumerate(ncab) if c.startswith("saldomov"))
    except (StopIteration, ValueError):
        raise ValueError(f"Arquivo do CAGED mudou: colunas esperadas não achadas em {cab[:12]}") from None
    maximo = max(i_comp, i_uf, i_sec, i_saldo)
    comps: dict[str, dict] = {}
    n = 0
    for l in linhas:
        if len(l) <= maximo:
            continue
        uf = UF_IBGE.get(l[i_uf].strip())
        if not uf:
            continue
        try:
            saldo = int(l[i_saldo])
        except ValueError:
            continue
        n += 1
        e = comps.setdefault(l[i_comp].strip(), {}).setdefault(uf, {"adm": 0, "desl": 0, "secoes": {}})
        s = e["secoes"].setdefault(l[i_sec].strip().upper() or "Z", [0, 0])
        if saldo > 0:
            e["adm"] += 1
            s[0] += 1
        elif saldo < 0:
            e["desl"] += 1
            s[1] += 1
    return {"linhas": n, "competencias": comps}


def ler_7z(caminho: Path):
    """Extrai o .7z numa pasta temporária (o formato não permite ler em fluxo) e devolve (cabeçalho, iterador de linhas, pasta)."""
    import py7zr
    pasta = Path(tempfile.mkdtemp(prefix="caged-x-"))
    with py7zr.SevenZipFile(caminho) as z:
        z.extractall(path=pasta)
    arq = next(p for p in pasta.rglob("*") if p.is_file() and p.suffix.lower() in (".txt", ".csv"))
    bruto = arq.read_bytes()[:65536]
    try:
        bruto.decode("utf-8")
        enc = "utf-8-sig"
    except UnicodeDecodeError as e:
        enc = "utf-8-sig" if e.start >= len(bruto) - 4 else "latin-1"   # corte no meio de um caractere não conta
    fh = open(arq, encoding=enc, newline="")
    leitor = csv.reader(fh, delimiter=";")
    return next(leitor), leitor, pasta, fh


def conectar(tentativas: int = 5) -> ftplib.FTP:
    """Conexão ao FTP com espera crescente: o robô já recebeu 'Temporary failure in name resolution' numa execução e funcionou em outra."""
    for i in range(1, tentativas + 1):
        try:
            ftp = ftplib.FTP(timeout=120, encoding="latin-1")
            ftp.connect(HOST, 21)
            ftp.login()
            return ftp
        except (OSError, ftplib.Error) as e:
            if i == tentativas:
                raise
            pausa = 5 * i * (0.5 + random.random())
            log.warning("CAGED FTP: %s; nova tentativa em %.0fs", type(e).__name__, pausa)
            time.sleep(pausa)
    raise RuntimeError("inalcançável")


def listar_ftp(ftp: ftplib.FTP, caminho: str) -> list[str]:
    ftp.cwd(caminho)
    return ftp.nlst()


def baixar_ftp(ftp: ftplib.FTP, caminho: str, nome: str) -> Path:
    destino = Path(tempfile.mkdtemp(prefix="caged-")) / nome
    ftp.cwd(caminho)
    with open(destino, "wb") as f:
        ftp.retrbinary(f"RETR {nome}", f.write, blocksize=1 << 20)
    return destino


def processar(ftp, ano: str, mes: str) -> dict:
    caminho = f"{RAIZ}/{ano}/{mes}"
    out: dict[str, dict] = {}
    for prefixo in ("CAGEDMOV", "CAGEDFOR", "CAGEDEXC"):
        nome = f"{prefixo}{mes}.7z"
        arq = baixar_ftp(ftp, caminho, nome)
        pasta = fh = None
        try:
            cab, linhas, pasta, fh = ler_7z(arq)
            out[prefixo] = agregar(linhas, cab)
        finally:
            if fh:
                fh.close()
            if pasta:
                shutil.rmtree(pasta, ignore_errors=True)
            arq.unlink(missing_ok=True)
    return out


def resumir(partes: dict, mes: str) -> dict:
    mov = partes["CAGEDMOV"]["competencias"].get(mes, {})
    por_uf, secoes = {}, {}
    for uf, e in mov.items():
        por_uf[uf] = {"admissoes": e["adm"], "desligamentos": e["desl"], "saldo_mov": e["adm"] - e["desl"],
                      "por_secao": {k: {"admissoes": v[0], "desligamentos": v[1], "saldo_mov": v[0] - v[1], "setor": SECOES.get(k, k)} for k, v in sorted(e["secoes"].items())}}
        for k, v in e["secoes"].items():
            s = secoes.setdefault(k, [0, 0])
            s[0] += v[0]
            s[1] += v[1]
    adm = sum(u["admissoes"] for u in por_uf.values())
    desl = sum(u["desligamentos"] for u in por_uf.values())
    extra = {}
    for pref, rot in (("CAGEDFOR", "fora_do_prazo"), ("CAGEDEXC", "excluidos")):
        comps = partes[pref]["competencias"]
        extra[rot] = {"linhas": partes[pref]["linhas"], "admissoes": sum(e["adm"] for c in comps.values() for e in c.values()),
                      "desligamentos": sum(e["desl"] for c in comps.values() for e in c.values())}
    return {"competencia": mes, "brasil": {"admissoes": adm, "desligamentos": desl, "saldo_mov": adm - desl},
            "por_secao": {k: {"admissoes": v[0], "desligamentos": v[1], "saldo_mov": v[0] - v[1], "setor": SECOES.get(k, k)} for k, v in sorted(secoes.items())},
            "por_uf": por_uf, "fora_do_prazo": extra["fora_do_prazo"], "excluidos": extra["excluidos"], "movimentos_lidos": partes["CAGEDMOV"]["linhas"]}


def coletar_caged(meses: int = 2, refazer: bool = False):
    """Os `meses` mais recentes do FTP do Novo CAGED (competência já gravada não volta a ser baixada)."""
    with registrar_coleta("caged", "saldos") as (db, n):
        ftp = conectar()
        try:
            anos = sorted(a for a in listar_ftp(ftp, RAIZ) if re.fullmatch(r"\d{4}", a))
            if not anos:
                raise RuntimeError("CAGED: nenhuma pasta de ano no FTP (estrutura mudou?)")
            candidatos = []
            for ano in reversed(anos[-2:]):
                candidatos += [(ano, m) for m in sorted((m for m in listar_ftp(ftp, f"{RAIZ}/{ano}") if re.fullmatch(r"\d{6}", m)), reverse=True)]
            for ano, mes in candidatos[: int(meses)]:
                if not refazer and db.query(Registro).filter_by(fonte="caged", tipo="caged_mes", chave=mes).first():
                    continue
                try:
                    d = resumir(processar(ftp, ano, mes), mes)
                    if d["movimentos_lidos"] < MINIMO_MOV:
                        raise RuntimeError(f"CAGED {mes}: só {d['movimentos_lidos']:,} movimentos (esperado ≥ {MINIMO_MOV:,}); nada foi gravado")
                    if len(d["por_uf"]) < 27:
                        raise RuntimeError(f"CAGED {mes}: vieram {len(d['por_uf'])} estados (esperado 27); nada foi gravado")
                    upsert(db, Registro, {"fonte": "caged", "tipo": "caged_mes", "chave": mes},
                           {"ano": int(mes[:4]), "titulo": f"Novo CAGED {mes[4:]}/{mes[:4]}", "valor": float(d["brasil"]["saldo_mov"]), "dados": d})
                    db.commit()
                    n += 1
                except Exception as e:  # noqa: BLE001
                    n.avisos.append(f"{mes}: {type(e).__name__}: {str(e)[:150]}")
        finally:
            try:
                ftp.quit()
            except Exception:  # noqa: BLE001
                pass
        if not n.itens and n.avisos:
            raise RuntimeError("; ".join(n.avisos))
    return n.itens
