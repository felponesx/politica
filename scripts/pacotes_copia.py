"""Pacotes da cópia estática: as chaves pequenas que cada tela usa ficam juntas num arquivo só.

Sem isso, cada chave mora numa parte (s<N>.json, ~450 KB) escolhida pelo hash do nome, e a tela inicial chegava a baixar
dezenas de partes (mais de 20 MB) para ler uns 100 KB de dados. Os pacotes NÃO tiram nada das partes: o site usa o pacote
quando o manifest o anuncia e, se o pacote falhar, continua lendo a parte como antes.

Também grava resumos prontos para a tela inicial (contagem de proposições por tipo e os últimos registros), que antes
exigiam baixar listas inteiras (/proposicoes ~2,4 MB, /contratos ~1,5 MB).

Uso numa cópia já pronta (sem banco):  python -m scripts.pacotes_copia [site/dados]
Pacotes: inicio, eleicoes (só na tela de eleições), economia, governo, escandalos, ambiente e geral (ver SECOES).
O exportador (scripts/exportar_snapshot.py) chama `gravar_pacotes` ao gerar a cópia.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path

GRANDE = 150_000  # mesmo limite das partes: acima disso a resposta já tem arquivo próprio (dados/g/…)

INICIO = [
    "/contadores", "/mapa/estados", "/economia?nomes=ipca_12m,selic,desemprego,dolar,pib_12m", "/gastos/entes",
    "/eleicoes/anos", "/orgaos", "/dividas/estados",
    # resumos montados aqui (ver acrescentar_resumos)
    "/inicio/proposicoes", "/votacoes?limit=2", "/proposicoes?limit=1", "/contratos?limit=1&ordenar=data",
]
EXTRAS_TELAS = [r"^/orgaos\?ano=\d{4}$", r"^/gastos/evolucao\?esfera=U$", r"^/gastos/funcao\?ano=\d{4}&esfera=U$"]
# chaves das telas agrupadas por assunto (primeiro trecho do caminho): cada pacote fica perto do tamanho de uma parte (~450 KB)
# e traz tudo o que as telas daquele assunto leem. Trecho que não está aqui vai para "geral".
SECOES = {
    "economia": ["economia", "indicadores", "energia-tarifas", "iva", "renuncia-fiscal", "aeroportos", "transito", "acidentes-rodovias",
                 "caged", "trabalho", "social", "indicadores-sociais", "saneamento"],
    "governo": ["orgaos", "cortes", "emendas", "gastos", "historico-estados", "cartao-corporativo", "servidores", "viagens", "fundos",
                "dividas", "recuperacao-judicial", "fluxo-federativo", "economia-empresas", "resumo-contratos", "fornecedores-cruzados",
                "empresas-setores", "obras-gestao"],
    "escandalos": ["escandalos", "escandalos-fila", "crimes-politicos", "sancoes", "tcu-inabilitados", "tcu-irregulares", "lista-suja",
                   "doadores", "faccoes", "julgamentos", "cpis", "legislacao-resumo", "diarios-oficiais"],
    "ambiente": ["saude", "alertas-mapbiomas", "ambiente", "multas-ambientais", "malha"],
}
FORA = [r"^/policias/.+"]  # fichas de uma polícia: cada página lê uma só; no pacote sairia mais caro


def _texto(v) -> str:
    return json.dumps(v, ensure_ascii=False, separators=(",", ":"), default=str)


def _itens(v):
    return (v or {}).get("itens") or [] if isinstance(v, dict) else []


def acrescentar_resumos(dados: dict) -> list[str]:
    """Resumos da tela inicial a partir das listas completas que já estão na cópia. Devolve as chaves criadas."""
    novas = []
    props = _itens(dados.get("/proposicoes"))[:4000]  # o site contava as primeiras 4.000 (todosItens com teto 4000)
    if props:
        por = {}
        for p in props:
            t = p.get("sigla_tipo") or "?"
            por[t] = por.get(t, 0) + 1
        datas = sorted(p["data_apresentacao"] for p in props if p.get("data_apresentacao"))
        dados["/inicio/proposicoes"] = {"por_tipo": por, "total": len(props), "data_min": datas[0] if datas else None,
                                        "data_max": datas[-1] if datas else None}
        novas.append("/inicio/proposicoes")
    for base, chave, n in (("/votacoes", "/votacoes?limit=2", 2), ("/proposicoes", "/proposicoes?limit=1", 1),
                           ("/contratos?ordenar=data", "/contratos?limit=1&ordenar=data", 1)):
        v = dados.get(base)
        if isinstance(v, dict) and "itens" in v:
            meta = {k: x for k, x in v.items() if k not in ("itens", "__completa")}
            hoje = date.today().isoformat()
            # data no futuro é erro de digitação da fonte (há contratos do PNCP "assinados" em 2027): não vira "última atualização"
            validos = [x for x in v["itens"] if str(x.get("data_assinatura") or x.get("data") or x.get("data_apresentacao") or "")[:10] <= hoje]
            dados[chave] = {**meta, "total": len(v["itens"]), "itens": validos[:n]}
            novas.append(chave)
    return novas


def _ultimo_ano_eleicao(dados) -> int | None:
    anos = [int(m.group(1)) for k in dados for m in [re.match(r"^/eleicoes/(\d{4})/[A-Z]{2}/mapa\?", k)] if m]
    return max(anos) if anos else None


def montar_pacotes(dados: dict, fixas) -> dict:
    """{arquivo: {"telas": [...]|None, "valores": {chave: valor}}}. Só entram chaves pequenas (abaixo de GRANDE)."""
    pequeno = {k for k, v in dados.items() if len(_texto(v).encode()) <= GRANDE}
    usadas: set[str] = set()

    def pegar(chaves):
        out = {k: dados[k] for k in chaves if k in pequeno and k not in usadas}
        usadas.update(out)
        return out

    inicio = pegar(INICIO + sorted(k for k in dados if re.match(r"^/estados/[A-Z]{2}/fluxo$", k)))
    ano = _ultimo_ano_eleicao(dados)
    ele = []
    if ano:
        ele = [k for k in dados if re.match(rf"^/eleicoes/{ano}/[A-Z]{{2}}/mapa\?cargo=PRESIDENTE&turno=1$", k)]
        ele += [f"/eleicoes/{ano}/estados?cargo=PRESIDENTE&turno=1", f"/eleicoes/{ano}/cargos"]
    ele += sorted(k for k in dados if re.match(r"^/malhas/[A-Z]{2}$", k))
    eleicoes = pegar(ele)
    candidatas = [k for k in fixas if not any(re.match(p, k) for p in FORA)] + sorted(k for k in dados if any(re.match(p, k) for p in EXTRAS_TELAS))
    secao_de = {seg: nome for nome, segs in SECOES.items() for seg in segs}
    grupos: dict[str, list] = {}
    for k in candidatas:
        grupos.setdefault(secao_de.get(k.split("?")[0].strip("/").split("/")[0], "geral"), []).append(k)
    out = {}
    if inicio:
        out["p/inicio.json"] = {"telas": None, "valores": inicio}
    for nome in [*SECOES, "geral"]:
        vals = pegar(grupos.get(nome, []))
        if vals:
            out[f"p/{nome}.json"] = {"telas": None, "valores": vals}
    if eleicoes:  # malhas e mapas só valem juntos na tela de eleições; nas outras, ler um estado pela parte sai mais barato
        out["p/eleicoes.json"] = {"telas": ["eleicoes"], "valores": eleicoes}
    return out


def gravar_pacotes(pasta: Path, dados: dict, fixas) -> dict:
    """Grava dados/p/*.json e devolve o bloco "pacotes" do manifest. `dados` recebe os resumos novos."""
    acrescentar_resumos(dados)
    pacotes = montar_pacotes(dados, fixas)
    (pasta / "p").mkdir(exist_ok=True)
    manifest = {}
    for arq, p in pacotes.items():
        (pasta / arq).write_text(_texto(p["valores"]), encoding="utf-8")
        manifest[arq] = {"chaves": sorted(p["valores"])} | ({"telas": p["telas"]} if p["telas"] else {})
    return manifest


def ler_copia(pasta: Path) -> dict:
    m = json.loads((pasta / "manifest.json").read_text(encoding="utf-8"))
    dados = {}
    for i in range(m["shards"]):
        for k, v in json.loads((pasta / f"s{i}.json").read_text(encoding="utf-8")).items():
            if isinstance(v, dict) and "__arquivo" in v:
                arq = pasta / v["__arquivo"]
                v = json.loads(arq.read_text(encoding="utf-8")) if arq.exists() else None
            if v is not None:
                dados[k] = v
    return dados


def main(argv):
    from scripts.exportar_snapshot import FIXAS
    pasta = Path(argv[0] if argv else "site/dados")
    dados = ler_copia(pasta)
    bloco = gravar_pacotes(pasta, dados, FIXAS)
    mpath = pasta / "manifest.json"
    m = json.loads(mpath.read_text(encoding="utf-8"))
    m["pacotes"] = bloco
    mpath.write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")
    for arq, p in bloco.items():
        print(f"{arq}: {len(p['chaves'])} chaves, {(pasta / arq).stat().st_size // 1024} KB" + (f" (só em {p['telas']})" if p.get("telas") else ""))


if __name__ == "__main__":
    main(sys.argv[1:])
