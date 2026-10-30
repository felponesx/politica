"""INEP — IDEB do Brasil, dos estados e das escolas (planilhas de download.inep.gov.br/ideb/resultados/).

Arquivos (zip com .xlsx e .ods; o do Brasil só existe em .xlsx e só até 2023):
- divulgacao_regioes_ufs_ideb_<ano>.zip       regiões e estados, uma aba por etapa (AI, AF, EM), uma linha por rede;
- divulgacao_brasil_ideb_<ano>.xlsx           Brasil, uma aba por etapa;
- divulgacao_<anos_iniciais|anos_finais|ensino_medio>_escolas_<ano>.zip   escolas.
Cada aba tem a linha de códigos das colunas (`VL_OBSERVADO_<ano>` = IDEB, `VL_PROJECAO_<ano>` = meta) e os dados logo abaixo. O IDEB sai a cada 2 anos.

O servidor do INEP não envia o certificado intermediário (RNP ICPEdu GR46 OV TLS CA 2025, emitido pela GlobalSign Root R46). Completamos a cadeia com o
certificado do endereço AIA do próprio certificado, conferido pela impressão digital abaixo; a verificação do TLS continua ligada e esse certificado só vale
para este cliente. Se o INEP trocar o certificado, a coleta falha dizendo a nova impressão digital."""
import io
import logging
import random
import re
import tempfile
import time
import zipfile
from datetime import date
from pathlib import Path

import certifi
import httpx
import openpyxl

from app.collectors.base import registrar_coleta
from app.models import Registro
from app.utils import UFS, sem_acento, upsert, NOME_PARA_UF

log = logging.getLogger("brasilplus.inep")
BASE = "https://download.inep.gov.br/ideb/resultados/"
AIA = "http://secure.globalsign.com/cacert/rnpicpedugr46ovtlsca2025.crt"
AIA_SHA256 = "e10747d4da7bab09cba9952f019d3534cb9fba070bf13d8791b1699cd2ff59dd"
ETAPAS = {"iniciais": ("AI", "anos_iniciais"), "finais": ("AF", "anos_finais"), "medio": ("EM", "ensino_medio")}
ESCOLAS_POR_UF = 80   # melhores de cada estado e etapa (o ranking do país sai desta lista)
MINIMO_UFS = 27
MINIMO_ESCOLAS = {"iniciais": 20_000, "finais": 15_000, "medio": 8_000}
ABREVIADOS = {"M. G. DO SUL": "MS", "R. G. DO NORTE": "RN", "R. G. DO SUL": "RS"}  # a planilha abrevia estes três
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36", "Accept": "*/*"}  # o servidor do INEP derruba clientes sem cara de navegador
_cliente_cache: httpx.Client | None = None


def _tentar(fn, vezes: int = 5):
    """O servidor do INEP derruba conexões de vez em quando (reset): tenta de novo com espera crescente."""
    for i in range(1, vezes + 1):
        try:
            return fn()
        except (httpx.TransportError, httpx.HTTPStatusError) as e:
            if i == vezes:
                raise
            pausa = 4 * i * (0.5 + random.random())
            log.warning("INEP: %s; nova tentativa em %.0fs", type(e).__name__, pausa)
            time.sleep(pausa)


def cliente() -> httpx.Client:
    global _cliente_cache
    if _cliente_cache is None:
        der = _tentar(lambda: httpx.get(AIA, timeout=60, headers=UA).content)
        import hashlib
        h = hashlib.sha256(der).hexdigest()
        if h != AIA_SHA256:
            raise RuntimeError(f"certificado intermediário do INEP mudou (sha256 {h}); confira a cadeia e atualize AIA_SHA256 em app/collectors/inep.py")
        import ssl
        pem = ssl.DER_cert_to_PEM_cert(der)
        arq = Path(tempfile.mkdtemp(prefix="inep-ca-")) / "cadeia.pem"
        arq.write_text(Path(certifi.where()).read_text() + "\n" + pem)
        _cliente_cache = httpx.Client(verify=str(arq), timeout=300, follow_redirects=True, headers=UA)
    return _cliente_cache


def baixar(nome: str) -> Path:
    """Baixa um arquivo de BASE para um arquivo temporário (os das escolas passam de 100 MB)."""
    destino = Path(tempfile.mkdtemp(prefix="inep-")) / nome

    def go():
        with cliente().stream("GET", BASE + nome) as r:
            r.raise_for_status()
            with open(destino, "wb") as f:
                for parte in r.iter_bytes(1 << 20):
                    f.write(parte)
        return destino
    return _tentar(go)


def abrir_xlsx(caminho: Path) -> openpyxl.Workbook:
    """Abre o .xlsx direto ou o que estiver dentro do zip."""
    if caminho.suffix.lower() == ".zip":
        z = zipfile.ZipFile(caminho)
        nome = next(n for n in z.namelist() if n.lower().endswith(".xlsx"))
        destino = caminho.parent / Path(nome).name
        with z.open(nome) as src, open(destino, "wb") as dst:
            while True:
                bloco = src.read(1 << 20)
                if not bloco:
                    break
                dst.write(bloco)
        caminho = destino
    return openpyxl.load_workbook(caminho, read_only=True, data_only=True)


def valor(x) -> float | None:
    if isinstance(x, bool) or x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    t = str(x).strip().replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None


def linhas_da_aba(ws, n_chaves: int):
    """Itera (chaves, {ano: ideb}, {ano: meta}) de uma aba; `chaves` são as primeiras `n_chaves` colunas."""
    obs, proj, ja_vi_codigos = {}, {}, False
    for i, linha in enumerate(ws.iter_rows(values_only=True)):
        if not ja_vi_codigos:
            if i > 20:
                raise RuntimeError(f"aba {ws.title!r}: linha de códigos VL_ não encontrada")
            for j, c in enumerate(linha):
                m = isinstance(c, str) and re.fullmatch(r"VL_(OBSERVADO|PROJECAO)_(\d{4})", c.strip())
                if m:
                    (obs if m.group(1) == "OBSERVADO" else proj)[int(m.group(2))] = j
            ja_vi_codigos = bool(obs)
            continue
        if not linha or all(c is None for c in linha[:n_chaves]):
            continue
        yield (tuple(linha[:n_chaves]), {a: valor(linha[j]) for a, j in obs.items() if j < len(linha)}, {a: valor(linha[j]) for a, j in proj.items() if j < len(linha)})


_MIUDAS = {"DE", "DA", "DO", "DAS", "DOS", "E", "EM", "NA", "NO"}
_SIGLAS = {"EE", "EEEFM", "EEEM", "EEEF", "EEEMTI", "EMEF", "EMEI", "EMEIF", "EMEB", "EMEFM", "CED", "CEM", "CEEP", "CE", "CEF", "CEI", "CAIC", "CIEP", "CTISP", "CTPM", "IFES", "IFSP", "IF", "UFSC", "UFMG", "UFRJ", "USP", "II", "III", "IV", "V", "VI", "UE", "ETE", "ETEC", "EEB", "EB", "EJA", "CEPI", "CEMTI", "CMPM", "CPM", "SESI", "SENAI", "PM", "DF", "RJ", "SP", "MG"}


def nome_escola(nome) -> str:
    """O INEP escreve em MAIÚSCULAS e sem acento: vira 'Escola Estadual de ...', mantendo as siglas (EEEFM, CED...)."""
    t = str(nome or "").strip()
    if not t.isupper():
        return t
    pal = []
    for i, w in enumerate(t.split()):
        pal.append(w if w in _SIGLAS or not re.search(r"[AEIOU]", w) else w.lower() if (w in _MIUDAS and i) else w.capitalize())
    return " ".join(pal)


def _tira_nota(txt) -> str:
    return re.sub(r"\s*\(\d+\)", "", str(txt or "")).strip()


def _sem_nulos(d: dict) -> dict:
    return {str(a): v for a, v in sorted(d.items()) if v is not None}


def ler_ufs(ano: int) -> tuple[dict, dict, dict]:
    """({etapa: {UF: {ano: ideb}}}, {etapa: {ano: ideb do Brasil, se a aba trouxer}}, {etapa: {ano: meta do Brasil}}) da rede Total."""
    wb = abrir_xlsx(baixar(f"divulgacao_regioes_ufs_ideb_{ano}.zip"))
    ufs, brasil, metas = {}, {}, {}
    for etapa, (sigla, _) in ETAPAS.items():
        ws = next(w for w in wb.worksheets if f"({sigla})" in w.title)
        ufs[etapa], brasil[etapa], metas[etapa] = {}, {}, {}
        for (reg, rede), o, p in linhas_da_aba(ws, 2):
            if not str(_tira_nota(rede)).lower().startswith("total"):
                continue
            nome = sem_acento(_tira_nota(reg))
            if nome == "BRASIL":
                brasil[etapa], metas[etapa] = _sem_nulos(o), _sem_nulos(p)
            elif nome in NOME_PARA_UF or nome in ABREVIADOS:
                ufs[etapa][NOME_PARA_UF.get(nome) or ABREVIADOS[nome]] = _sem_nulos(o)
    return ufs, brasil, metas


def ler_brasil(ano: int) -> tuple[dict, dict]:
    wb = abrir_xlsx(baixar(f"divulgacao_brasil_ideb_{ano}.xlsx"))
    brasil, metas = {}, {}
    for etapa, (sigla, _) in ETAPAS.items():
        ws = next(w for w in wb.worksheets if f"({'Anos Iniciais' if sigla == 'AI' else 'Anos Finais' if sigla == 'AF' else 'EM'})" in w.title)
        for (_, rede), o, p in linhas_da_aba(ws, 2):
            if str(_tira_nota(rede)).lower().startswith("total"):
                brasil[etapa], metas[etapa] = _sem_nulos(o), _sem_nulos(p)
    return brasil, metas


def montar_ideb(ufs: dict, brasil: dict, metas: dict, ano: int) -> dict:
    """Formato de `app.ensino`: {ano, brasil: {etapa: {ano: ideb}}, ufs: {UF: {etapa: {ano: ideb}}}, metas: {etapa: {ano: meta}}}."""
    por_uf: dict[str, dict] = {}
    for etapa, d in ufs.items():
        for uf, serie in d.items():
            if serie:
                por_uf.setdefault(uf, {})[etapa] = serie
    return {"ano": ano, "brasil": {e: s for e, s in brasil.items() if s}, "ufs": por_uf, "metas": {e: m for e, m in metas.items() if m}}


def ler_escolas(etapa: str, ano: int) -> list[dict]:
    """Escolas com IDEB no último ano da planilha, as melhores de cada estado (ESCOLAS_POR_UF), da maior nota para a menor."""
    wb = abrir_xlsx(baixar(f"divulgacao_{ETAPAS[etapa][1]}_escolas_{ano}.zip"))
    ws = wb.worksheets[0]
    achadas, total = [], 0
    for (uf, cod_mun, mun, cod_esc, nome, rede), o, _ in linhas_da_aba(ws, 6):
        total += 1
        v = o.get(ano)
        if v is not None and uf in UFS and nome:
            achadas.append({"codigo": str(cod_esc), "nome": nome_escola(nome), "uf": uf,
                            "municipio": str(mun).strip(), "rede": _tira_nota(rede), "ideb": round(v, 1)})
    if total < MINIMO_ESCOLAS[etapa]:
        raise RuntimeError(f"escolas {etapa}: só {total} linhas (esperado ≥ {MINIMO_ESCOLAS[etapa]:,}); nada foi gravado")
    por_uf: dict[str, list] = {}
    for e in sorted(achadas, key=lambda x: (-x["ideb"], x["nome"])):
        l = por_uf.setdefault(e["uf"], [])
        if len(l) < ESCOLAS_POR_UF:
            l.append(e)
    return sorted((e for l in por_uf.values() for e in l), key=lambda x: (-x["ideb"], x["nome"]))


def ultimo_ano_disponivel(nome_modelo: str, ate: int | None = None) -> int:
    """Último ano (de dois em dois) com o arquivo publicado; o IDEB sai nos anos ímpares."""
    ate = ate or date.today().year
    for ano in range(ate, 2014, -1):
        r = _tentar(lambda: cliente().head(BASE + nome_modelo.format(ano=ano)))
        if r.status_code == 200:
            return ano
    raise RuntimeError(f"INEP: nenhum arquivo {nome_modelo} encontrado")


def coletar_ensino_ideb():
    """IDEB do Brasil e dos estados por etapa, desde 2005, e as melhores escolas de cada estado (ano mais recente)."""
    with registrar_coleta("inep", "ideb") as (db, n):
        ano = ultimo_ano_disponivel("divulgacao_regioes_ufs_ideb_{ano}.zip")
        ufs, brasil, metas = ler_ufs(ano)
        for etapa, d in ufs.items():
            if len(d) < MINIMO_UFS:
                raise RuntimeError(f"IDEB {etapa}: vieram {len(d)} estados (esperado {MINIMO_UFS}); nada foi gravado")
        if not all(brasil.values()):  # a planilha de 2025 não traz o Brasil: usa a do último ano que tem
            try:
                ano_br = ultimo_ano_disponivel("divulgacao_brasil_ideb_{ano}.xlsx", ano)
                b, m = ler_brasil(ano_br)
                brasil = {e: brasil.get(e) or b.get(e, {}) for e in ETAPAS}
                metas = {e: metas.get(e) or m.get(e, {}) for e in ETAPAS}
                if ano_br < ano:
                    n.avisos.append(f"Brasil: a planilha mais nova do INEP é de {ano_br}; os estados vão até {ano}")
            except Exception as e:  # noqa: BLE001
                n.avisos.append(f"Brasil: {type(e).__name__}: {str(e)[:120]}")
        dados = montar_ideb(ufs, brasil, metas, ano)
        upsert(db, Registro, {"fonte": "inep", "tipo": "ensino_ideb", "chave": "BR"}, {"ano": ano, "titulo": "IDEB", "dados": dados})
        n += 1
        db.commit()
        escolas = {"ano": ano}
        for etapa in ETAPAS:
            try:
                escolas[etapa] = ler_escolas(etapa, ano)
            except Exception as e:  # noqa: BLE001 - uma etapa que falha não derruba o IDEB nem as outras
                n.avisos.append(f"escolas {etapa}: {type(e).__name__}: {str(e)[:150]}")
                log.warning("INEP escolas %s: %s", etapa, e)
        if any(escolas.get(e) for e in ETAPAS):
            upsert(db, Registro, {"fonte": "inep", "tipo": "ensino_escolas", "chave": "BR"}, {"ano": ano, "titulo": "IDEB das escolas", "dados": escolas})
            n += 1
    return n.itens
