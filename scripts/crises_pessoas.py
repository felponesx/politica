"""Saúde mental, deficiência, autismo, benefícios e juventude fora da escola e do trabalho, por estado.

Uso:
    python -m scripts.crises_pessoas [saida.json] [--mes AAAAMM]

Fontes (todas abertas, sem chave):
  - IBGE, Censo 2022 (SIDRA 10130, 10127, 10145): pessoas com deficiência (e por tipo de dificuldade) e pessoas
    diagnosticadas com autismo, por estado.
  - IBGE, Censo 2022 (SIDRA 9543 e 9936): taxa de alfabetização de 15 anos ou mais e domicílios ocupados, por estado.
  - IBGE, PNS 2013 e 2019 (SIDRA 4694, 4669, 7891): depressão diagnosticada por profissional de saúde mental, outros
    transtornos mentais e uso de remédio para depressão.
  - IBGE, PNAD Contínua 2025 (SIDRA 9415, 7447, 7449): jovens de 15 a 24 anos que não estudam nem trabalham, e
    domicílios e pessoas com algum morador que recebeu Bolsa Família.
  - Portal da Transparência, Gás do Povo (download-de-dados/gas-do-povo/AAAAMM): famílias e pessoas beneficiadas por
    estado no mês. SÓ TOTAIS POR ESTADO: CPF, nome e estabelecimento NÃO são lidos nem guardados.

Resultado em app/dados/crises_pessoas.json (lido por GET /populacao/extra, chave "crises").
Quando uma fonte não responde, o campo fica sem valor e a fonte aparece em "falhas": nunca se põe zero no lugar.
"""
from __future__ import annotations

import csv
import io
import json
import sys
import tempfile
import zipfile
from datetime import date
from pathlib import Path

from app.populacao import SIGLA

SAIDA = Path(__file__).resolve().parent.parent / "app" / "dados" / "crises_pessoas.json"
POPULACAO = Path(__file__).resolve().parent.parent / "app" / "dados" / "populacao_censo.json"
BASE = "https://apisidra.ibge.gov.br/values"
GAS = "https://portaldatransparencia.gov.br/download-de-dados/gas-do-povo/{mes}"
UA = "BRASILMais/1.0 (site de dados abertos)"

# Códigos da classificação do SIDRA (confirmados nas respostas reais, ver tests/test_crises_pessoas.py)
DEF_TOTAL = "58771"                                  # tabela 10127, tipo de dificuldade: total
DEF_TIPOS = {"visual": "73771", "auditiva": "73772", "motora": "73773", "mao": "73789", "comunicacao": "73790"}
DEF_POP_TOTAL, DEF_POP_COM = "46583", "58765"        # tabela 10130: total e pessoas com deficiência
AUT_TOTAL = "95253"                                  # tabela 10145: grupo de idade total
DEP_TOTAL_SEXO, DEP_TOTAL_SIT = "6794", "6795"       # total de sexo e de situação do domicílio (PNS)


def _baixar(url: str) -> list[dict]:
    import httpx
    r = httpx.get(url, headers={"User-Agent": UA}, timeout=300, follow_redirects=True)
    r.raise_for_status()
    return r.json()[1:]


def _num(v) -> float | None:
    """Valor do SIDRA como número. '-', '..' e '...' (sem dado) viram None, nunca zero."""
    try:
        return float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _sigla(x: dict) -> str | None:
    """Sigla do estado pelo código de 2 dígitos ('1' = Brasil)."""
    cod = str(x.get("D1C") or "")
    if cod == "1":
        return "BR"
    return SIGLA.get(cod)


def _colher(linhas: list[dict], metricas: dict, periodo_chave: str = "D3C") -> dict:
    """metricas = {nome_no_resultado: (variavel_codigo_ou_None, {campo: valor_esperado})}.
    Devolve {UF: {metrica: valor}} e {UF: {metrica: periodo}}; linha sem dado fica de fora."""
    out: dict[str, dict] = {}
    per: dict[str, dict] = {}
    for x in linhas:
        sg = _sigla(x)
        if sg is None:
            continue
        for nome, (var, filtros) in metricas.items():
            if var is not None and str(x.get("D2C")) != var:
                continue
            if any(str(x.get(k)) != v for k, v in filtros.items()):
                continue
            v = _num(x.get("V"))
            if v is None:
                continue
            out.setdefault(sg, {})[nome] = v
            per.setdefault(sg, {})[nome] = x.get(periodo_chave)
    return {"valores": out, "periodos": per}


def censo_deficiencia(linhas_tipo: list[dict], linhas_pop: list[dict]) -> dict:
    """% de pessoas de 2 anos ou mais com deficiência e % com cada dificuldade (Censo 2022). Uma pessoa pode ter mais de uma:
    as porcentagens por tipo não somam 100."""
    metricas = {"deficiencia_pct": ("13403", {"D4C": DEF_TOTAL}), "deficiencia_n": ("12785", {"D4C": DEF_TOTAL})}
    for tipo, cod in DEF_TIPOS.items():
        metricas[f"def_{tipo}_pct"] = ("13403", {"D4C": cod})
        metricas[f"def_{tipo}_n"] = ("12785", {"D4C": cod})
    tip = _colher(linhas_tipo, metricas)
    pop = _colher(linhas_pop, {"pessoas_2mais": ("11852", {"D5C": DEF_POP_TOTAL}),
                               "com_deficiencia": ("11852", {"D5C": DEF_POP_COM})})
    valores = {}
    for sg in set(tip["valores"]) | set(pop["valores"]):
        d = {**tip["valores"].get(sg, {}), **pop["valores"].get(sg, {})}
        valores[sg] = d
    return {"valores": valores, "periodos": {**tip["periodos"], **{k: v for k, v in pop["periodos"].items()}}}


def censo_autismo(linhas: list[dict]) -> dict:
    """Pessoas diagnosticadas com autismo e % da população (Censo 2022, tabela 10145)."""
    r = _colher(linhas, {"autismo_n": ("13267", {"D4C": DEP_TOTAL_SEXO, "D5C": AUT_TOTAL}),
                         "autismo_pct": ("13408", {"D4C": DEP_TOTAL_SEXO, "D5C": AUT_TOTAL})})
    return r


def pns_depressao(dep2013: list[dict], dep2019: list[dict], outros2013: list[dict], outros2019: list[dict],
                  medic2019: list[dict]) -> dict:
    """Depressão diagnosticada por profissional de saúde mental (PNS 2013 e 2019), outros transtornos graves e uso de remédio
    entre quem tem depressão (PNS 2019). Cada ano vem da sua própria consulta, pelo período pedido."""
    partes = [
        _colher(dep2013, {"depressao_prof_2013_pct": ("4642", {"D4C": DEP_TOTAL_SEXO, "D5C": DEP_TOTAL_SIT})}),
        _colher(dep2019, {"depressao_prof_2019_pct": ("4642", {"D4C": DEP_TOTAL_SEXO, "D5C": DEP_TOTAL_SIT})}),
        _colher(outros2013, {"outros_transtornos_2013_pct": ("4678", {"D4C": DEP_TOTAL_SEXO, "D5C": DEP_TOTAL_SIT})}),
        _colher(outros2019, {"outros_transtornos_2019_pct": ("4678", {"D4C": DEP_TOTAL_SEXO, "D5C": DEP_TOTAL_SIT})}),
        _colher(medic2019, {"depressao_remedio_2019_pct": ("11157", {"D4C": DEP_TOTAL_SEXO, "D5C": DEP_TOTAL_SIT})}),
    ]
    valores, periodos = {}, {}
    for parte in partes:
        for sg, d in parte["valores"].items():
            valores.setdefault(sg, {}).update(d)
        for sg, d in parte["periodos"].items():
            periodos.setdefault(sg, {}).update(d)
    return {"valores": valores, "periodos": periodos}


def pnad_nemnem(linhas: list[dict]) -> dict:
    """% de pessoas de 15 a 24 anos que não estão ocupadas, não estudam e não fazem treinamento (PNAD 2025, ODS 8.6.1)."""
    return _colher(linhas, {"nem_nem_pct": ("8840", {})})


def _variavel(x: dict) -> str:
    """Nome da variável da linha. Nas tabelas do SIDRA a coluna muda de tabela para tabela (D2N, D3N ou D4N)."""
    for k in ("D2N", "D3N", "D4N"):
        t = str(x.get(k) or "")
        if t and not t[:4].isdigit() and t != "Total":
            return t
    return ""


def pnad_bolsa(linhas_dom: list[dict], linhas_pes: list[dict]) -> dict:
    """Domicílios (mil) com algum morador que recebeu Bolsa Família, e pessoas de 10 anos ou mais nesses domicílios (mil).
    A porcentagem dos domicílios é calculada em coletar(), contra os domicílios do Censo 2022: a linha 'Percentual' da
    tabela é a distribuição do total (100), não a fatia."""
    dom = {}
    for x in linhas_dom:
        if _variavel(x).startswith("Domicílios em que algum morador do domicílio recebeu") \
                and str(x.get("MN", "")) == "Mil unidades":
            sg, v = _sigla(x), _num(x.get("V"))
            if sg and v is not None:
                dom.setdefault(sg, {})["bolsa_domicilios_mil"] = v
    pes = {}
    for x in linhas_pes:
        if _variavel(x).startswith("Pessoas de 10 anos ou mais de idade cujo domicílio possui algum morador que recebeu") \
                and str(x.get("MN", "")) == "Mil pessoas":
            sg, v = _sigla(x), _num(x.get("V"))
            if sg and v is not None:
                pes.setdefault(sg, {})["bolsa_pessoas_mil"] = v
    valores = {}
    for sg in set(dom) | set(pes):
        valores[sg] = {**dom.get(sg, {}), **pes.get(sg, {})}
    return {"valores": valores}


def alfabetizacao(linhas: list[dict]) -> dict:
    """Taxa de alfabetização de 15 anos ou mais (Censo 2022, tabela 9543) → analfabetismo = 100 − taxa."""
    out = {}
    for x in linhas:
        if not _variavel(x).startswith("Taxa de alfabetização") or str(x.get("D4N")) != "Total":
            continue
        sg, v = _sigla(x), _num(x.get("V"))
        if sg and v is not None:
            out[sg] = {"analfabetismo_pct": round(100 - v, 2)}
    return {"valores": out}


def domicilios_censo(linhas: list[dict]) -> dict:
    """Domicílios particulares permanentes ocupados por estado (Censo 2022, tabela 9936)."""
    out = {}
    for x in linhas:
        if not _variavel(x).startswith("Domicílios particulares permanentes ocupados") or str(x.get("D4N")) != "Total":
            continue
        sg, v = _sigla(x), _num(x.get("V"))
        if sg and v is not None:
            out[sg] = {"domicilios": v}
    return {"valores": out}


def gas_do_povo(caminho_zip: Path) -> dict:
    """Soma por estado do arquivo mensal do Gás do Povo. Lê só UF, tamanho da família e valor. CPF e nome não são lidos."""
    csv.field_size_limit(10**9)
    fam: dict[str, int] = {}
    pes: dict[str, int] = {}
    val: dict[str, float] = {}
    mes = None
    linhas = sem_pessoas = 0
    with zipfile.ZipFile(caminho_zip) as z:
        nome = next(i.filename for i in z.infolist() if i.filename.lower().endswith(".csv"))
        with z.open(nome) as bruto:
            leitor = csv.reader(io.TextIOWrapper(bruto, encoding="latin-1", newline=""), delimiter=";")
            cab = [c.strip().upper() for c in next(leitor)]
            i_mes, i_uf = cab.index("MÊS REFERÊNCIA"), cab.index("UF")
            i_pes, i_val = cab.index("QUANTIDADE DE PESSOAS NA FAMÍLIA"), cab.index("VALOR BENEFÍCIO")
            for row in leitor:
                if len(row) <= i_val:
                    continue
                linhas += 1
                uf = row[i_uf].strip().upper()
                mes = mes or row[i_mes].strip()
                fam[uf] = fam.get(uf, 0) + 1
                try:
                    pes[uf] = pes.get(uf, 0) + int(row[i_pes])
                except ValueError:
                    sem_pessoas += 1
                try:
                    val[uf] = val.get(uf, 0.0) + float(row[i_val].replace(".", "").replace(",", "."))
                except ValueError:
                    pass
    out = {}
    for uf in fam:
        out[uf] = {"gas_familias": fam[uf], "gas_pessoas": pes.get(uf), "gas_valor_mi": round(val.get(uf, 0.0) / 1e6, 2)}
    return {"mes": mes, "linhas": linhas, "sem_quantidade_pessoas": sem_pessoas, "valores": out}


def _baixar_gas(mes: str, destino: Path) -> Path | None:
    import httpx
    alvo = destino / f"gas-{mes}.zip"
    with httpx.stream("GET", GAS.format(mes=mes), headers={"User-Agent": UA}, timeout=600, follow_redirects=True) as r:
        if r.status_code != 200:
            return None
        with open(alvo, "wb") as f:
            for parte in r.iter_bytes():
                f.write(parte)
    return alvo if zipfile.is_zipfile(alvo) else None


def _populacao() -> dict[str, int]:
    d = json.loads(POPULACAO.read_text(encoding="utf-8"))
    return {SIGLA.get(uf, uf): int(e["total"]) for uf, e in d["estados"].items()}


def _juntar(partes: dict[str, dict]) -> dict:
    """{UF: {metrica: valor}} a partir de vários recortes."""
    out: dict[str, dict] = {}
    for dados in partes.values():
        for sg, d in (dados or {}).items():
            out.setdefault(sg, {}).update(d)
    return out


def coletar(mes: str | None = None) -> dict:
    falhas: list[str] = []
    partes: dict[str, dict] = {}

    def tenta(nome, fn):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001 — uma fonte fora do ar não derruba as outras
            falhas.append(f"{nome}: {str(e)[:160]}")
            return None

    dep = tenta("PNS depressão", lambda: pns_depressao(
        _baixar(f"{BASE}/t/4694/n1/all/n3/all/v/4642/p/2013/c2/6794/c1/6795"),
        _baixar(f"{BASE}/t/4694/n1/all/n3/all/v/4642/p/2019/c2/6794/c1/6795"),
        _baixar(f"{BASE}/t/4669/n1/all/n3/all/v/4678/p/2013/c2/6794/c1/6795"),
        _baixar(f"{BASE}/t/4669/n1/all/n3/all/v/4678/p/2019/c2/6794/c1/6795"),
        _baixar(f"{BASE}/t/7891/n1/all/n3/all/v/11157/p/2019/c2/6794/c1/6795")))
    deficiencia = tenta("Censo deficiência", lambda: censo_deficiencia(
        _baixar(f"{BASE}/t/10127/n1/all/n3/all/v/13403,12785/p/2022/c1509/{DEF_TOTAL},{','.join(DEF_TIPOS.values())}"),
        _baixar(f"{BASE}/t/10130/n1/all/n3/all/v/11852/p/2022/c2/6794/c839/{DEF_POP_TOTAL},{DEF_POP_COM}")))
    autismo = tenta("Censo autismo", lambda: censo_autismo(
        _baixar(f"{BASE}/t/10145/n1/all/n3/all/v/13267,13408/p/2022/c2/6794/c58/{AUT_TOTAL}")))
    nem = tenta("PNAD nem-nem", lambda: pnad_nemnem(_baixar(f"{BASE}/t/9415/n1/all/n3/all/v/8840/p/last")))
    bolsa = tenta("PNAD Bolsa Família", lambda: pnad_bolsa(
        _baixar(f"{BASE}/t/7449/n1/all/n3/all/p/last"),
        _baixar(f"{BASE}/t/7447/n1/all/n3/all/p/last")))
    alf = tenta("Censo alfabetização", lambda: alfabetizacao(_baixar(f"{BASE}/t/9543/n1/all/n3/all/p/last")))
    dom = tenta("Censo domicílios", lambda: domicilios_censo(_baixar(f"{BASE}/t/9936/n1/all/n3/all/p/2022")))

    gas = None
    with tempfile.TemporaryDirectory() as tmp:
        tmp_p = Path(tmp)
        meses = [mes] if mes else [date.today().strftime("%Y%m"), _mes_anterior(1), _mes_anterior(2)]
        for m in meses:
            zipado = tenta(f"Gás do Povo {m}", lambda m=m: _baixar_gas(m, tmp_p))
            if zipado:
                gas = tenta(f"Gás do Povo {m} (leitura)", lambda z=zipado: gas_do_povo(z))
                if gas:
                    break
    if gas is None:
        falhas.append("Gás do Povo: nenhum mês publicado foi lido")

    pop = _populacao()
    periodos: dict[str, str] = {}
    for parte in (dep, deficiencia, autismo, nem):
        for d in ((parte or {}).get("periodos") or {}).values():
            for k, v in d.items():
                periodos.setdefault(k, v)
    for nome, parte in (("saude_mental", dep), ("deficiencia", deficiencia), ("autismo", autismo),
                        ("nem_nem", nem), ("bolsa", bolsa), ("alfabetizacao", alf), ("domicilios", dom)):
        if parte is not None:
            partes[nome] = parte.get("valores", parte) if isinstance(parte, dict) else {}
    if gas:
        periodos["gas_mes"] = gas["mes"]
        valores_gas = dict(gas["valores"])
        # total do Brasil = soma dos estados (o arquivo não tem linha de país)
        valores_gas["BR"] = {k: round(sum(d.get(k) or 0 for d in gas["valores"].values()), 2)
                             for k in ("gas_familias", "gas_pessoas", "gas_valor_mi")}
        partes["gas"] = valores_gas
        for sg, d in valores_gas.items():
            if pop.get(sg) and d.get("gas_pessoas") is not None:
                d["gas_pessoas_pct_pop"] = round(d["gas_pessoas"] / pop[sg] * 100, 2)
            dom_sg = (partes.get("domicilios") or {}).get(sg, {}).get("domicilios")
            if dom_sg:
                d["gas_familias_por_100_domicilios"] = round(d["gas_familias"] / dom_sg * 100, 2)
    uf = _juntar(partes)
    pop["BR"] = sum(v for k, v in pop.items() if k != "BR")
    for sg in list(uf):
        uf[sg]["populacao_2022"] = pop.get(sg)
        dom_sg = (partes.get("domicilios") or {}).get(sg, {}).get("domicilios")
        mil = uf[sg].get("bolsa_domicilios_mil")
        if dom_sg and mil is not None:
            uf[sg]["bolsa_domicilios_pct"] = round(mil * 1000 / dom_sg * 100, 1)
    if "BR" not in uf:
        uf["BR"] = {}
    uf["BR"]["populacao_2022"] = pop["BR"]
    if gas:
        # Brasil: porcentagem de pessoas com o Gás do Povo sobre a população do país
        uf.setdefault("BR", {})["gas_pessoas_pct_pop"] = round(uf["BR"]["gas_pessoas"] / pop["BR"] * 100, 2)

    return {
        "gerado_em": date.today().isoformat(),
        "uf": uf,
        "periodos": periodos,
        "fontes": {
            "depressao": {"fonte": "IBGE: PNS 2013 e PNS 2019 (tabelas 4694, 4669 e 7891)",
                          "link": "https://sidra.ibge.gov.br/tabela/4694",
                          "metodo": "Pessoas de 18 anos ou mais que referem diagnóstico de depressão por profissional de saúde mental, em 2013 e em 2019 "
                                    "(em % dos adultos do estado). Uso de remédio (2019): entre quem tem depressão, quantos usaram remédio para depressão "
                                    "nas duas semanas antes da pesquisa. Outros transtornos graves (2013 e 2019): esquizofrenia, transtorno bipolar, psicose ou TOC."},
            "autismo": {"fonte": "IBGE: Censo 2022 (tabela 10145)", "link": "https://sidra.ibge.gov.br/tabela/10145",
                        "metodo": "Pessoas que declararam diagnóstico de autismo. É a primeira vez que o Censo pergunta. "
                                  "Depende do que a pessoa ou a família declarou."},
            "deficiencia": {"fonte": "IBGE: Censo 2022 (tabelas 10127 e 10130)", "link": "https://sidra.ibge.gov.br/tabela/10127",
                            "metodo": "Pessoas de 2 anos ou mais com deficiência, pelas perguntas sobre dificuldade permanente. Uma pessoa pode ter mais de uma "
                                      "dificuldade: as porcentagens por tipo não somam o total."},
            "nem_nem": {"fonte": "IBGE: PNAD Contínua 2025 (tabela 9415, indicador ODS 8.6.1)", "link": "https://sidra.ibge.gov.br/tabela/9415",
                        "metodo": "Pessoas de 15 a 24 anos que não estavam ocupadas, não estudavam e não faziam treinamento para trabalho."},
            "bolsa": {"fonte": "IBGE: PNAD Contínua 2025 (tabelas 7449 e 7447)", "link": "https://sidra.ibge.gov.br/tabela/7449",
                      "metodo": "Domicílios em que algum morador recebeu rendimento do Programa Bolsa Família (mil), e a porcentagem dos domicílios do estado. "
                                "A porcentagem divide a contagem da PNAD 2025 pelos domicílios ocupados do Censo 2022 (tabela 9936), por isso é aproximada. "
                                "A PNAD também dá quantas pessoas de 10 anos ou mais moram nesses domicílios; não dá a porcentagem de pessoas, "
                                "porque a população por idade não entra nesta conta."},
            "gas": {"fonte": "Portal da Transparência: Gás do Povo (download-de-dados/gas-do-povo)", "link": "https://portaldatransparencia.gov.br/download-de-dados/gas-do-povo",
                    "metodo": "Famílias e pessoas (tamanho da família informado no cadastro) com o benefício pago no mês, por estado. "
                              "O Gás do Povo substituiu o Auxílio Gás (Vale-Gás). Só totais; nenhum CPF ou nome foi guardado. "
                              "A porcentagem usa a população do Censo 2022, por isso é aproximada."},
            "analfabetismo": {"fonte": "IBGE: Censo 2022 (tabela 9543)", "link": "https://sidra.ibge.gov.br/tabela/9543",
                              "metodo": "Analfabetismo de 15 anos ou mais = 100 menos a taxa de alfabetização do Censo 2022."},
        },
        "falhas": falhas,
    }


def _mes_anterior(n: int) -> str:
    hoje = date.today()
    ano, mes = hoje.year, hoje.month - n
    while mes <= 0:
        mes += 12
        ano -= 1
    return f"{ano}{mes:02d}"


def main(argv: list[str]) -> None:
    mes = None
    if "--mes" in argv:
        i = argv.index("--mes")
        mes = argv[i + 1]
        argv = argv[:i] + argv[i + 2:]
    destino = Path(argv[0]) if argv else SAIDA
    r = coletar(mes)
    destino.write_text(json.dumps(r, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{len(r['uf'])} recortes; falhas: {len(r['falhas'])} → {destino}")
    for f in r["falhas"]:
        print("  falha:", f)


if __name__ == "__main__":
    main(sys.argv[1:])
