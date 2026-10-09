"""Empresas em recuperação judicial e falência — base aberta do CNPJ (Receita Federal).

A Receita publica todo mês o cadastro completo num compartilhamento do SERPRO (Nextcloud):
  https://arquivos.receitafederal.gov.br/index.php/s/YggdBLfdninEJX9  (pastas AAAA-MM; WebDAV em public.php/webdav)
Arquivos Estabelecimentos0..9 e Empresas0..9: CSV sem cabeçalho, latin-1, separador ';', tudo entre aspas.
Cada estabelecimento tem "situação especial" (campo 29) e a data dela (campo 30): RECUPERACAO JUDICIAL,
FALIDO, ESPOLIO... É o registro da Receita, não a lista do Judiciário: pode atrasar em relação ao processo.

O servidor entrega cerca de 0,6 MB/s por conexão e a base tem vários GB, então os dez arquivos de cada tipo
são baixados ao mesmo tempo e lidos enquanto chegam (sem gravar em disco). Primeiro os Estabelecimentos
(guardamos só os que têm recuperação judicial ou falência), depois as Empresas (razão social, porte, capital).
Resultado em `registros` (fonte receita, tipos recuperacao_judicial e falencia).
"""
import csv
import os
import re
import struct
import threading
import time
import zlib
from concurrent.futures import ThreadPoolExecutor

import httpx
from sqlalchemy import delete

from app.collectors.base import log, registrar_coleta
from app.models import Registro
from app.utils import sem_acento

TOKEN = "YggdBLfdninEJX9"
WEBDAV = "https://arquivos.receitafederal.gov.br/public.php/webdav/"
TIPOS = ("recuperacao_judicial", "falencia")
SITUACAO = {"01": "Nula", "02": "Ativa", "03": "Suspensa", "04": "Inapta", "08": "Baixada"}
PORTE = {"00": "Não informado", "01": "Microempresa", "03": "Empresa de pequeno porte", "05": "Demais"}
SEM_SITUACAO_ESPECIAL = b';"";""'  # fim da linha quando os dois últimos campos estão vazios


class TempoEsgotado(Exception):
    pass


def tipo_situacao(texto: str) -> str | None:
    t = sem_acento(texto or "")
    if "RECUPERACAO JUDICIAL" in t or "RECUPERACAO EXTRAJUDICIAL" in t:
        return "recuperacao_judicial"
    if "FALID" in t or "FALENCIA" in t:
        return "falencia"
    return None


def _cliente():
    return httpx.Client(timeout=httpx.Timeout(60.0, read=300.0), follow_redirects=True, auth=(TOKEN, ""),
                        headers={"User-Agent": "BRASIL+ coletor (transparencia)"})


def ultimo_mes(cli) -> str:
    r = cli.request("PROPFIND", WEBDAV, headers={"Depth": "1"})
    r.raise_for_status()
    meses = sorted(set(re.findall(r"/(\d{4}-\d{2})/?</d:href>", r.text)))
    if not meses:
        raise RuntimeError("Nenhuma pasta AAAA-MM no compartilhamento do CNPJ")
    return meses[-1]


def blocos_arquivo(caminho, tamanho=1 << 20):
    with open(caminho, "rb") as f:
        while bloco := f.read(tamanho):
            yield bloco


def linhas_do_zip(blocos):
    """Linhas do primeiro arquivo de um zip, lidas enquanto os bytes chegam: cabeçalho local do zip + fluxo
    deflate (os arquivos da Receita têm um CSV só)."""
    blocos = iter(blocos)
    buf = b""
    while len(buf) < 30:
        buf += next(blocos)
    if buf[:4] != b"PK\x03\x04":
        raise ValueError("não é um arquivo zip")
    metodo, = struct.unpack("<H", buf[8:10])
    tam_comp, = struct.unpack("<I", buf[18:22])
    nl, el = struct.unpack("<HH", buf[26:30])
    while len(buf) < 30 + nl + el:
        buf += next(blocos)
    d = zlib.decompressobj(-15) if metodo == 8 else None
    restante = tam_comp if metodo == 0 else None
    resto = b""

    def todos():
        yield buf[30 + nl + el:]
        yield from blocos
    for bloco in todos():
        if d:
            texto = d.decompress(bloco)
        else:
            texto = bloco[:restante]
            restante -= len(texto)
        partes = (resto + texto).split(b"\n")
        resto = partes.pop()
        yield from partes
        if (d and d.eof) or (restante is not None and restante <= 0):
            break
    if resto.strip():
        yield resto


def _csv(linha: bytes) -> list[str]:
    return next(csv.reader([linha.decode("latin-1").rstrip("\r\n")], delimiter=";"))


def ler_estabelecimentos(linhas, achados: dict, prazo=None):
    """Guarda em `achados` (por CNPJ básico) os estabelecimentos com recuperação judicial ou falência.
    Fica a matriz quando houver; senão, o primeiro estabelecimento encontrado."""
    for k, bruta in enumerate(linhas):
        if prazo and k % 200000 == 0 and time.monotonic() > prazo:
            raise TempoEsgotado
        if bruta.rstrip(b"\r\n").endswith(SEM_SITUACAO_ESPECIAL):
            continue
        c = _csv(bruta)
        if len(c) < 30:
            continue
        tipo = tipo_situacao(c[28])
        if not tipo:
            continue
        basico, matriz = c[0], c[3] == "1"
        if basico in achados and not matriz:
            continue
        data = c[29]
        achados[basico] = {
            "tipo": tipo, "cnpj": f"{c[0]}{c[1]}{c[2]}", "matriz": matriz, "nome_fantasia": c[4].strip() or None,
            "situacao_cadastral": SITUACAO.get(c[5], c[5]), "situacao_especial": c[28].strip(),
            "data_situacao_especial": f"{data[:4]}-{data[4:6]}-{data[6:8]}" if len(data) == 8 else None,
            "cnae": c[11], "uf": c[19] or None, "municipio_receita": c[20], "inicio_atividade": c[10] or None,
        }
    return achados


def ler_empresas(linhas, procurados, prazo=None) -> dict:
    """Razão social, natureza jurídica, capital social e porte dos CNPJs básicos procurados."""
    out = {}
    for k, bruta in enumerate(linhas):
        if prazo and k % 200000 == 0 and time.monotonic() > prazo:
            raise TempoEsgotado
        if bruta[1:9].decode("latin-1") not in procurados:
            continue
        c = _csv(bruta)
        if len(c) < 6:
            continue
        try:
            capital = float(c[4].replace(".", "").replace(",", "."))
        except ValueError:
            capital = None
        out[c[0]] = {"razao_social": c[1].strip(), "natureza_juridica": c[2], "capital_social": capital,
                     "porte": PORTE.get(c[5], c[5] or None)}
    return out


def ler_tabela(linhas, prazo=None) -> dict:
    """Arquivos auxiliares (Municipios, Cnaes): código;descrição."""
    out = {}
    for bruta in linhas:
        c = _csv(bruta)
        if len(c) >= 2:
            out[c[0]] = c[1].strip()
    return out


def coletar_recuperacao_judicial(mes: str | None = None, minutos: int = 150, pasta_local: str | None = None,
                                 paralelo: int = 10):
    """`pasta_local`: pasta com os zips já baixados (testes). `minutos`: orçamento; ao estourar, grava o que leu."""
    with registrar_coleta("receita", "recuperacao_judicial", mes=mes or "último") as (db, n):
        inicio = time.monotonic()
        cli = None if pasta_local else _cliente()
        mes = mes or ("local" if pasta_local else ultimo_mes(cli))
        trava = threading.Lock()

        def ler(nome, fn, *args, prazo=None):
            """Lê um arquivo (baixando ao mesmo tempo); falha ou tempo esgotado viram aviso, sem derrubar os outros."""
            t = time.monotonic()
            try:
                if pasta_local:
                    caminho = os.path.join(pasta_local, nome)
                    if not os.path.exists(caminho):
                        return None
                    return fn(linhas_do_zip(blocos_arquivo(caminho)), *args, prazo=prazo)
                with cli.stream("GET", f"{WEBDAV}{mes}/{nome}") as r:
                    r.raise_for_status()
                    res = fn(linhas_do_zip(r.iter_bytes(1 << 20)), *args, prazo=prazo)
                log.info("CNPJ %s/%s lido em %.0f min", mes, nome, (time.monotonic() - t) / 60)
                return res
            except TempoEsgotado:
                aviso = f"{nome}: tempo esgotado no meio do arquivo"
            except Exception as e:
                aviso = f"{nome}: {type(e).__name__}: {e}"[:200]
            with trava:
                n.avisos.append(aviso)
            return None

        # 1) estabelecimentos, em paralelo (cada um com seu dicionário; a matriz tem preferência ao juntar)
        prazo1 = inicio + minutos * 60 * 0.7
        with ThreadPoolExecutor(paralelo) as ex:
            partes = list(ex.map(lambda i: ler(f"Estabelecimentos{i}.zip", ler_estabelecimentos, {}, prazo=prazo1),
                                 range(10)))
        achados = {}
        for parte in partes:
            for basico, e in (parte or {}).items():
                if basico not in achados or (e["matriz"] and not achados[basico]["matriz"]):
                    achados[basico] = e
        log.info("CNPJ: %s empresas com recuperação judicial ou falência", len(achados))

        # 2) empresas (razão social etc.) e tabelas de municípios e CNAE
        prazo2 = inicio + minutos * 60
        procurados = frozenset(achados)
        with ThreadPoolExecutor(paralelo) as ex:
            partes = list(ex.map(lambda i: ler(f"Empresas{i}.zip", ler_empresas, procurados, prazo=prazo2), range(10)))
        for parte in partes:
            for basico, dados in (parte or {}).items():
                achados[basico].update(dados)
        municipios = ler("Municipios.zip", ler_tabela) or {}
        cnaes = ler("Cnaes.zip", ler_tabela) or {}
        if cli:
            cli.close()

        if not achados:
            raise RuntimeError("Nenhum estabelecimento lido: " + "; ".join(n.avisos)[:500])
        if not n.avisos:  # leitura completa: substitui a lista anterior
            db.execute(delete(Registro).where(Registro.fonte == "receita", Registro.tipo.in_(TIPOS)))
            db.flush()
            antigos = {}
        else:  # parcial: atualiza o que foi lido e mantém o resto
            antigos = {(r.tipo, r.chave): r for r in db.query(Registro).filter(
                Registro.fonte == "receita", Registro.tipo.in_(TIPOS))}
        for e in achados.values():
            e["municipio"] = municipios.get(e.pop("municipio_receita") or "")
            e["cnae_descricao"] = cnaes.get(e["cnae"])
            e["mes_base"] = mes
            ano = int(e["data_situacao_especial"][:4]) if e.get("data_situacao_especial") else None
            valores = {"uf": e["uf"], "ano": ano, "titulo": e.get("razao_social") or e.get("nome_fantasia") or e["cnpj"],
                       "valor": e.get("capital_social"), "dados": e}
            r = antigos.get((e["tipo"], e["cnpj"]))
            if r:
                for k, v in valores.items():
                    setattr(r, k, v)
            else:
                db.add(Registro(fonte="receita", tipo=e["tipo"], chave=e["cnpj"], **valores))
            n += 1
    return n.itens
