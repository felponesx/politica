"""Segurança pública por estado.

- Sistema prisional — Sisdepen (Secretaria Nacional de Políticas Penais), base semestral por estabelecimento:
  https://www.gov.br/senappen/pt-br/servicos/sisdepen/bases-de-dados (CSV UTF-8, ';', ~1.700 colunas).
  Somamos por UF: população presa (em celas e em prisão domiciliar com tornozeleira), vagas, entradas no sistema
  (inclusões originárias), alvarás de soltura, saídas temporárias, abandonos (quem estava no semiaberto/aberto e não
  voltou, inclusive de saída temporária) e mortes. As colunas são achadas pelo nome, não pela posição.
"""
import csv
import io
import os
import re
import tempfile

from app import http
from app.collectors.base import registrar_coleta
from app.models import Registro
from app.utils import sem_acento, upsert

SISDEPEN_PAGINA = "https://www.gov.br/senappen/pt-br/servicos/sisdepen/bases-de-dados"
UA = {"User-Agent": "Mozilla/5.0 (BRASIL+ coletor de dados publicos)", "Accept": "*/*"}

# campo -> expressão sobre o cabeçalho normalizado (sem acento, minúsculo, espaços simples)
CAMPOS_SISDEPEN = {
    "populacao": r"^4\.1 populacao prisional \| total$",
    "vagas_masc": r"^1\.3 capacidade do estabelecimento \| masculino \| total$",
    "vagas_fem": r"^1\.3 capacidade do estabelecimento \| feminino \| total$",
    "entradas": r"^4\.5 movimentacao .*\| entradas \| numero de inclusoes originarias \| total$",
    "alvaras": r"^4\.5 movimentacao .*\| saidas \| alvaras de soltura \| total$",
    "abandonos": r"^4\.5 movimentacao .*\| saidas \| abandonos \| total$",
    "obitos": r"^4\.5 movimentacao .*\| saidas \| total de obitos \| total$",
    "saidas_temporarias": r"^4\.5 movimentacao .*\| autorizacoes de saida \| saida temporaria \| total$",
    "permissoes_saida": r"^4\.5 movimentacao .*\| autorizacoes de saida \| permissao de saida \| total$",
}


def _norm(h: str) -> str:
    return re.sub(r"\s+", " ", sem_acento(h or "").lower()).strip()


def _num(v) -> float:
    try:
        return float(str(v).replace(",", ".")) if str(v).strip() not in ("", "nan", "None") else 0.0
    except ValueError:
        return 0.0


def links_sisdepen(html: str) -> list[str]:
    """Links dos CSV da página de bases, do mais recente para o mais antigo (o ciclo vem no nome)."""
    achados = re.findall(r'href="([^"]*bases-de-dados/\d{4}/(\d+)o-ciclo[^"]*\.csv/@@download/file)"', html)
    unicos = {}
    for u, ciclo in achados:
        unicos.setdefault(int(ciclo), u if u.startswith("http") else "https://www.gov.br" + u)
    return [unicos[c] for c in sorted(unicos, reverse=True)]


def agregar_sisdepen(texto: str) -> dict:
    leitor = csv.reader(io.StringIO(texto), delimiter=";")
    cab = [_norm(c) for c in next(leitor)]
    pos = {}
    for campo, expr in CAMPOS_SISDEPEN.items():
        idx = [i for i, h in enumerate(cab) if re.search(expr, h)]
        if idx:
            pos[campo] = idx[0]
    i_uf = cab.index("uf")
    i_tipo = next((i for i, h in enumerate(cab) if h == "tipo do estabelecimento"), None)
    i_ref = next((i for i, h in enumerate(cab) if h == "referencia"), None)
    faltam = sorted(set(CAMPOS_SISDEPEN) - set(pos))
    por_uf, ref = {}, None
    for linha in leitor:
        if len(linha) <= i_uf or not linha[i_uf].strip():
            continue
        uf = linha[i_uf].strip().upper()[:2]
        ref = ref or (linha[i_ref].strip() if i_ref is not None and i_ref < len(linha) else None)
        a = por_uf.setdefault(uf, {"estabelecimentos": 0, "populacao_domiciliar": 0.0, **{c: 0.0 for c in pos}})
        a["estabelecimentos"] += 1
        for campo, i in pos.items():
            a[campo] += _num(linha[i]) if i < len(linha) else 0.0
        if i_tipo is not None and i_tipo < len(linha) and "domiciliar" in _norm(linha[i_tipo]) and "populacao" in pos:
            a["populacao_domiciliar"] += _num(linha[pos["populacao"]])
    for a in por_uf.values():
        a["vagas"] = a.pop("vagas_masc", 0.0) + a.pop("vagas_fem", 0.0)
        a["populacao_celas"] = a.get("populacao", 0.0) - a["populacao_domiciliar"]
        for k, v in list(a.items()):
            a[k] = int(round(v))
    return {"referencia": ref, "por_uf": por_uf, "colunas_faltando": faltam}


def coletar_sisdepen(arquivo_local: str | None = None, url: str | None = None, todos: bool = False):
    """Base mais recente do Sisdepen (ou `url`/`arquivo_local`), somada por estado. `todos`: todos os semestres."""
    if todos and not (arquivo_local or url):
        pagina = http._cliente.get(SISDEPEN_PAGINA, headers=UA, timeout=60)
        pagina.raise_for_status()
        total = 0
        for u in links_sisdepen(pagina.text):
            try:
                total += coletar_sisdepen(url=u)
            except Exception as e:  # um semestre com formato diferente não derruba os outros
                import logging
                logging.getLogger("brasilplus.seguranca").warning("Sisdepen %s: %s", u, e)
        return total
    with registrar_coleta("sisdepen", "prisional", url=url or "mais recente") as (db, n):
        if arquivo_local:
            bruto = open(arquivo_local, "rb").read()
        else:
            if not url:
                pagina = http._cliente.get(SISDEPEN_PAGINA, headers=UA, timeout=60)
                pagina.raise_for_status()
                lista = links_sisdepen(pagina.text)
                if not lista:
                    raise RuntimeError("Nenhum CSV do Sisdepen na página de bases de dados")
                url = lista[0]
            caminho = os.path.join(tempfile.gettempdir(), "sisdepen.csv")
            with http._cliente.stream("GET", url, headers=UA, timeout=None) as r:
                r.raise_for_status()
                with open(caminho, "wb") as f:
                    for b in r.iter_bytes(1 << 20):
                        f.write(b)
            bruto = open(caminho, "rb").read()
        texto = bruto.decode("utf-8-sig") if not bruto.startswith(b"\xff\xfe") else bruto.decode("utf-16")
        res = agregar_sisdepen(texto)
        if res["colunas_faltando"]:
            n.avisos.append("colunas não encontradas: " + ", ".join(res["colunas_faltando"]))
        ref = res["referencia"] or "?"
        ano = int(ref[:4]) if ref[:4].isdigit() else None
        for uf, dados in res["por_uf"].items():
            upsert(db, Registro, {"fonte": "sisdepen", "tipo": "prisional", "chave": f"{ref}-{uf}"},
                   {"uf": uf, "ano": ano, "titulo": f"Sistema prisional {uf} {ref}", "valor": dados.get("populacao"),
                    "dados": {**dados, "referencia": ref, "url": url}})
            n += 1
    return n.itens


# ---------------- Anuário Brasileiro de Segurança Pública (FBSP) ----------------
# Tabela 01 do Anuário: mortes violentas intencionais por UF, dois anos (números absolutos e taxa por 100 mil).
# Dados das secretarias estaduais de segurança, compilados pelo Fórum Brasileiro de Segurança Pública.
ANUARIO_PAGINA = "https://forumseguranca.org.br/publicacoes/anuario-brasileiro-de-seguranca-publica/"
T01_COLUNAS = [("homicidio_doloso", 1, "homic"), ("latrocinio", 3, "latroc"), ("lesao_morte", 5, "les"),
               ("policiais_mortos", 7, "policia"), ("mortes_intervencao", 9, "decorrente"), ("mvi", 11, "violentas"),
               ("taxa_mvi", 13, None)]


def ler_t01(linhas: list) -> dict:
    """{ano: {UF: {...}}} a partir das linhas da aba T01 (valores como vêm do openpyxl)."""
    from app.utils import para_uf
    ib = next(i for i, l in enumerate(linhas) if l and str(l[0] or "").strip() == "Brasil")
    cab = [l for l in linhas[:ib] if l and any(v not in (None, "") for v in l)][-4:]  # categoria, subcategoria, medida, ano
    anos_l = cab[-1]
    cats = [_norm(" ".join(str(cab[k][c] or "") if c < len(cab[k]) else "" for k in (1, 0))) for c in range(len(anos_l))]
    for campo, col, chave in T01_COLUNAS:  # confere o cabeçalho antes de confiar nas posições
        if chave and chave not in cats[col]:
            raise ValueError(f"Tabela 01 do Anuário mudou: coluna {col} = {cats[col]!r}, esperava {chave!r}")
    anos = [int(str(anos_l[c])[:4]) for c in (1, 2)]
    out = {a: {} for a in anos}
    for l in linhas[ib:]:
        nome = re.sub(r"\(\d+\)", "", str(l[0] or "")).strip()
        if nome.startswith(("Fonte", "Nota")):
            break
        uf = "BR" if nome == "Brasil" else para_uf(nome) if nome else None
        if not uf or not any(isinstance(v, (int, float)) for v in l[1:]):  # linhas em branco, regiões, notas
            continue
        for k, ano in enumerate(anos):
            d = {}
            for campo, col, _ in T01_COLUNAS:
                v = l[col + k]
                d[campo] = None if v in (None, "", "-", "...") else (round(float(v), 2) if campo == "taxa_mvi" else int(float(v)))
            out[ano][uf] = d
    return out


def coletar_anuario(arquivo_local: str | None = None, url: str | None = None, todas: bool = False):
    """Mortes violentas intencionais por estado (Tabela 01 do Anuário mais recente). `todas`: todas as edições
    publicadas em planilha (cada uma traz dois anos)."""
    import openpyxl
    if todas and not (arquivo_local or url):
        pagina = http._cliente.get(ANUARIO_PAGINA, headers=UA, timeout=60)
        pagina.raise_for_status()
        urls = sorted(set(re.findall(r'(https://[^"]+/anuario-\d{4}\.xlsx)', pagina.text)))
        total = 0
        for u in urls:  # da mais antiga para a mais nova: a edição nova corrige os números do ano anterior
            try:
                total += coletar_anuario(url=u)
            except Exception as e:
                import logging
                logging.getLogger("brasilplus.seguranca").warning("Anuário %s: %s", u, e)
        return total
    with registrar_coleta("fbsp", "anuario", url=url or "mais recente") as (db, n):
        if arquivo_local:
            bruto = open(arquivo_local, "rb").read()
        else:
            if not url:
                pagina = http._cliente.get(ANUARIO_PAGINA, headers=UA, timeout=60)
                pagina.raise_for_status()
                urls = re.findall(r'(https://[^"]+/anuario-\d{4}\.xlsx)', pagina.text)
                if not urls:
                    raise RuntimeError("Planilha do Anuário não encontrada na página do FBSP")
                url = sorted(urls, key=lambda u: re.search(r"(\d{4})\.xlsx", u).group(1))[-1]
            r = http._cliente.get(url, headers=UA, timeout=120)
            r.raise_for_status()
            bruto = r.content
        wb = openpyxl.load_workbook(io.BytesIO(bruto), read_only=True, data_only=True)
        dados = ler_t01(list(wb["T01"].iter_rows(values_only=True)))
        edicao = re.search(r"(\d{4})\.xlsx", url or "") and re.search(r"(\d{4})\.xlsx", url).group(1)
        for ano, por_uf in dados.items():
            for uf, d in por_uf.items():
                upsert(db, Registro, {"fonte": "fbsp", "tipo": "violencia", "chave": f"{ano}-{uf}"},
                       {"uf": uf, "ano": ano, "titulo": f"Mortes violentas {uf} {ano}", "valor": d.get("mvi"),
                        "dados": {**d, "edicao": edicao, "url": url}})
                n += 1
    return n.itens


# ---------------- Sinesp VDE (Ministério da Justiça) ----------------
# Base mensal por município, enviada pelas secretarias estaduais: uf, municipio, evento, data_referencia, ...,
# total_vitima (eventos com vítima), total (ocorrências e apreensões). Uma planilha por ano.
SINESP_URL = ("https://www.gov.br/mj/pt-br/assuntos/sua-seguranca/seguranca-publica/estatistica/download/"
              "dnsp-base-de-dados/bancovde-{ano}.xlsx/@@download/file")
EVENTOS_SINESP = {
    "homicidio doloso": "homicidio_doloso",
    "feminicidio": "feminicidio",
    "roubo seguido de morte (latrocinio)": "latrocinio",
    "lesao corporal seguida de morte": "lesao_morte",
    "morte por intervencao de agente do estado": "mortes_intervencao",
    "morte de agente do estado": "agentes_mortos",
    "tentativa de homicidio": "tentativa_homicidio",
    "mandado de prisao cumprido": "mandados_cumpridos",
    "pessoa desaparecida": "desaparecidos",
    "pessoa localizada": "localizados",
    "arma de fogo apreendida": "armas_apreendidas",
    "estupro": "estupro",
    "estupro de vulneravel": "estupro_vulneravel",
    "roubo de veiculo": "roubo_veiculo",
    "furto de veiculo": "furto_veiculo",
    "roubo de carga": "roubo_carga",
    "trafico de drogas": "trafico_drogas",
}


def agregar_sinesp(linhas) -> dict:
    """{uf: {"AAAA-MM": {evento: n}}} a partir das linhas da planilha (a primeira é o cabeçalho).
    Para cada evento vale a soma de total_vitima; se o evento não tem vítimas (apreensões, mandados), a de total."""
    it = iter(linhas)
    cab = [_norm(str(c or "")) for c in next(it)]
    i = {c: cab.index(c) for c in ("uf", "evento", "data_referencia", "total_vitima", "total") if c in cab}
    if not {"uf", "evento", "data_referencia"} <= set(i):
        raise ValueError(f"Planilha do Sinesp mudou: cabeçalho {cab}")
    vit, tot = {}, {}
    for l in it:
        uf = str(l[i["uf"]] or "").strip().upper()
        ev = EVENTOS_SINESP.get(_norm(str(l[i["evento"]] or "")))
        dt = l[i["data_referencia"]]
        if len(uf) != 2 or not ev or dt is None:
            continue
        mes = dt.strftime("%Y-%m") if hasattr(dt, "strftime") else str(dt)[:7]
        k = (uf, mes, ev)
        for alvo, col in ((vit, "total_vitima"), (tot, "total")):
            v = l[i[col]] if col in i and i[col] < len(l) else None
            if isinstance(v, (int, float)):
                alvo[k] = alvo.get(k, 0) + v
    eventos_com_vitima = {k[2] for k, v in vit.items() if v}
    out = {}
    for k in set(vit) | set(tot):
        uf, mes, ev = k
        v = vit.get(k, 0) if ev in eventos_com_vitima else tot.get(k, 0)
        out.setdefault(uf, {}).setdefault(mes, {})[ev] = int(round(v))
    return out


def coletar_sinesp(ano: int | None = None, arquivo_local: str | None = None):
    """Ocorrências do Sinesp VDE por estado e mês (ano corrente por padrão; se ainda não publicado, o anterior)."""
    import datetime as _dt
    import openpyxl
    ano = int(ano) if ano else _dt.date.today().year
    with registrar_coleta("sinesp", "vde", ano=ano) as (db, n):
        if arquivo_local:
            bruto = open(arquivo_local, "rb").read()
        else:
            r = http._cliente.get(SINESP_URL.format(ano=ano), headers=UA, timeout=300, follow_redirects=True)
            r.raise_for_status()
            bruto = r.content
        wb = openpyxl.load_workbook(io.BytesIO(bruto), read_only=True, data_only=True)
        por_uf = agregar_sinesp(wb.worksheets[0].iter_rows(values_only=True))
        if not por_uf:
            raise RuntimeError("Planilha do Sinesp sem linhas reconhecidas")
        for uf, meses in por_uf.items():
            totais = {}
            for m in meses.values():
                for ev, v in m.items():
                    totais[ev] = totais.get(ev, 0) + v
            upsert(db, Registro, {"fonte": "sinesp", "tipo": "vde", "chave": f"{ano}-{uf}"},
                   {"uf": uf, "ano": ano, "titulo": f"Sinesp {uf} {ano}", "valor": totais.get("homicidio_doloso"),
                    "dados": {"meses": dict(sorted(meses.items())), "totais": totais,
                              "primeiro_mes": min(meses), "ultimo_mes": max(meses),
                              "url": SINESP_URL.format(ano=ano) if not arquivo_local else None}})
            n += 1
    return n.itens


# ---------------- Raio-X das Forças de Segurança Pública (FBSP) ----------------
# Tabela 02: efetivo da ativa por UF (PM, bombeiros, Polícia Civil, perícia, Polícia Penal, guardas municipais) e os
# totais federais (PF, PRF, Polícia Penal Federal, Polícia Legislativa). Tabelas 03 a 05: efetivo previsto em lei.
RAIOX_PAGINA = "https://forumseguranca.org.br/publicacoes/raio-x-das-forcas-de-seguranca-publica-do-brasil-{ano}/"
RAIOX_COLUNAS = [("policia_militar", r"policia militar"), ("bombeiros", r"bombeiro"), ("policia_civil", r"policia civil"),
                 ("pericia", r"pericia"), ("policia_penal_federal", r"penal federal"), ("policia_penal", r"policia penal"),
                 ("policia_federal", r"policia federal"), ("prf", r"rodoviaria"), ("policia_legislativa", r"legislativa"),
                 ("guardas_municipais", r"guarda"), ("total", r"^total")]


def _valor_tabela(v):
    if v in (None, "", "...", "…"):
        return None
    if v == "-":
        return 0
    try:
        return int(round(float(v)))
    except (TypeError, ValueError):
        return None


def _linhas_uf(linhas, desde):
    """(uf, linha) das linhas de estado (e "BR") depois do cabeçalho, até a fonte/notas."""
    from app.utils import para_uf
    for l in linhas[desde:]:
        nome = re.sub(r"\(\d+\)", "", str(l[0] or "")).strip()
        if not nome:
            continue
        if nome.startswith(("Fonte", "(")):
            break
        uf = "BR" if nome == "Brasil" else para_uf(nome)
        if uf:
            yield uf, l


def ler_raiox_t02(linhas: list) -> tuple[int | None, dict]:
    """(ano, {UF: {força: efetivo}}) da Tabela 02 do Raio-X."""
    ano = next((int(m.group(1)) for l in linhas[:6] for v in l if v
                for m in [re.search(r"Federa..o\s*-\s*(\d{4})", str(v))] if m), None)
    ic = next(i for i, l in enumerate(linhas) if l and any("militar" in _norm(str(v or "")) for v in l))
    cab = [_norm(str(v or "")) for v in linhas[ic]]
    pos = {}
    for c, h in enumerate(cab[1:], 1):
        h = re.sub(r"\(\d+\)", "", h).strip()
        campo = next((k for k, expr in RAIOX_COLUNAS if re.search(expr, h)), None)
        if campo and campo not in pos:
            pos[campo] = c
    if not {"policia_militar", "policia_civil", "total"} <= set(pos):
        raise ValueError(f"Tabela 02 do Raio-X mudou: {cab}")
    out = {uf: {k: _valor_tabela(l[c]) if c < len(l) else None for k, c in pos.items()}
           for uf, l in _linhas_uf(linhas, ic + 1)}
    return ano, out


def ler_raiox_previsto(linhas: list) -> dict:
    """{UF: (previsto, existente)} das Tabelas 03 a 05."""
    ic = next(i for i, l in enumerate(linhas) if l and any("previsto" in _norm(str(v or "")) for v in l))
    return {uf: (_valor_tabela(l[1]), _valor_tabela(l[2])) for uf, l in _linhas_uf(linhas, ic + 1)}


def coletar_raiox(ano: int | None = None, arquivo_local: str | None = None, url: str | None = None):
    """Efetivo das forças de segurança por estado (Raio-X do FBSP mais recente, ou `ano`)."""
    import datetime as _dt
    import openpyxl
    with registrar_coleta("fbsp", "efetivo", ano=ano or "mais recente") as (db, n):
        if arquivo_local:
            bruto = open(arquivo_local, "rb").read()
        else:
            if not url:
                for a in ([int(ano)] if ano else range(_dt.date.today().year, _dt.date.today().year - 4, -1)):
                    p = http._cliente.get(RAIOX_PAGINA.format(ano=a), headers=UA, timeout=60, follow_redirects=True)
                    achados = re.findall(r'(https://[^"\' ]+raio-x[^"\' ]*\.xlsx)', p.text) if p.status_code == 200 else []
                    if achados:
                        url = achados[0]
                        break
                if not url:
                    raise RuntimeError("Planilha do Raio-X das Forças de Segurança não encontrada")
            r = http._cliente.get(url, headers=UA, timeout=120, follow_redirects=True)
            r.raise_for_status()
            bruto = r.content
        wb = openpyxl.load_workbook(io.BytesIO(bruto), read_only=True, data_only=True)
        ano_dados, por_uf = ler_raiox_t02(list(wb["T02"].iter_rows(values_only=True)))
        previsto = {}
        for aba, forca in (("T03", "policia_militar"), ("T04", "policia_civil"), ("T05", "policia_penal")):
            try:
                for uf, (prev, _) in ler_raiox_previsto(list(wb[aba].iter_rows(values_only=True))).items():
                    previsto.setdefault(uf, {})[forca] = prev
            except (KeyError, StopIteration):
                n.avisos.append(f"aba {aba} (efetivo previsto) não encontrada")
        for uf, d in por_uf.items():
            upsert(db, Registro, {"fonte": "fbsp", "tipo": "efetivo", "chave": f"{ano_dados}-{uf}"},
                   {"uf": uf, "ano": ano_dados, "titulo": f"Efetivo das forças de segurança {uf} {ano_dados}",
                    "valor": d.get("total"), "dados": {**d, "previsto": previsto.get(uf, {}), "url": url}})
            n += 1
    return n.itens
