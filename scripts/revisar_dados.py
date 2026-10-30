"""Agente de revisão dos dados: confere a cópia publicada em site/dados e grava site/dados/revisao.json.

  python -m scripts.revisar_dados [site/dados] [--urls] [--sem-rede]

Não corrige nada e não decide o que é verdade: mostra o que não fecha. Cada conferência vira um item com o que foi esperado e o que
foi encontrado. Níveis: "erro" (número impossível ou dado vencido que o site já está mostrando), "aviso" (merece olhar), "ok" e
"nao_verificado" (a fonte de comparação estava fora do ar). Grupos de conferência:
  frescor     data de cada arquivo e das últimas coletas;
  consistencia somas e contas que precisam fechar entre telas (população, arrecadação, presos, cadeiras, órgãos...);
  contadores  Impostômetro e Gasto Brasil do site contra a leitura ao vivo e contra os marcos publicados na imprensa;
  externas    comparação com o IBGE ao vivo (população do país) e com os links de fonte dos escândalos (`--urls`);
  escandalos  dados dos casos: pessoa ou marco descartado por falta de fonte, conferência vencida;
  noticias    letras quebradas, links repetidos, datas no futuro;
  midia       tamanho do site (limite de 256 MB do Artifact) e cobertura de fotos: prefeitos e governadores eleitos, Congresso, escândalos.
Sai com código 1 quando há "erro" (o robô avisa por e-mail do GitHub).
"""
import json
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
UFS = ["AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG", "MS", "MT", "PA", "PB", "PE", "PI", "PR", "RJ", "RN", "RO", "RR", "RS", "SC", "SE", "SP", "TO"]
ORDEM = {"erro": 0, "aviso": 1, "nao_verificado": 2, "ok": 3}


def fnv1a(texto: str) -> int:
    h = 0x811C9DC5
    for c in texto:
        h = ((h ^ ord(c)) * 0x01000193) & 0xFFFFFFFF
    return h


class Copia:
    """Leitor da cópia estática (manifest + blocos s<N>.json), igual ao do site."""

    def __init__(self, pasta: Path):
        self.pasta = pasta
        self.manifest = self.arquivo("manifest.json") or {}
        self._cache: dict[int, dict] = {}

    def arquivo(self, nome: str):
        try:
            return json.loads((self.pasta / nome).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def get(self, chave: str):
        n = fnv1a(chave) % (self.manifest.get("shards") or 128)
        if n not in self._cache:
            self._cache[n] = self.arquivo(f"s{n}.json") or {}
        v = self._cache[n].get(chave)
        if isinstance(v, dict) and v.get("__arquivo"):
            v = self.arquivo(v["__arquivo"])
        return None if isinstance(v, dict) and "__status" in v else v


class Relatorio:
    def __init__(self):
        self.itens: list[dict] = []

    def add(self, grupo, nivel, titulo, detalhe="", esperado=None, encontrado=None):
        self.itens.append({"grupo": grupo, "nivel": nivel, "titulo": titulo, "detalhe": detalhe, "esperado": esperado, "encontrado": encontrado})

    def ok(self, grupo, titulo, detalhe=""):
        self.add(grupo, "ok", titulo, detalhe)

    def perto(self, grupo, titulo, a, b, tol, nivel="erro", detalhe=""):
        """Dois números que deveriam coincidir (diferença relativa até `tol`)."""
        if a is None or b is None:
            return self.add(grupo, "nao_verificado", titulo, "faltou um dos números", a, b)
        dif = abs(a - b) / max(abs(a), abs(b), 1e-9)
        if dif <= tol:
            self.ok(grupo, titulo, f"{a:,.2f} e {b:,.2f} (diferença {dif:.2%})")
        else:
            self.add(grupo, nivel, titulo, detalhe or f"diferença de {dif:.1%}, acima de {tol:.1%}", round(a, 2), round(b, 2))


def _idade_h(iso: str | None, agora: datetime) -> float | None:
    try:
        d = datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return None
    d = d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    return (agora - d).total_seconds() / 3600


def frescor(c: Copia, r: Relatorio, agora: datetime):
    g = "frescor"
    h = _idade_h(c.manifest.get("gerado_em"), agora)
    if h is None:
        r.add(g, "erro", "Cópia dos dados sem data", "manifest.json ausente ou sem `gerado_em`")
    else:
        r.add(g, "ok" if h < 72 else "aviso" if h < 168 else "erro", "Cópia completa dos dados", f"gerada há {h / 24:.1f} dia(s)", "menos de 3 dias", f"{h / 24:.1f} dias")
    for nome, arq, aviso_h, erro_h in (("Notícias", "noticias.json", 2, 12), ("Contadores externos", "contadores_externos.json", 2, 12)):
        d = c.arquivo(arq)
        h = _idade_h((d or {}).get("atualizado_em"), agora)
        if h is None:
            r.add(g, "aviso", f"{nome}: arquivo ausente", f"{arq} não existe (o site usa a cópia completa no lugar)")
        else:
            r.add(g, "ok" if h < aviso_h else "aviso" if h < erro_h else "erro", f"{nome}: última atualização", f"há {h:.1f} h (o robô roda a cada 15 min)", f"menos de {aviso_h} h", f"{h:.1f} h")
    coletas = c.get("/coletas?limit=30") or []
    erros = [f"{x['fonte']}-{x['tarefa']} {x.get('parametros') or ''}: {(x.get('erro') or '')[:80]}" for x in coletas if x.get("status") == "erro"]
    parciais = [f"{x['fonte']}-{x['tarefa']}: {(x.get('erro') or '')[:80]}" for x in coletas if x.get("status") == "parcial"]
    if erros:
        r.add(g, "aviso", f"{len(erros)} coleta(s) com erro nas últimas 30", "; ".join(erros[:6]))
    if parciais:
        r.add(g, "aviso", f"{len(parciais)} coleta(s) parcial(is) nas últimas 30", "; ".join(parciais[:6]))
    if coletas and not erros and not parciais:
        r.ok(g, "Últimas 30 coletas", "todas terminaram sem erro")


def consistencia(c: Copia, r: Relatorio):
    g = "consistencia"
    mapa = (c.get("/mapa/estados") or {}).get("estados") or {}
    if set(mapa) != set(UFS):
        r.add(g, "erro", "Mapa dos estados sem as 27 UFs", "", "27 UFs", f"{len(mapa)} UFs: faltam {sorted(set(UFS) - set(mapa))}")
    else:
        r.ok(g, "Mapa dos estados", "27 UFs presentes")
    ruins = [f"{uf}.{m}={v}" for uf, d in mapa.items() for m, v in d.items() if v is None or (isinstance(v, (int, float)) and (v != v or v < 0))]
    if ruins:
        r.add(g, "aviso", "Valores vazios ou negativos no mapa dos estados", ", ".join(ruins[:12]), "números não negativos", f"{len(ruins)} casos")
    pop = sum(d.get("pop") or 0 for d in mapa.values())
    if pop:
        r.add(g, "ok" if 205e6 < pop < 222e6 else "erro", "População somada dos estados", f"{pop:,.0f} habitantes", "entre 205 e 222 milhões", f"{pop:,.0f}")
    seg = c.get("/seguranca") or {}
    b = (seg.get("brasil") or {})
    if b.get("populacao") and pop:
        r.perto(g, "População: mapa dos estados × Segurança", pop, b["populacao"], 0.01, "aviso")
    p = b.get("prisional") or {}
    if p:
        r.perto(g, "Presos: celas + domiciliar = população presa", p["populacao_celas"] + p["populacao_domiciliar"], p["populacao"], 0.001)
        r.perto(g, "Déficit de vagas = presos em celas − vagas", p["populacao_celas"] - p["vagas"], p["deficit_vagas"], 0.01)
        if b.get("populacao"):
            r.perto(g, "Taxa de aprisionamento por 100 mil", p["populacao"] / b["populacao"] * 1e5, p["taxa_aprisionamento"], 0.01)
    est = seg.get("estados") or {}
    soma_presos = sum(((e.get("prisional") or {}).get("populacao") or 0) for e in est.values())
    if p and soma_presos:
        r.perto(g, "Presos: soma dos estados × Brasil", soma_presos, p["populacao"], 0.01)
    flux = c.get("/fluxo-federativo") or {}
    fe = flux.get("estados") or []
    if fe:
        r.perto(g, "Arrecadação: fluxo federativo × mapa dos estados", sum(e["arrecadado"] or 0 for e in fe if e["uf"] in mapa),
                sum(d.get("arr") or 0 for d in mapa.values()), 0.001)
        erros = []
        for e in fe:
            if e.get("arrecadado") and e.get("retornado") and e.get("retorno_por_real_arrecadado"):
                if abs(e["retornado"] / e["arrecadado"] - e["retorno_por_real_arrecadado"]) > 0.01 * e["retorno_por_real_arrecadado"] + 1e-3:
                    erros.append(e["uf"])
        r.add(g, "erro" if erros else "ok", "Retorno por R$ 1 arrecadado = retornado ÷ arrecadado", f"não fecha em: {', '.join(erros)}" if erros else "fecha nos 27 estados")
        part = sum(e.get("participacao_arrecadacao_nacional") or 0 for e in fe)
        r.add(g, "ok" if 0.97 <= part <= 1.03 else "aviso", "Participação dos estados na arrecadação soma 100%", f"{part:.1%}", "100%", f"{part:.1%}")
    org = c.get("/orgaos") or {}
    if org.get("itens"):
        r.perto(g, "Órgãos: total pago = soma dos órgãos", sum(i.get("pago") or 0 for i in org["itens"]), org.get("total_pago"), 0.001)
        sem = [i["nome"] for i in org["itens"] if (i.get("pago") or 0) > (i.get("orcamento_atualizado") or 0) * 1.001 and i.get("orcamento_atualizado")]
        r.add(g, "aviso" if sem else "ok", "Órgãos que pagaram mais que o orçamento atualizado", ", ".join(sem[:5]) if sem else "nenhum")
    dv = (c.get("/dividas/estados") or {}).get("estados") or []
    inv = [d["uf"] for d in dv if (g_ := d.get("governo_estadual")) and g_.get("consolidada") and g_.get("consolidada_liquida")
           and g_["consolidada_liquida"]["valor"] > g_["consolidada"]["valor"]]
    if dv:
        r.add(g, "erro" if inv else "ok", "Dívida líquida não passa da consolidada", f"passa em: {', '.join(inv)}" if inv else "confere nos estados com dado")
    comp = c.get("/partidos/composicao") or {}
    cam = sum((comp.get("camara") or {}).get("partidos", {}).values())
    sen = sum((comp.get("senado") or {}).get("partidos", {}).values())
    if cam:
        r.add(g, "ok" if cam <= 513 else "erro", "Cadeiras da Câmara", f"{cam} deputados em exercício na contagem", "no máximo 513", cam)
    if sen:
        r.add(g, "ok" if sen <= 81 else "erro", "Cadeiras do Senado", f"{sen} senadores em exercício na contagem", "no máximo 81", sen)
    # obras: valor que parece erro de cadastro precisa estar marcado e a soma não pode depender dele
    obras = (c.get("/obras") or {}).get("itens") or []
    if obras:
        from app.obras_valor import valor_suspeito
        devia = [o for o in obras if valor_suspeito(o.get("nome"), o.get("descricao"), o.get("tipo"), o.get("valor_previsto"))]
        sem_marca = [o for o in devia if not o.get("valor_suspeito")]
        if sem_marca:
            r.add(g, "aviso", "Obras com valor suspeito sem marcação", f"{len(sem_marca)} obra(s), ex.: {sem_marca[0]['nome'][:60]} "
                  f"(R$ {sem_marca[0]['valor_previsto'] / 1e9:,.0f} bi). A cópia é anterior à regra ou o robô ainda não exportou de novo.")
        else:
            r.ok(g, "Obras com valor suspeito", f"{len(devia)} marcada(s) na cópia e fora das somas" if devia else "nenhuma na amostra")
    fs = c.get("/fontes/status") or {}
    resumo_fontes = fs.get("resumo") or {}
    total_fontes = sum(resumo_fontes.values()) if resumo_fontes else 0
    if total_fontes and resumo_fontes.get("nunca_coletada") == total_fontes:
        r.add(g, "erro", "Situação das fontes mostra tudo como nunca coletada", f"{total_fontes} de {total_fontes}: o painel não está achando as coletas")
    elif total_fontes:
        r.ok(g, "Situação das fontes", f"{resumo_fontes.get('ok', 0)} em dia, {resumo_fontes.get('nunca_coletada', 0)} nunca coletadas")
    saude = c.get("/saude/painel") or {}
    if saude:
        b = saude.get("brasil") or {}
        if b.get("ubs") is not None:
            r.add(g, "ok" if 40_000 <= b["ubs"] <= 60_000 else "aviso", "Saúde: UBS no país", f"{b['ubs']:,} UBS ({b.get('ubs_por_100mil')} por 100 mil hab.)", "entre 40 mil e 60 mil", b["ubs"])
        if b.get("mm_vagas"):
            r.add(g, "ok" if b["mm_ocupadas"] <= b["mm_vagas"] else "erro", "Saúde: vagas ocupadas do Mais Médicos não passam das vagas", f"{b['mm_ocupadas']:,} de {b['mm_vagas']:,}")
        if b.get("gasto_estados_saude") and b.get("gasto_uniao_saude") and not (20e9 < b["gasto_uniao_saude"] < 600e9):
            r.add(g, "aviso", "Saúde: gasto da União fora do esperado", f"R$ {b['gasto_uniao_saude'] / 1e9:,.0f} bi", "entre R$ 20 bi e R$ 600 bi", round(b["gasto_uniao_saude"]))
    parl = (c.get("/parlamentares") or {}).get("itens") or []
    nomes = {}
    for x in parl:
        nomes.setdefault((x["casa"], x["nome"]), 0)
        nomes[(x["casa"], x["nome"])] += 1
    rep = [f"{casa}:{n}" for (casa, n), k in nomes.items() if k > 1]
    r.add(g, "aviso" if rep else "ok", "Parlamentares repetidos na lista", ", ".join(rep[:8]) if rep else "nenhum nome repetido na mesma casa")


def contadores(c: Copia, r: Relatorio, agora: datetime, rede: bool):
    g = "contadores"
    ext = c.arquivo("contadores_externos.json") or {}
    ref = {}
    try:
        ref = json.loads((RAIZ / "app" / "dados" / "contadores_referencia.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    for chave, nome in (("impostometro", "Impostômetro"), ("gastometro", "Gasto Brasil")):
        e = (ext.get(chave) or {}).get("ao_vivo")
        if e:
            t = datetime.fromisoformat(e["quando"])
            agora_proj = e["base"] + e["taxa"] * max(0, (agora - t).total_seconds())
            r.ok(g, f"{nome}: valor no site", f"R$ {agora_proj / 1e12:.3f} tri projetado até agora (lido às {t.astimezone(timezone(timedelta(hours=-3))):%d/%m %H:%M})")
            # contra os marcos já noticiados: o total precisa ser maior e o ritmo desde o marco, parecido com o ritmo publicado
            marcos = sorted(((ref.get(chave) or {}).get("marcos") or []), key=lambda m: m["data"])
            if marcos:
                m = marcos[-1]
                dias = (t.date() - date.fromisoformat(m["data"])).days
                if e["base"] < m["valor"]:
                    r.add(g, "erro", f"{nome}: total menor que o marco já noticiado", f"marco de {m['data']}: R$ {m['valor'] / 1e12:.2f} tri", m["valor"], round(e["base"]))
                elif dias >= 5:
                    medio = (e["base"] - m["valor"]) / dias / 86400
                    dif = abs(medio - e["taxa"]) / e["taxa"]
                    r.add(g, "ok" if dif <= 0.10 else "aviso", f"{nome}: ritmo desde o marco de {m['data'][8:]}/{m['data'][5:7]} × ritmo publicado",
                          f"média desde o marco R$ {medio:,.0f}/s; ritmo publicado R$ {e['taxa']:,.0f}/s (diferença {dif:.1%}). Marcos da imprensa e contador podem usar critérios diferentes (ex.: correção pelo IPCA).",
                          round(e["taxa"]), round(medio))
        else:
            r.add(g, "aviso", f"{nome}: sem leitura direta", "o site está usando marco da imprensa ou a conta própria")
    if rede and ext:
        try:
            from app.collectors import contadores_externos as ce
            vivo = ce.ler_impostometro()["brasil"]
            e = ext["impostometro"]["ao_vivo"]
            t_ext = datetime.fromisoformat(e["quando"])
            t_v = datetime.fromisoformat(vivo["como_de"])
            r.perto(g, "Impostômetro: arquivo do site × leitura ao vivo agora", e["base"] + e["taxa"] * (t_v - t_ext).total_seconds(), vivo["total"], 0.002, "aviso",
                    "o arquivo do robô está desatualizado em relação à fonte")
            vg = ce.ler_gastometro()
            e = ext["gastometro"]["ao_vivo"]
            t_ext, t_v = datetime.fromisoformat(e["quando"]), datetime.fromisoformat(vg["como_de"])
            r.perto(g, "Gasto Brasil: arquivo do site × leitura ao vivo agora", e["base"] + e["taxa"] * (t_v - t_ext).total_seconds(), vg["total"]["total"], 0.002, "aviso")
        except Exception as ex:  # noqa: BLE001
            r.add(g, "nao_verificado", "Leitura ao vivo do Impostômetro e do Gasto Brasil", f"{type(ex).__name__}: {str(ex)[:120]}")


def externas(c: Copia, r: Relatorio, rede: bool, urls: bool):
    g = "externas"
    if not rede:
        return
    mapa = (c.get("/mapa/estados") or {}).get("estados") or {}
    pop = sum(d.get("pop") or 0 for d in mapa.values())
    try:
        from app import http
        resp = http.get_json("https://servicodados.ibge.gov.br/api/v3/agregados/6579/periodos/-1/variaveis/9324", params={"localidades": "N1[all]"})
        ibge = float(next(iter(resp[0]["resultados"][0]["series"][0]["serie"].values())))
        r.perto(g, "População do Brasil: site × IBGE ao vivo", pop, ibge, 0.01, "aviso")
    except Exception as ex:  # noqa: BLE001
        r.add(g, "nao_verificado", "População do Brasil no IBGE", f"{type(ex).__name__}: {str(ex)[:120]}")
    if urls:
        _conferir_links(r)


def _conferir_links(r: Relatorio):
    """Links de fonte dos escândalos: só 404/410 e falha de conexão contam (muitos jornais bloqueiam robôs com 403/429)."""
    from concurrent.futures import ThreadPoolExecutor

    import httpx
    from app import escandalos
    links = {}
    for slug, caso in escandalos.casos().items():
        for u in [*caso["fontes"], *[p["fonte"] for p in caso["pessoas"]], *[a["fonte"] for a in caso["andamento"]]]:
            links.setdefault(u, slug)

    def ver(u):
        try:
            x = httpx.get(u, timeout=20, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0 (BRASIL+ revisor de links)"})
            return u, x.status_code
        except Exception as e:  # noqa: BLE001
            return u, type(e).__name__
    with ThreadPoolExecutor(8) as ex:
        res = list(ex.map(ver, links))
    mortos = [(u, s) for u, s in res if s in (404, 410) or isinstance(s, str)]
    bloqueados = sum(1 for _, s in res if s in (401, 403, 429))
    if mortos:
        r.add("externas", "aviso", f"{len(mortos)} link(s) de fonte dos escândalos não abrem", "; ".join(f"{links[u]}: {u} ({s})" for u, s in mortos[:10]), "links abertos", f"{len(mortos)} de {len(links)}")
    else:
        r.ok("externas", "Links de fonte dos escândalos", f"{len(links)} links, nenhum quebrado ({bloqueados} sites bloquearam o robô e não puderam ser conferidos)")


def escandalos_(r: Relatorio, agora: datetime):
    g = "escandalos"
    from app import escandalos
    pasta = escandalos.PASTA
    carregados = escandalos.casos()
    for arq in sorted(pasta.glob("*.json")):
        bruto = json.loads(arq.read_text(encoding="utf-8"))
        caso = carregados.get(bruto.get("slug"))
        if not caso:
            r.add(g, "erro", f"Caso {arq.stem} não foi carregado", "falta slug ou nome")
            continue
        perdidas = [p.get("nome") for p in bruto.get("pessoas") or [] if p.get("nome") not in {x["nome"] for x in caso["pessoas"]}]
        marcos = len(bruto.get("andamento") or []) - len(caso["andamento"])
        if perdidas or marcos:
            r.add(g, "aviso", f"{caso['nome']}: dado descartado por falta de fonte", f"pessoas sem fonte: {perdidas[:5] or 'nenhuma'}; marcos sem fonte: {max(marcos, 0)}")
        try:
            idade = (agora.date() - date.fromisoformat(caso["verificado_em"])).days
        except (TypeError, ValueError):
            idade = None
        if idade is None or idade > 90:
            r.add(g, "aviso", f"{caso['nome']}: conferência velha", f"verificado em {caso['verificado_em']} ({idade} dias)", "até 90 dias", idade)
        sem_data = [p["nome"] for p in caso["pessoas"] if p["situacao"] and not p["data_situacao"]]
        if sem_data:
            r.add(g, "aviso", f"{caso['nome']}: situação jurídica sem data", ", ".join(sem_data[:6]))
    if not any(i["grupo"] == g and i["nivel"] != "ok" for i in r.itens):
        r.ok(g, "Escândalos", f"{len(carregados)} casos: tudo com fonte, data de situação e conferência recente")


def noticias(c: Copia, r: Relatorio, agora: datetime):
    g = "noticias"
    d = c.arquivo("noticias.json") or c.get("/noticias") or {}
    it = d.get("itens") or []
    if not it:
        return r.add(g, "aviso", "Sem notícias", "nem noticias.json nem a cópia completa trazem matérias")
    quebr = re.compile(r"�|[^\W\d_]\?{1,2}[^\W\d_]")
    ruins = [i["titulo"][:60] for i in it if quebr.search(f"{i['titulo']} {i.get('resumo') or ''}")]
    futuras = [i["titulo"][:60] for i in it if (i.get("data") or "") > (agora + timedelta(hours=2)).isoformat()]
    links = [i["link"] for i in it]
    rep = len(links) - len(set(links))
    r.add(g, "aviso" if ruins else "ok", "Matérias com letras quebradas", "; ".join(ruins[:4]) if ruins else "nenhuma")
    r.add(g, "aviso" if futuras else "ok", "Matérias com data no futuro", "; ".join(futuras[:4]) if futuras else "nenhuma")
    r.add(g, "aviso" if rep else "ok", "Links de matéria repetidos", f"{rep} repetido(s)" if rep else "nenhum")
    novo = max((i.get("data") or "" for i in it), default="")
    h = _idade_h(novo, agora)
    if h is not None:
        r.add(g, "ok" if h < 6 else "aviso", "Matéria mais recente", f"publicada há {h:.1f} h", "menos de 6 h", f"{h:.1f} h")


def midia(c: Copia, r: Relatorio):
    g = "midia"
    site = c.pasta.parent
    if (site / "index.html").exists():
        mb = sum(f.stat().st_size for f in site.rglob("*") if f.is_file()) / 1048576
        r.add(g, "ok" if mb < 235 else "aviso" if mb < 250 else "erro", "Tamanho do site publicado",
              f"{mb:.0f} MB de {site.name}/ (o Artifact aceita até 256 MB por versão)", "menos de 235 MB", f"{mb:.0f} MB")
    pasta = site / "midia"
    try:
        idx = json.loads((pasta / "indice.json").read_text(encoding="utf-8"))
        chaves = set()
        for i in range(idx["blocos"]):
            chaves |= set(json.loads((pasta / f"fotos_{i}.json").read_text(encoding="utf-8")))
    except (OSError, ValueError, KeyError):
        return r.add(g, "nao_verificado", "Fotos", "site/midia não encontrado ou sem índice")

    def cobertura(titulo, total, com, minimo):
        if not total:
            return
        pct = com / total
        r.add(g, "ok" if pct >= minimo else "aviso", titulo, f"{com} de {total} com foto ({pct:.0%})", f"pelo menos {minimo:.0%}", f"{pct:.0%}")
    for cargo, rotulo, minimo in (("PREFEITO", "Prefeitos eleitos", 0.9), ("GOVERNADOR", "Governadores eleitos", 0.95), ("PRESIDENTE", "Presidente eleito", 1.0)):
        lista = (c.get(f"/candidatos?cargo={cargo}&eleitos=true") or {}).get("itens") or []
        cobertura(f"Fotos: {rotulo}", len(lista), sum(1 for x in lista if f"tse:{x.get('sq_candidato')}" in chaves), minimo)
    parl = [x for x in ((c.get("/parlamentares") or {}).get("itens") or []) if x.get("casa") in ("camara", "senado") and x.get("foto_url")]
    cobertura("Fotos: deputados e senadores", len(parl), sum(1 for x in parl if x["foto_url"] in chaves), 0.95)
    try:
        from app import escandalos
        pessoas = {p["nome"] for caso in escandalos.casos().values() for p in caso["pessoas"]}
        com = sum(1 for n in pessoas if f"esc:{n}" in chaves)
        r.add(g, "ok" if com / max(1, len(pessoas)) >= 0.5 else "aviso", "Fotos: pessoas dos escândalos",
              f"{com} de {len(pessoas)} com foto ({com / max(1, len(pessoas)):.0%}); só entra foto de fonte oficial ou de verbete que cita o caso")
    except Exception as ex:  # noqa: BLE001
        r.add(g, "nao_verificado", "Fotos: pessoas dos escândalos", f"{type(ex).__name__}: {str(ex)[:100]}")


def revisar(pasta: Path, agora: datetime | None = None, rede: bool = True, urls: bool = False) -> dict:
    agora = agora or datetime.now(timezone.utc)
    c, r = Copia(pasta), Relatorio()
    for etapa in (lambda: frescor(c, r, agora), lambda: consistencia(c, r), lambda: contadores(c, r, agora, rede),
                  lambda: externas(c, r, rede, urls), lambda: escandalos_(r, agora), lambda: noticias(c, r, agora), lambda: midia(c, r)):
        try:
            etapa()
        except Exception as ex:  # noqa: BLE001 - uma conferência quebrada não impede as outras
            r.add("revisor", "erro", "A conferência falhou ao rodar", f"{type(ex).__name__}: {str(ex)[:200]}")
    r.itens.sort(key=lambda i: (ORDEM[i["nivel"]], i["grupo"]))
    cont = {n: sum(1 for i in r.itens if i["nivel"] == n) for n in ORDEM}
    return {"gerado_em": agora.isoformat(timespec="seconds"), "resumo": cont, "itens": r.itens,
            "aviso": "Conferência automática de consistência e atualização. Não substitui a leitura da fonte oficial e não prova que um número está certo: "
                     "mostra o que não fecha entre telas, contra a fonte ao vivo e contra os marcos publicados."}


def markdown(rel: dict) -> str:
    s = rel["resumo"]
    linhas = [f"## Revisão dos dados — {s['erro']} erro(s), {s['aviso']} aviso(s), {s['ok']} ok, {s['nao_verificado']} não verificado(s)", ""]
    for nivel, rotulo in (("erro", "Erros"), ("aviso", "Avisos"), ("nao_verificado", "Não verificados")):
        itens = [i for i in rel["itens"] if i["nivel"] == nivel]
        if itens:
            linhas += [f"### {rotulo}", "", "| Grupo | Conferência | Detalhe |", "|---|---|---|"]
            linhas += [f"| {i['grupo']} | {i['titulo']} | {str(i['detalhe']).replace('|', '/')[:300]} |" for i in itens]
            linhas.append("")
    linhas.append(f"{s['ok']} conferência(s) passaram.")
    return "\n".join(linhas)


def main(argv):
    args = [a for a in argv if not a.startswith("--")]
    pasta = Path(args[0] if args else "site/dados")
    rel = revisar(pasta, rede="--sem-rede" not in argv, urls="--urls" in argv)
    (pasta / "revisao.json").write_text(json.dumps(rel, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(markdown(rel))
    sys.exit(1 if rel["resumo"]["erro"] else 0)


if __name__ == "__main__":
    main(sys.argv[1:])
