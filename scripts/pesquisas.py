"""Pesquisas financiadas com dinheiro público (aba "Pesquisas").

Uso:
    python -m scripts.pesquisas               # baixa as fontes abertas e grava app/dados/pesquisas.json
    python -m scripts.pesquisas --arquivos DIR   # usa arquivos já baixados em DIR (testes e reprocessamento)

Fontes (conferidas com os arquivos reais em 25/11/2026; ver docs/PESQUISAS_FONTES.md):
  * FAPEMIG (MG): projetos-contratados.xlsx + instituicoescadastradas.xlsx (dados abertos da fundação, publicação trimestral).
    Valor = CONTRATADO (não é valor pago). Coordenador = nome que a própria FAPEMIG publica.
  * INT (RJ, MCTI): listas anuais de projetos de P&D contratados (cliente governo e cliente empresa), 2022–2025.
    Valor = PACTUADO no contrato; é dinheiro que o INT recebe do cliente. Sem nome de pesquisador na fonte.

  * FINEP (federal): Contratacao.xlsx, aba "Projetos Não Reembolsável ICTs" (projetos contratados com instituições de ciência e tecnologia: universidades, institutos).
    Valor = CONTRATADO (Valor Finep) e, nesta fonte, também o LIBERADO (Valor Pago = soma do que a FINEP já repassou ao projeto, na "posição" da planilha). Sem nome de pesquisador.

Regras: nada é estimado nem completado; campo ausente fica nulo ("não informado" na tela); nome de pessoa só o que a fonte publica;
o estado de uma instituição vem do cadastro da própria fonte (FAPEMIG) ou da sede do INT (Rio de Janeiro); nunca ligamos projetos por nome parecido.
Não guardamos a planilha de bolsas de cota (nomes de estudantes): não é projeto de pesquisa.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import sys
import time
import unicodedata
from datetime import date, datetime
from pathlib import Path

import httpx
import openpyxl

RAIZ = Path(__file__).resolve().parent.parent
SAIDA = RAIZ / "app" / "dados" / "pesquisas.json"
UA = {"User-Agent": "Mozilla/5.0 (compatible; BRASILMais/1.0; dados abertos)"}

FAPEMIG_PAGINA = "https://fapemig.br/difusao-do-conhecimento/fapemig-em-numeros/dados-abertos-fapemig"
FAPEMIG_ARQ = {
    "projetos": "https://api.site.fapemig.br/wp-content/uploads/projetos-contratados.xlsx",
    "instituicoes": "https://api.site.fapemig.br/wp-content/uploads/instituicoescadastradas.xlsx",
}
INT_PAGINA = "https://www.gov.br/int/pt-br/acesso-a-informacao/dados-abertos"
_INT = "https://www.gov.br/int/pt-br/acesso-a-informacao"
INT_ARQ = [  # (ano, cliente, endereço)
    (2025, "governo", f"{_INT}/arquivos/2025-lista-de-projetos-de-p-d-contratados-cujo-cliente-seja-governo-e-suas-esferas.xlsx/@@download/file"),
    (2025, "empresa", f"{_INT}/arquivos/2025-lista-de-projetos-de-p-d-contratados-cujo-cliente-seja-empresa.xlsx/@@download/file"),
    (2024, "governo", f"{_INT}/arquivos%20dados%20abertos/2024-projetos-de-p-d-com-cliente-governo-contratados-no-ano.xlsx/@@download/file"),
    (2024, "empresa", f"{_INT}/arquivos%20dados%20abertos/2024-projetos-de-p-d-com-cliente-empresa-contratados-no-ano.xlsx/@@download/file"),
    (2023, "misto", f"{_INT}/2023-projetos-de-p-d-contratados-no-ano.xlsx/@@download/file"),
    (2022, "governo", f"{_INT}/2022-projetos-de-p-d-contratados-cujo-cliente-seja-governo-e-suas-esferas.xlsx/@@download/file"),
    (2022, "empresa", f"{_INT}/2022-projetos-de-p-d-contratados-cujo-cliente-seja-empresa.xlsx/@@download/file"),
]

FINEP_PAGINA = "https://legacy.finep.gov.br/transparencia-finep/paineis-e-downloads/central-de-downloads"
FINEP_ARQ = "https://download.finep.gov.br/Contratacao.xlsx"
FINEP_ABA = "Projetos_Não_Reembolsavel_ICTs"

UFS = {"ACRE": "AC", "ALAGOAS": "AL", "AMAPA": "AP", "AMAZONAS": "AM", "BAHIA": "BA", "CEARA": "CE", "DISTRITO FEDERAL": "DF", "ESPIRITO SANTO": "ES", "GOIAS": "GO",
       "MARANHAO": "MA", "MATO GROSSO": "MT", "MATO GROSSO DO SUL": "MS", "MINAS GERAIS": "MG", "PARA": "PA", "PARAIBA": "PB", "PARANA": "PR", "PERNAMBUCO": "PE",
       "PIAUI": "PI", "RIO DE JANEIRO": "RJ", "RIO GRANDE DO NORTE": "RN", "RIO GRANDE DO SUL": "RS", "RONDONIA": "RO", "RORAIMA": "RR", "SANTA CATARINA": "SC",
       "SAO PAULO": "SP", "SERGIPE": "SE", "TOCANTINS": "TO"}
PARTICULAS = {"de", "da", "do", "das", "dos", "e", "em", "para", "a", "o", "na", "no", "nas", "nos", "com", "por", "del", "à", "ao", "aos", "às"}
SIGLAS = {"cnpq", "finep", "capes", "bndes", "fapemig", "fapesp", "faperj", "ufmg", "ufv", "ufu", "ufla", "ufjf", "usp", "unicamp", "embrapa", "fiocruz", "ltda", "s.a.", "epamig", "sus", "inpe", "ipt", "mcti", "mctic"}


def sem_acento(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def chave(s) -> str:
    return re.sub(r"\s+", " ", sem_acento(str(s or "")).upper()).strip()


def limpo(s) -> str | None:
    if s is None:
        return None
    t = re.sub(r"\s+", " ", str(s).replace("\xa0", " ")).strip()
    return t or None


def bonito(s: str | None, sigla_curta: bool = False) -> str | None:
    """Nome de pessoa ou de instituição escrito em CAIXA ALTA vira Título (de, da, dos ficam minúsculos). Só muda a caixa das letras; não corrige nada."""
    s = limpo(s)
    if not s:
        return None
    if s != s.upper():
        return s                                  # já vem com minúsculas: respeita a fonte
    if sigla_curta and " " not in s and len(s) <= 8:
        return s                                  # instituição de uma palavra curta toda em maiúsculas é sigla (FAPERGS, FUNDEP): fica como a fonte escreveu
    def peca(t: str, primeira: bool) -> str:
        if t in SIGLAS:
            return t.upper()
        return t if (not primeira and t in PARTICULAS) else t[:1].upper() + t[1:]

    out = []
    for i, p in enumerate(s.lower().split(" ")):
        out.append("-".join(peca(q, i == 0 and j == 0) for j, q in enumerate(p.split("-"))))
    return " ".join(out)


def corta(t: str | None, n: int) -> str | None:
    """Texto longo cortado na última palavra inteira, com reticências (o resumo completo fica na fonte)."""
    if not t:
        return None
    if len(t) <= n:
        return t
    return t[:n].rsplit(" ", 1)[0].rstrip(",;:.") + "…"


def numero(v) -> float | None:
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    if v is None:
        return None
    t = str(v).strip().replace("R$", "").replace(" ", "")
    if not t:
        return None
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None


def data_iso(v) -> str | None:
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    t = limpo(v)
    if not t:
        return None
    m = re.match(r"^(\d{2})/(\d{2})/(\d{4})", t)
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", t)
    return t[:10] if m else None


def baixar(url: str) -> bytes:
    ultimo = None
    for t in range(4):
        try:
            r = httpx.get(url, headers=UA, timeout=180, follow_redirects=True)
            if r.status_code == 200 and len(r.content) > 1000:
                return r.content
            ultimo = f"HTTP {r.status_code}"
        except httpx.HTTPError as e:
            ultimo = str(e)[:100]
        time.sleep(3 * (t + 1))
    raise RuntimeError(f"{url[:90]}: {ultimo}")


def ler_xlsx(conteudo: bytes) -> tuple[list[str], list[tuple]]:
    ws = openpyxl.load_workbook(io.BytesIO(conteudo), read_only=True, data_only=True).worksheets[0]
    linhas = ws.iter_rows(values_only=True)
    cab = None
    for r in linhas:                                   # a primeira linha com texto é o cabeçalho
        if sum(1 for c in r if c not in (None, "")) >= 3:
            cab = [limpo(c) or "" for c in r]
            break
    if cab is None:
        return [], []
    return cab, [r for r in linhas if any(c not in (None, "") for c in r)]


def abrir_finep(conteudo: bytes):
    return openpyxl.load_workbook(io.BytesIO(conteudo), read_only=True, data_only=True)


def ler_aba_finep(wb, aba: str) -> tuple[str | None, list[str], list[tuple]]:
    """Uma aba da planilha da FINEP: (posição da planilha, cabeçalho, linhas). O cabeçalho é a primeira linha (depois da 5ª) com 8 ou mais textos."""
    nome = next((n for n in wb.sheetnames if chave(n).replace("_", " ") == chave(aba).replace("_", " ")), None)
    if nome is None:
        raise RuntimeError(f"FINEP: a aba {aba} não está na planilha (abas: {wb.sheetnames[:12]})")
    linhas = list(wb[nome].iter_rows(values_only=True))
    hi = next((i for i, r in enumerate(linhas) if i >= 4 and sum(1 for c in r if isinstance(c, str) and c.strip()) >= 8), None)
    if hi is None:
        raise RuntimeError(f"FINEP: cabeçalho da aba {aba} não encontrado")
    posicao = next((limpo(r[0]) for r in linhas[:hi] if r and r[0] and "osi" in str(r[0]) and "/" in str(r[0])), None)
    return posicao, [limpo(c) or "" for c in linhas[hi]], [r for r in linhas[hi + 1:] if any(c not in (None, "") for c in r)]


class Dic:
    """Dicionário que devolve o número de cada texto (os projetos guardam só o número: o arquivo fica bem menor)."""

    def __init__(self):
        self.lista: list = []
        self.idx: dict = {}

    def __call__(self, valor, criar=None):
        if valor is None:
            return None
        k = json.dumps(valor, ensure_ascii=False)
        if k not in self.idx:
            self.idx[k] = len(self.lista)
            self.lista.append(valor)
        return self.idx[k]


def montar(fapemig_proj: bytes, fapemig_inst: bytes, int_arqs: list[tuple[int, str, str, bytes]], finep: bytes | None = None, faperj: list[dict] | None = None,
           hoje: str | None = None) -> dict:
    hoje = hoje or date.today().isoformat()
    inst, area, chamada, modal = Dic(), Dic(), Dic(), Dic()
    projetos: list[list] = []

    # ---- cadastro de instituições da FAPEMIG: estado, tipo e se é ICT
    cab, linhas = ler_xlsx(fapemig_inst)
    ci = {chave(c): i for i, c in enumerate(cab)}
    cadastro = {}
    for r in linhas:
        nome = limpo(r[ci["NOME_INSTITUICAO"]])
        if nome:
            cadastro[chave(nome)] = (UFS.get(chave(r[ci["ESTADO"]])), limpo(r[ci["TIPO_INSTITUICAO"]]), limpo(r[ci["LCT"]]))

    inst_idx: dict[str, int] = {}

    def instituicao(nome, sigla, uf=None, tipo=None):
        """Uma instituição por nome (mesma razão social, sem acento e caixa) em TODAS as fontes: o que uma fonte não traz (sigla, estado, tipo) é completado pela outra."""
        n = bonito(nome, sigla_curta=True) or "Instituição não informada pela fonte"
        k = chave(n)
        if k not in inst_idx:
            inst_idx[k] = len(inst.lista)
            inst.lista.append([n, limpo(sigla), uf, bonito(tipo) if tipo else None])
        else:
            e = inst.lista[inst_idx[k]]
            for j, v in ((1, limpo(sigla)), (2, uf), (3, bonito(tipo) if tipo else None)):
                if e[j] is None and v:
                    e[j] = v
        return inst_idx[k]

    # ---- FAPEMIG
    cab, linhas = ler_xlsx(fapemig_proj)
    c = {chave(x): i for i, x in enumerate(cab)}
    obrig = ["ANO", "PROCESSO", "COORDENADOR", "TITULO", "AREA", "VALORCONTRATADO", "INSTITUICAOEXECUTORA_NOME"]
    faltam = [k for k in obrig if k not in c]
    if faltam:
        raise RuntimeError(f"FAPEMIG: colunas que sumiram: {faltam}")
    vistos, descartadas = set(), {"sem_processo": 0, "repetido": 0, "ano_invalido": 0}
    for r in linhas:
        proc = limpo(r[c["PROCESSO"]])
        if not proc:
            descartadas["sem_processo"] += 1
            continue
        if proc in vistos:
            descartadas["repetido"] += 1
            continue
        vistos.add(proc)
        ano = r[c["ANO"]]
        if not isinstance(ano, (int, float)) or not 1990 <= int(ano) <= date.today().year + 1:
            descartadas["ano_invalido"] += 1              # ex.: uma linha com "RBE" no lugar do ano: o projeto entra sem ano
            ano = None
        else:
            ano = int(ano)
        nome_ex, sigla_ex = limpo(r[c["INSTITUICAOEXECUTORA_NOME"]]), limpo(r[c["INSTITUICAOEXECUTORA_SIGLA"]])
        nome_ge, sigla_ge = limpo(r[c["INSTITUICAOGESTORA_NOME"]]), limpo(r[c["INSTITUICAOGESTORA_SIGLA"]])
        sede = (sigla_ex or "").upper() == "SEDE"           # SEDE = a própria FAPEMIG (termos de cooperação, programas): não é pesquisa de um pesquisador
        cad = cadastro.get(chave(nome_ex)) if nome_ex else None
        ie = instituicao(nome_ex, sigla_ex, cad[0] if cad else None, cad[1] if cad else None)
        cad_g = cadastro.get(chave(nome_ge)) if nome_ge else None
        ig = instituicao(nome_ge, sigla_ge, cad_g[0] if cad_g else None, cad_g[1] if cad_g else None) if nome_ge and "NAO POSSUI GESTORA" not in chave(nome_ge) else None
        projetos.append([0, ano, proc, limpo(r[c["TITULO"]]), bonito(r[c["COORDENADOR"]]), ie, ig,
                         area(bonito(r[c["AREA"]])), chamada(limpo(r[c["CHAMADA_DESC"]]) if "CHAMADA_DESC" in c else None),
                         modal(bonito(r[c["MODALIDADE"]]) if "MODALIDADE" in c else None), numero(r[c["VALORCONTRATADO"]]),
                         data_iso(r[c["DATA_INICIO"]]) if "DATA_INICIO" in c else None, data_iso(r[c["DATA_TERMINO"]]) if "DATA_TERMINO" in c else None,
                         1 if sede else 0, None, None])
    n_fapemig = len(projetos)

    # ---- INT
    int_inst = instituicao("Instituto Nacional de Tecnologia", "INT", "RJ", "Pública federal")
    int_linhas = 0
    por_arquivo = []
    int_visto: dict[tuple, list] = {}
    for ano, cliente, url, conteudo in int_arqs:
        cab, linhas = ler_xlsx(conteudo)
        k = {chave(x): i for i, x in enumerate(cab)}
        def achar(*prefixos):
            for x, i in k.items():
                if any(x.startswith(chave(p)) for p in prefixos):
                    return i
            return None
        i_tit, i_desc, i_data, i_val, i_cli = achar("TITULO"), achar("DESCRICAO"), achar("DATA DE ASSINATURA"), achar("VALOR"), achar("NOME DO CLIENTE", "CLIENTE")
        i_fonte = achar("FONTE DE RECURSO")
        if i_tit is None or i_val is None:
            por_arquivo.append({"ano": ano, "cliente": cliente, "linhas": 0, "aviso": "colunas não reconhecidas"})
            continue
        n = 0
        ocorrencia: dict[tuple, int] = {}
        for r in linhas:
            tit = limpo(r[i_tit])
            if not tit or chave(tit) in ("TOTAL",):
                continue
            n += 1
            ass = data_iso(r[i_data]) if i_data is not None else None
            desc = limpo(r[i_desc]) if i_desc is not None else None
            cli = bonito(r[i_cli]) if i_cli is not None else None
            val = numero(r[i_val])
            base = (chave(tit), ass, val, chave(cli))
            ocorrencia[base] = ocorrencia.get(base, 0) + 1
            kk = base + (ocorrencia[base],)            # linhas iguais DENTRO do mesmo arquivo são registros distintos; só unimos entre arquivos
            if kk in int_visto:                        # o mesmo contrato aparece em listas de anos diferentes: um só registro, com os anos em que foi listado
                if ano not in int_visto[kk][14]["listado_em"]:
                    int_visto[kk][14]["listado_em"].append(ano)
                continue
            proj = [1, int(ass[:4]) if ass else ano, f"INT-{ano}-{cliente}-{n}", tit, None, int_inst, None, None, None, modal("Projeto de P&D contratado"),
                    val, ass, None, 0, {"cliente": cli, "tipo_cliente": cliente, "descricao": (desc or "")[:700] or None, "fonte_recurso": limpo(r[i_fonte]) if i_fonte is not None else None, "listado_em": [ano]}, None]
            int_visto[kk] = proj
            projetos.append(proj)
        por_arquivo.append({"ano": ano, "cliente": cliente, "linhas": n, "sha256": hashlib.sha256(conteudo).hexdigest()[:16]})

    int_linhas = len(int_visto)

    # ---- FINEP: três abas da planilha de contratação. O valor liberado (pago) vem da própria FINEP.
    #  * ICTs (universidades e institutos): fonte "finep", grupo 0 (pesquisa)
    #  * Subvenção direta (empresas): fonte "finep-empresas", grupo 2 (empresas)
    #  * Subvenção descentralizada (Centelha/Tecnova, via fundações estaduais): fonte "finep-empresas", grupo 2, com o nome do coordenador que a FINEP publica
    finep_info: dict[str, dict] = {}
    if finep is not None:
        wb = abrir_finep(finep)
        sha = hashlib.sha256(finep).hexdigest()[:16]
        for aba, fonte_i, grupo, tipo_inst, modalidade_fixa in (("Projetos_Não_Reembolsavel_ICTs", 2, 0, None, "Não reembolsável a ICTs"),
                                                                ("Projetos_Subvenção_Direta", 3, 2, "Empresa", None)):
            try:
                posicao, cab, linhas = ler_aba_finep(wb, aba)
            except RuntimeError:
                if grupo == 0:
                    raise                                        # a aba de ICTs é o coração da fonte; as de subvenção podem sumir sem derrubar a coleta
                continue
            k = {chave(x): i for i, x in enumerate(cab) if x}
            faltam = [x for x in ["CONTRATO", "TITULO", "EXECUTOR", "UF EXECUTOR", "VALOR FINEP", "VALOR PAGO", "DATA ASSINATURA"] if x not in k]
            if faltam:
                raise RuntimeError(f"FINEP ({aba}): colunas que sumiram: {faltam}")
            g = lambda r, nome: r[k[chave(nome)]] if chave(nome) in k else None  # noqa: E731
            vistos_f: set[str] = set()
            repetidos = 0
            for r in linhas:
                contrato = limpo(g(r, "Contrato"))
                if not contrato:
                    continue
                if contrato in vistos_f:
                    repetidos += 1
                    continue
                vistos_f.add(contrato)
                ass = data_iso(g(r, "Data Assinatura"))
                exe, prop = limpo(g(r, "Executor")), limpo(g(r, "Proponente"))
                uf = limpo(g(r, "UF Executor"))
                ie = instituicao(exe, None, uf.upper() if uf else None, tipo_inst)
                ig = instituicao(prop, None, (limpo(g(r, "UF Proponente")) or "").upper() or None, tipo_inst) if prop and chave(prop) != chave(exe) else None
                resumo = limpo(g(r, "Resumo Publicável"))
                modal_txt = modalidade_fixa or limpo(g(r, "Instrumento")) or "Subvenção direta"
                projetos.append([fonte_i, int(ass[:4]) if ass else None, contrato, limpo(g(r, "Título")), None, ie, ig, None, chamada(limpo(g(r, "Demanda"))),
                                 modal(modal_txt), numero(g(r, "Valor Finep")), ass, data_iso(g(r, "Prazo Execução")), grupo,
                                 {"status": limpo(g(r, "Status")), "municipio": bonito(g(r, "Município Executor")), "resumo": corta(resumo, 300)}, numero(g(r, "Valor Pago"))])
            finep_info[aba] = {"posicao": posicao, "repetidos": repetidos, "linhas": len(vistos_f), "sha256": sha}

        try:
            posicao, cab, linhas = ler_aba_finep(wb, "Projetos_Subv__Descentralizada")
        except RuntimeError:
            posicao, cab, linhas = None, [], []
        k = {chave(x): i for i, x in enumerate(cab) if x}
        faltam = [x for x in ["REFERENCIA PROJETO", "RAZAO SOCIAL", "TITULO DO PROJETO", "PARTICIPACAO FINEP", "TOTAL LIBERADO - FINEP", "DATA ASSINATURA"] if x not in k] if cab else []
        if faltam:
            raise RuntimeError(f"FINEP (subvenção descentralizada): colunas que sumiram: {faltam}")
        g = lambda r, nome: r[k[chave(nome)]] if chave(nome) in k else None  # noqa: E731
        vistos_f = set()
        repetidos = 0
        for r in linhas:
            ref = limpo(g(r, "Referência Projeto"))
            if not ref:
                continue
            if ref in vistos_f:
                repetidos += 1
                continue
            vistos_f.add(ref)
            ass = data_iso(g(r, "Data assinatura"))
            uf = (limpo(g(r, "UF Empresa")) or "").upper() or None
            ie = instituicao(limpo(g(r, "Razão Social")), None, uf, "Empresa")
            fap = limpo(g(r, "FAP"))
            ig = instituicao(fap, None, None, "Fundação estadual de amparo à pesquisa") if fap else None
            projetos.append([3, int(ass[:4]) if ass else None, ref, limpo(g(r, "Titulo do projeto")), bonito(g(r, "Nome do coordenador")), ie, ig, area(bonito(g(r, "Área temática"))),
                             chamada(limpo(g(r, "Programa"))), modal("Subvenção descentralizada (via fundação estadual)"), numero(g(r, "Participação Finep")), ass,
                             data_iso(g(r, "Prazo de Execução")), 2,
                             {"municipio": bonito(g(r, "Municipio")), "porte": limpo(g(r, "Porte Empresa")), "fap": fap, "valor_total": numero(g(r, "Valor total")),
                              "contrapartida_empresa": numero(g(r, "Contrapartida da empresa")), "liberado_fap": numero(g(r, "Total Liberado - FAP"))},
                             numero(g(r, "Total Liberado - Finep"))])
        if cab:
            finep_info["Projetos_Subv__Descentralizada"] = {"posicao": posicao, "repetidos": repetidos, "linhas": len(vistos_f), "sha256": sha}

    # ---- FAPERJ (busca pública; não publica valor)
    faperj_n = 0
    if faperj:
        for x in faperj:
            ed = x.get("edicao") or ""
            ano_m = re.search(r"(?<!\d)((?:19|20)\d\d)(?!\d)", ed)
            ie = instituicao(x.get("instituicao"), None, "RJ", None) if x.get("instituicao") else instituicao(None, None, None, None)
            projetos.append([4, int(ano_m.group(1)) if ano_m else None, f"FAPERJ-{x['id']}", x.get("titulo"), bonito(x.get("pesquisador")), ie, None, area(bonito(x.get("area"))),
                             chamada(limpo(ed)), None, None, None, None, 0, None, None])      # o resumo na FAPERJ é montado pelo identificador FAPERJ-<atvnumero>
            faperj_n += 1

    int_linhas = len(int_visto)
    pos_ict = (finep_info.get("Projetos_Não_Reembolsavel_ICTs") or {}).get("posicao")
    n_emp = sum(finep_info[a]["linhas"] for a in ("Projetos_Subvenção_Direta", "Projetos_Subv__Descentralizada") if a in finep_info)
    fontes = [
        {"id": "fapemig", "nome": "FAPEMIG — projetos contratados", "financiador": "Fundação de Amparo à Pesquisa do Estado de Minas Gerais", "uf": "MG", "url": FAPEMIG_PAGINA,
         "arquivos": FAPEMIG_ARQ, "tipo_valor": "contratado", "atualizacao": "a cada 3 meses (publicação de 03/06/2026)", "linhas": n_fapemig,
         "tem_pesquisador": True, "descartadas": descartadas,
         "sha256": {"projetos": hashlib.sha256(fapemig_proj).hexdigest()[:16], "instituicoes": hashlib.sha256(fapemig_inst).hexdigest()[:16]},
         "aviso": "Valor contratado, não valor pago. Executora SEDE = termos e programas da própria FAPEMIG (não são pesquisa de um pesquisador)."},
        {"id": "int", "nome": "INT — projetos de P&D contratados", "financiador": "Clientes do Instituto Nacional de Tecnologia (governo e empresas)", "uf": "RJ", "url": INT_PAGINA,
         "arquivos": {f"{a}-{cl}": u for a, cl, u, _ in int_arqs}, "tipo_valor": "pactuado", "atualizacao": "anual", "linhas": int_linhas, "tem_pesquisador": False,
         "por_arquivo": por_arquivo,
         "aviso": "Valor pactuado no contrato; é dinheiro que o INT recebe do cliente. A fonte não traz o nome de quem pesquisa."},
        {"id": "finep", "nome": "FINEP — projetos não reembolsáveis a ICTs", "financiador": "Financiadora de Estudos e Projetos (FINEP, federal)", "uf": "Brasil", "url": FINEP_PAGINA,
         "arquivos": {"contratacao": FINEP_ARQ}, "tipo_valor": "contratado", "tem_pago": True, "atualizacao": f"planilha da FINEP, {pos_ict or 'posição não informada'}",
         "linhas": (finep_info.get("Projetos_Não_Reembolsavel_ICTs") or {}).get("linhas", 0), "tem_pesquisador": False,
         "descartadas": {"repetido": (finep_info.get("Projetos_Não_Reembolsavel_ICTs") or {}).get("repetidos", 0)},
         "aviso": "Valor contratado = Valor Finep do contrato; liberado = soma do que a FINEP já repassou ao projeto na posição da planilha (não é o andamento científico). "
                  "Instituições de ciência e tecnologia (universidades, institutos)."},
        {"id": "finep-empresas", "nome": "FINEP — subvenção a empresas", "financiador": "FINEP (federal), com fundações estaduais nos programas Centelha e Tecnova", "uf": "Brasil", "url": FINEP_PAGINA,
         "arquivos": {"contratacao": FINEP_ARQ}, "tipo_valor": "contratado", "tem_pago": True, "atualizacao": f"planilha da FINEP, {pos_ict or 'posição não informada'}",
         "linhas": n_emp, "tem_pesquisador": True, "grupo": "empresas",
         "aviso": "Subvenção (dinheiro não reembolsável) a empresas para pesquisa e inovação: subvenção direta e subvenção descentralizada (Centelha, Tecnova, via fundações estaduais). "
                  "Valor = parte da FINEP (Valor Finep / Participação Finep); liberado = o que a FINEP já liberou. Ficam fora dos rankings de pesquisa e aparecem em Projetos › Empresas. "
                  "O coordenador é o nome que a FINEP publica para a empresa."},
        {"id": "faperj", "nome": "FAPERJ — projetos contemplados", "financiador": "Fundação Carlos Chagas Filho de Amparo à Pesquisa do Estado do Rio de Janeiro", "uf": "RJ",
         "url": "https://siteantigo.faperj.br/servicos/buscaprojetosinfaperj/busca_projeto.phtml", "arquivos": {}, "tipo_valor": "nd",
         "atualizacao": "busca pública, desde julho de 2007", "linhas": faperj_n, "tem_pesquisador": True,
         "aviso": "A FAPERJ publica pesquisador, instituição, programa, título e área, mas NÃO o valor de cada auxílio. O estado RJ vem da regra da própria FAPERJ (financia instituições sediadas no estado), "
                  "não de um campo da busca."},
    ]
    return {"fonte": "FINEP, FAPEMIG, FAPERJ e INT (dados abertos)", "gerado_em": hoje, "versao": 3, "fontes": fontes,
            "inst": inst.lista, "areas": area.lista, "chamadas": chamada.lista, "modalidades": modal.lista, "p": projetos}


def main() -> None:
    pasta = None
    if "--arquivos" in sys.argv:
        pasta = Path(sys.argv[sys.argv.index("--arquivos") + 1])
    if pasta:
        proj, ins = (pasta / "projetos-contratados.xlsx").read_bytes(), (pasta / "instituicoescadastradas.xlsx").read_bytes()
        ints = []
        fin = (pasta / "Contratacao.xlsx").read_bytes() if (pasta / "Contratacao.xlsx").exists() else None
    else:
        print("baixando FAPEMIG...")
        proj, ins = baixar(FAPEMIG_ARQ["projetos"]), baixar(FAPEMIG_ARQ["instituicoes"])
        ints = []
        print("baixando FINEP (8 MB)...")
        fin = baixar(FINEP_ARQ)
        for ano, cli, url in INT_ARQ:
            try:
                ints.append((ano, cli, url, baixar(url)))
                print(f"INT {ano} {cli}: ok")
            except RuntimeError as e:
                print(f"INT {ano} {cli}: NÃO baixou ({e})")
    arq_faperj = RAIZ / "app" / "dados" / "faperj_projetos.json"
    faperj = None
    if arq_faperj.exists():
        fj = json.loads(arq_faperj.read_text(encoding="utf-8"))
        faperj = fj["projetos"]
        print(f"FAPERJ: {len(faperj)} projetos da varredura de {fj.get('coletado_em')}" + (" (PARCIAL)" if fj.get("parcial") else ""))
    else:
        print("FAPERJ: sem app/dados/faperj_projetos.json (rode python -m scripts.faperj)")
    d = montar(proj, ins, ints, fin, faperj)
    SAIDA.write_text(json.dumps(d, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tot = {f["id"]: f["linhas"] for f in d["fontes"] if f["linhas"]}
    print(f"{len(d['p'])} projetos ({tot}); {len(d['inst'])} instituições; {SAIDA.stat().st_size/1e6:.1f} MB → {SAIDA.name}")


if __name__ == "__main__":
    main()
