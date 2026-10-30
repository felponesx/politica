"""DATASUS TabNet — leitos, UTI, médicos, óbitos infantis e nascidos vivos por estado (Ministério da Saúde).

O TabNet (http://tabnet.datasus.gov.br) monta tabelas a partir de um formulário. Pedimos `formato=prn` (texto com ponto e vírgula) por POST e lemos a
tabela. Só abre em http (não em https). Tabelas usadas (cada uma com o arquivo do mês ou do ano mais recente, lido do próprio formulário):
- CNES leitos de internação  `cnes/cnv/leiintbr.def`  (linha Unidade da Federação × coluna Especialidade; existentes e SUS);
- CNES leitos complementares `cnes/cnv/leiutibr.def`  (UTI e unidades intermediárias, por tipo; existentes e SUS);
- CNES profissionais         `cnes/cnv/prid02br.def`  (indivíduos por CBO; só as ocupações de médico);
- SIM óbitos infantis        `sim/cnv/inf10uf.def`    (por ano, residência da mãe);
- SINASC nascidos vivos      `sinasc/cnv/nvuf.def`    (por ano, residência da mãe);
- SIM todos os óbitos        `sim/cnv/obt10uf.def`    (estado × capítulo da CID-10, residência);
- SIH internações do SUS     `sih/cnv/nruf.def`       (por estado de residência, 12 arquivos mensais do último ano completo);
- SINAN dengue               `sinannet/cnv/denguebbr.def` (casos prováveis por ano de notificação e estado de residência).
Taxa de mortalidade infantil = óbitos de menores de 1 ano ÷ nascidos vivos × 1.000, por ano; só entra ano com nascimentos completos (≥ 85% do ano anterior),
porque os arquivos mais novos são parciais.
"""
import html
import logging
import random
import re
import time
import urllib.parse
from datetime import date

import httpx

from app import http
from app.collectors.base import registrar_coleta
from app.models import Registro
from app.utils import UF_POR_CODIGO_IBGE, upsert

log = logging.getLogger("brasilplus.datasus")
BASE = "http://tabnet.datasus.gov.br/cgi"
UA = {"User-Agent": "Mozilla/5.0 (BRASIL+ coletor de dados publicos)", "Content-Type": "application/x-www-form-urlencoded"}
ANO_INICIAL = 2010
MEDICOS_CHAVE = ("Médico",)


def _tentar(fn, vezes: int = 3):
    for i in range(1, vezes + 1):
        try:
            return fn()
        except (httpx.TransportError, httpx.HTTPStatusError) as e:
            if i == vezes:
                raise
            pausa = 3 * i * (0.5 + random.random())
            log.warning("TabNet: %s; nova tentativa em %.0fs", type(e).__name__, pausa)
            time.sleep(pausa)


def _post(caminho: str, dados: list[tuple[str, str]]) -> str:
    corpo = urllib.parse.urlencode(dados, encoding="latin-1")

    def go():
        r = http._cliente.post(f"{BASE}/tabcgi.exe?{caminho}", content=corpo, headers=UA, timeout=180)
        r.raise_for_status()
        return r.content.decode("latin-1", errors="replace")
    return _tentar(go)


def _get(caminho: str) -> str:
    def go():
        r = http._cliente.get(f"{BASE}/deftohtm.exe?{caminho}", headers={"User-Agent": UA["User-Agent"]}, timeout=120)
        r.raise_for_status()
        return r.content.decode("latin-1", errors="replace")
    return _tentar(go)


def arquivos_disponiveis(caminho: str) -> list[str]:
    """Nomes dos arquivos (do mais novo para o mais velho) que o formulário oferece, ex.: ['ltbr2609.dbf', 'ltbr2608.dbf', ...]."""
    pag = _get(caminho)
    m = re.search(r'<select[^>]*name="?Arquivos"?[^>]*>(.*?)</select>', pag, re.I | re.S)
    return re.findall(r'<option[^>]*value="?([^">]+\.dbf)"?', m.group(1), re.I) if m else []


def tabela(texto: str) -> list[list[str]]:
    """Linhas "a";"b";"c" do resultado do TabNet, já sem aspas. A primeira é o cabeçalho."""
    linhas = html.unescape(re.sub(r"<[^>]+>", "\n", texto)).split("\n")
    return [[c.strip().strip('"') for c in l.strip().split(";")] for l in linhas if l.strip().startswith('"') and ";" in l]


def consultar(caminho: str, linha: str, coluna: str, incremento: str, arquivos: list[str]) -> list[list[str]]:
    dados = [("Linha", linha), ("Coluna", coluna), ("Incremento", incremento), *[("Arquivos", a) for a in arquivos], ("formato", "prn"), ("mostre", "Mostra")]
    return tabela(_post(caminho, dados))


def numero(txt: str) -> int | float:
    t = (txt or "").strip()
    if t in ("", "-"):
        return 0
    try:
        return int(t.replace(".", "")) if "," not in t else float(t.replace(".", "").replace(",", "."))
    except ValueError:
        return 0


def por_uf(linhas: list[list[str]]) -> tuple[dict[str, dict], dict]:
    """({UF: {coluna: valor}}, {coluna: valor do total}). A primeira coluna é "11 Rondônia"; a linha "Total" vai à parte."""
    cab = linhas[0][1:]
    ufs, total = {}, {}
    for l in linhas[1:]:
        valores = {c: numero(v) for c, v in zip(cab, l[1:])}
        m = re.match(r"(\d{2})\b", l[0])
        if m and int(m.group(1)) in UF_POR_CODIGO_IBGE:
            ufs[UF_POR_CODIGO_IBGE[int(m.group(1))]] = valores
        elif l[0].strip().lower() == "total":
            total = valores
    return ufs, total


def competencia(arquivo: str) -> str:
    """'ltbr2609.dbf' -> '2026-09'."""
    m = re.search(r"(\d{2})(\d{2})\.dbf$", arquivo)
    return f"20{m.group(1)}-{m.group(2)}" if m else arquivo


def _exige_ufs(ufs: dict, nome: str):
    if len(ufs) != 27:
        raise RuntimeError(f"{nome}: vieram {len(ufs)} estados (esperado 27); nada foi gravado")


def ler_leitos(arquivo_int: str | None = None, arquivo_uti: str | None = None) -> dict[str, dict]:
    """{UF: {competencia, internacao: {especialidade: n}, internacao_sus, uti: {tipo: n}, uti_sus, ...}} no mês mais recente do CNES."""
    out: dict[str, dict] = {}
    ai = arquivo_int or arquivos_disponiveis("cnes/cnv/leiintbr.def")[0]
    au = arquivo_uti or arquivos_disponiveis("cnes/cnv/leiutibr.def")[0]
    for chave, caminho, coluna, arq in (("internacao", "cnes/cnv/leiintbr.def", "Especialidade", ai), ("uti", "cnes/cnv/leiutibr.def", "Leitos_complementares", au)):
        for incr, sufixo in (("Quantidade_existente", ""), ("Quantidade_SUS", "_sus")):
            ufs, _ = por_uf(consultar(caminho, "Unidade_da_Federação", coluna, incr, [arq]))
            _exige_ufs(ufs, f"leitos {chave}")
            for uf, v in ufs.items():
                e = out.setdefault(uf, {"competencia_internacao": competencia(ai), "competencia_uti": competencia(au)})
                e[chave + sufixo] = {k: int(x) for k, x in v.items()}
    return out


def ler_medicos(arquivo: str | None = None) -> dict[str, dict]:
    arq = arquivo or arquivos_disponiveis("cnes/cnv/prid02br.def")[0]
    ufs, _ = por_uf(consultar("cnes/cnv/prid02br.def", "Unidade_da_Federação", "Médicos", "Quantidade", [arq]))
    _exige_ufs(ufs, "médicos")
    return {uf: {"competencia": competencia(arq), "total": int(v.get("Total", 0)), "por_cbo": {k: int(x) for k, x in v.items() if k != "Total" and x}}
            for uf, v in ufs.items()}


def ler_mortalidade_infantil(ano_final: int | None = None) -> dict[str, dict]:
    """{UF ou 'BR': {serie: {ano: {obitos, nascidos, taxa}}, ultimo_ano}}; só anos com nascimentos completos."""
    ano_final = ano_final or date.today().year
    anos = list(range(ANO_INICIAL, ano_final + 1))
    obs, nas = {}, {}
    for caminho, coluna, incr, prefixo, destino in (("sim/cnv/inf10uf.def", "Ano_do_Óbito", "Óbitos_p/Residênc", "infuf", obs),
                                                     ("sinasc/cnv/nvuf.def", "Ano_do_nascimento", "Nascim_p/resid.mãe", "nvuf", nas)):
        existentes = set(arquivos_disponiveis(caminho))
        pedidos = [f"{prefixo}{a % 100:02d}.dbf" for a in anos if f"{prefixo}{a % 100:02d}.dbf" in existentes]
        linhas = consultar(caminho, "Unidade_da_Federação", coluna, incr, pedidos)
        ufs, total = por_uf(linhas)
        _exige_ufs(ufs, "óbitos infantis" if prefixo == "infuf" else "nascidos vivos")
        destino.update({uf: {a: int(v) for a, v in d.items() if a.isdigit()} for uf, d in ufs.items()})
        destino["BR"] = {a: int(v) for a, v in total.items() if a.isdigit()}
    nb = nas["BR"]
    validos = [a for a in sorted(nb) if (int(a) == ANO_INICIAL or nb[a] >= 0.85 * nb.get(str(int(a) - 1), 0)) and nb[a] > 0]
    # o SIM e o SINASC mais novos são preliminares (o Ministério fecha cerca de dois anos depois): a série oficial vai até ano_final - 2
    finais = [a for a in validos if int(a) <= ano_final - 2]
    out = {}
    for uf in obs:
        def ponto(a):
            return {"obitos": obs[uf].get(a, 0), "nascidos": nas[uf].get(a, 0), "taxa": round(obs[uf].get(a, 0) / nas[uf][a] * 1000, 2)}
        serie = {a: ponto(a) for a in finais if nas[uf].get(a)}
        if serie:
            out[uf] = {"serie": serie, "ultimo_ano": max(serie)}
            if uf == "BR":
                out[uf]["preliminar"] = {a: ponto(a) for a in validos if a not in finais and nas[uf].get(a)}
    return out


def ler_causas_morte(ano_final: int | None = None) -> dict[str, dict]:
    """{UF ou 'BR': {ano, total, capitulos: {'Cap IX': n}}} no último ano com óbitos fechados (ano_final - 2), pela residência."""
    ano_final = ano_final or date.today().year
    existentes = set(arquivos_disponiveis("sim/cnv/obt10uf.def"))
    ano = next((a for a in range(ano_final - 2, ANO_INICIAL - 1, -1) if f"obtuf{a % 100:02d}.dbf" in existentes), None)
    if ano is None:
        raise RuntimeError("causas de morte: nenhum arquivo do SIM encontrado")
    ufs, total = por_uf(consultar("sim/cnv/obt10uf.def", "Unidade_da_Federação", "Capítulo_CID-10", "Óbitos_p/Residênc", [f"obtuf{ano % 100:02d}.dbf"]))
    _exige_ufs(ufs, "causas de morte")

    def reg(v):
        return {"ano": ano, "total": int(v.get("Total", 0)), "capitulos": {k: int(x) for k, x in v.items() if k.startswith("Cap") and x}}
    out = {uf: reg(v) for uf, v in ufs.items()}
    out["BR"] = reg(total)
    return out


def ler_internacoes(ano_final: int | None = None) -> dict[str, dict]:
    """{UF ou 'BR': {ano, internacoes, valor_total, obitos, dias}} do SUS no último ano com os 12 meses processados (por residência do paciente)."""
    ano_final = ano_final or date.today().year
    existentes = set(arquivos_disponiveis("sih/cnv/nruf.def"))
    ano = next((a for a in range(ano_final, ANO_INICIAL - 1, -1) if all(f"nruf{a % 100:02d}{m:02d}.dbf" in existentes for m in range(1, 13))), None)
    if ano is None:
        raise RuntimeError("internações: nenhum ano completo no SIH")
    arqs = [f"nruf{ano % 100:02d}{m:02d}.dbf" for m in range(1, 13)]
    out: dict[str, dict] = {}
    for campo, incr in (("internacoes", "Internações"), ("valor_total", "Valor_total"), ("obitos", "Óbitos"), ("dias", "Dias_permanência")):
        ufs, total = por_uf(consultar("sih/cnv/nruf.def", "Unidade_da_Federação", "--Não-Ativa--", incr, arqs))
        _exige_ufs(ufs, f"internações {campo}")
        for uf, v in {**ufs, "BR": total}.items():
            out.setdefault(uf, {"ano": ano})[campo] = next(iter(v.values()), 0) if v else 0
    return out


def ler_dengue(ano_final: int | None = None) -> dict[str, dict]:
    """{UF ou 'BR': {serie: {ano: casos prováveis}, parcial: {ano: casos}}}: anos fechados até ano_final - 1; o ano corrente fica em `parcial`."""
    ano_final = ano_final or date.today().year
    existentes = set(arquivos_disponiveis("sinannet/cnv/denguebbr.def"))
    arqs = [f"dengbr{a % 100:02d}.dbf" for a in range(2014, ano_final + 1) if f"dengbr{a % 100:02d}.dbf" in existentes]
    if not arqs:
        raise RuntimeError("dengue: nenhum arquivo do SINAN encontrado")
    ufs, total = por_uf(consultar("sinannet/cnv/denguebbr.def", "UF_de_residência", "Ano_notificação", "Casos_Prováveis", arqs))
    _exige_ufs(ufs, "dengue")
    out = {}
    for uf, v in {**ufs, "BR": total}.items():
        anos = {a: int(x) for a, x in v.items() if a.isdigit() and 2014 <= int(a)}
        out[uf] = {"serie": {a: x for a, x in anos.items() if int(a) < ano_final}, "parcial": {a: x for a, x in anos.items() if int(a) >= ano_final}}
    return out


def _gravar(db, tipo: str, dados: dict, n):
    for chave, d in dados.items():
        upsert(db, Registro, {"fonte": "datasus", "tipo": tipo, "chave": chave}, {"uf": None if chave == "BR" else chave, "titulo": f"{tipo} {chave}", "dados": d})
        n += 1
    db.commit()


def coletar_saude_datasus():
    """Leitos de internação e UTI, médicos, mortalidade infantil, causas de morte, internações do SUS e dengue por estado (DATASUS TabNet). Cada bloco é gravado só se vier completo."""
    with registrar_coleta("datasus", "saude") as (db, n):
        for tipo, fn in (("leitos_uf", ler_leitos), ("medicos_uf", ler_medicos), ("mortalidade_infantil_uf", ler_mortalidade_infantil),
                         ("causas_morte_uf", ler_causas_morte), ("internacoes_uf", ler_internacoes), ("dengue_uf", ler_dengue)):
            try:
                _gravar(db, tipo, fn(), n)
            except Exception as e:  # noqa: BLE001 - um bloco que falha não derruba os outros (a coleta fica "parcial")
                n.avisos.append(f"{tipo}: {type(e).__name__}: {str(e)[:150]}")
                log.warning("DATASUS %s: %s", tipo, e)
        if not n.itens:
            raise RuntimeError("; ".join(n.avisos) or "nenhum bloco do DATASUS foi lido")
    return n.itens
