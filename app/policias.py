"""Fichas das polícias: história, patrono, homenageados, organização (batalhões/delegacias e onde ficam) e efetivo.

Curadas à mão em app/dados/policias/<chave>.json (um arquivo por corporação ou unidade especial; chave "pm:SP" vira o
arquivo pm-SP.json e a rota /policias/pm-SP). Toda afirmação precisa de link da fonte; o que chega sem fonte é
descartado ao carregar. Os números de crimes, mortes e prisões vêm de outras bases (Sinesp, Anuário, ISP-RJ).

Para a PM do Rio, junta os números do ISP-RJ por área de batalhão (AISP), com a tabela AISP → batalhão de
app/dados/policias/aisp-RJ.json.
"""
from __future__ import annotations

import json
import unicodedata
from functools import lru_cache
from pathlib import Path

PASTA = Path(__file__).resolve().parent / "dados" / "policias"
AVISO_AREA = ("Números do ISP-RJ registrados NA ÁREA de cada batalhão (AISP), não necessariamente pelo batalhão: uma morte "
              "por intervenção na área pode ter sido causada por outra unidade da PM (como o BOPE) ou pela Polícia Civil. "
              "Morte por intervenção de agente do Estado é um registro policial; não diz se houve ou não excesso.")


def slug(chave: str) -> str:
    s = unicodedata.normalize("NFKD", chave.replace(":", "-")).encode("ascii", "ignore").decode()
    return "".join(c for c in s if c.isalnum() or c == "-")


def _url(u) -> bool:
    return isinstance(u, str) and u.startswith(("http://", "https://"))


def _item(x, *obrig):
    if not isinstance(x, dict) or not _url(x.get("fonte")) or any(not x.get(k) for k in obrig):
        return None
    return x


def _lista(xs, *obrig):
    return [y for y in (_item(x, *obrig) for x in (xs or [])) if y]


def _ficha(d: dict) -> dict:
    org = d.get("organizacao") if isinstance(d.get("organizacao"), dict) else None
    if org:
        org = {"texto": org.get("texto") or "", "fonte": org.get("fonte") if _url(org.get("fonte")) else None,
               "unidades_total": org.get("unidades_total") if _url(org.get("fonte")) else None,
               "unidades_tipo": org.get("unidades_tipo") or "unidades", "data_ref": org.get("data_ref"),
               "unidades": _lista(org.get("unidades"), "nome")}
        if not org["fonte"] and not org["unidades"]:
            org = None
    ef = _item(d.get("efetivo"))
    if ef and not isinstance(ef.get("valor"), (int, float)):
        ef = None
    return {"chave": d["chave"], "slug": slug(d["chave"]), "nome": d.get("nome") or d["chave"], "sigla": d.get("sigla"),
            "uf": d.get("uf"), "corp": d.get("corp"), "subordinada_a": d.get("subordinada_a"),
            "resumo": _item(d.get("resumo"), "texto"), "fundacao": _item(d.get("fundacao")),
            "historia": sorted(_lista(d.get("historia"), "texto"), key=lambda h: str(h.get("ano") or "")),
            "patrono": _item(d.get("patrono"), "nome"), "homenageados": _lista(d.get("homenageados"), "nome")[:6],
            "organizacao": org, "sede": _item(d.get("sede"), "local"), "efetivo": ef,
            "fontes": [u for u in d.get("fontes_gerais") or [] if _url(u)]}


@lru_cache(maxsize=1)
def fichas() -> dict[str, dict]:
    out = {}
    for arq in sorted(PASTA.glob("*.json")):
        if arq.name.startswith("aisp-"):
            continue
        d = json.loads(arq.read_text(encoding="utf-8"))
        if d.get("chave"):
            f = _ficha(d)
            out[f["slug"]] = f
    # unidades especiais ligadas à corporação mãe
    for f in out.values():
        mae = out.get(slug(f["subordinada_a"])) if f.get("subordinada_a") else None
        if mae is not None:
            mae.setdefault("unidades_especiais", []).append({"slug": f["slug"], "sigla": f["sigla"], "nome": f["nome"]})
    return out


def listar() -> dict:
    return {"itens": [{k: f[k] for k in ("chave", "slug", "nome", "sigla", "uf", "corp", "subordinada_a")} for f in fichas().values()]}


@lru_cache(maxsize=1)
def mapa_aisp() -> dict:
    arq = PASTA / "aisp-RJ.json"
    return json.loads(arq.read_text(encoding="utf-8")) if arq.exists() else {}


def batalhoes_rj(por_aisp: dict) -> dict | None:
    """Junta os totais do ISP por AISP ({aisp: {"anos": {ano: {...}}, "munic": [...], "ultimo_mes": ...}}) com a tabela
    AISP → batalhão. Devolve a lista por batalhão e a série anual do estado."""
    if not por_aisp:
        return None
    mapa = (mapa_aisp().get("aisp") or {})
    anos_todos = sorted({a for d in por_aisp.values() for a in d["anos"]})
    ultimo_mes = max(d.get("ultimo_mes") or "" for d in por_aisp.values())
    completos = [a for a in anos_todos if max(t.get("meses", 12) for d in por_aisp.values() for x, t in d["anos"].items() if x == a) >= 12]
    ref = completos[-1] if completos else anos_todos[-1]
    lista, serie = [], {}
    for a, d in sorted(por_aisp.items(), key=lambda kv: int(kv[0])):
        m = mapa.get(str(a)) or {}
        anos = d["anos"]
        tot = lambda k: sum(t.get(k, 0) for t in anos.values())
        r = anos.get(ref, {})
        lista.append({"aisp": int(a), "batalhao": m.get("batalhao"), "nome": m.get("nome"), "sede": m.get("sede"),
                      "area": m.get("area") or ", ".join(d.get("munic") or []), "fonte_batalhao": m.get("fonte"),
                      "ano_ref": ref, "mortes_intervencao_ano": r.get("mortes_intervencao"),
                      "prisoes_ano": (r.get("prisoes_flagrante") or 0) + (r.get("mandados_cumpridos") or 0),
                      "prisoes_flagrante_ano": r.get("prisoes_flagrante"), "mandados_cumpridos_ano": r.get("mandados_cumpridos"),
                      "pms_mortos_servico_ano": r.get("pms_mortos_servico"),
                      "mortes_intervencao_total": tot("mortes_intervencao"), "prisoes_total": tot("prisoes_flagrante") + tot("mandados_cumpridos"),
                      "pms_mortos_servico_total": tot("pms_mortos_servico"), "desde": min(anos), "ultimo_mes": d.get("ultimo_mes"),
                      "ativa": ref in anos,
                      "anos": {ano: [t.get("mortes_intervencao", 0), t.get("prisoes_flagrante", 0) + t.get("mandados_cumpridos", 0),
                                     t.get("pms_mortos_servico", 0)] for ano, t in sorted(anos.items())}})
        for ano, t in anos.items():
            s = serie.setdefault(ano, {"mortes_intervencao": 0, "prisoes": 0, "pms_mortos_servico": 0, "meses": t.get("meses")})
            s["mortes_intervencao"] += t.get("mortes_intervencao", 0)
            s["prisoes"] += t.get("prisoes_flagrante", 0) + t.get("mandados_cumpridos", 0)
            s["pms_mortos_servico"] += t.get("pms_mortos_servico", 0)
    return {"ano_ref": ref, "ultimo_mes": ultimo_mes, "batalhoes": lista, "serie": dict(sorted(serie.items())),
            "fonte": "ISP-RJ, base de ocorrências por delegacia e mês (BaseDPEvolucaoMensalCisp.csv)",
            "url": "https://www.ispdados.rj.gov.br/Arquivos/BaseDPEvolucaoMensalCisp.csv",
            "mapa_fonte": mapa_aisp().get("fonte"), "mapa_nota": mapa_aisp().get("nota"), "aviso": AVISO_AREA}


def ficha(s: str, por_aisp: dict | None = None) -> dict | None:
    f = fichas().get(s)
    if f is None:
        return None
    f = dict(f)
    if f["chave"] == "pm:RJ" and por_aisp:
        f["isp_batalhoes"] = batalhoes_rj(por_aisp)
    return f
