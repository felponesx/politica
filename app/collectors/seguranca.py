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


def coletar_sisdepen(arquivo_local: str | None = None, url: str | None = None):
    """Base mais recente do Sisdepen (ou `url`/`arquivo_local`), somada por estado."""
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
        if not nome or nome.startswith(("Fonte", "(")):
            break
        uf = "BR" if nome == "Brasil" else para_uf(nome)
        if not uf:
            continue
        for k, ano in enumerate(anos):
            d = {}
            for campo, col, _ in T01_COLUNAS:
                v = l[col + k]
                d[campo] = None if v in (None, "", "-", "...") else (round(float(v), 2) if campo == "taxa_mvi" else int(float(v)))
            out[ano][uf] = d
    return out


def coletar_anuario(arquivo_local: str | None = None, url: str | None = None):
    """Mortes violentas intencionais por estado (Tabela 01 do Anuário mais recente)."""
    import openpyxl
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
