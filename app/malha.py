"""Malha municipal versionada: de onde veio cada geometria (IBGE oficial, OSM provisório…), validação, ativação controlada e comparação.

Regras: (1) cada geometria carrega a origem e a versão (`MalhaFonte`); fontes diferentes nunca se misturam sem registro; (2) a malha OFICIAL do IBGE vale sobre a provisória do OSM; (3) trocar a geometria
usada é uma transação só — desativa as antigas e ativa as novas, ou nada acontece — e NUNCA apaga a antiga (histórico); (4) só uma fonte `validada` pode ser ativada.
Área e perímetro saem da geometria COMPLETA (projeção Albers de área igual); no banco fica a geometria simplificada (`tolerancia_graus`), que basta para testar pontos e comparar."""
import logging
from datetime import datetime

import numpy as np
import shapely
from shapely import wkb
from shapely.geometry import MultiPolygon, Polygon
from shapely.ops import unary_union
from shapely.strtree import STRtree
from shapely.validation import explain_validity, make_valid
from sqlalchemy import func, select

from app.models import MalhaFonte, MalhaMunicipio, Municipio

log = logging.getLogger("brasilplus.malha")
R_TERRA = 6371008.8
TOLERANCIA = 0.0005          # graus (~55 m): simplificação da geometria guardada
ESPECIAIS = {"4300001": "Lagoa Mirim (corpo d'água, não é município)", "4300002": "Lagoa dos Patos (corpo d'água, não é município)"}   # polígonos que o IBGE põe na malha com código próprio
TOTAL_MUNICIPIOS = 5571      # malha municipal de 2025: os 5.570 municípios de antes (inclui o DF e Fernando de Noronha) + Boa Esperança do Norte (MT, 5101837), instalado em 2025
# Nove municípios têm código oficial cujo 7º dígito NÃO segue o algoritmo do dígito verificador (conferido na malha real de 2025 e é a lista conhecida do IBGE): são exceções, não erros.
EXCECOES_DIGITO = {"2201919": "Bom Princípio do Piauí", "2201988": "Brejo do Piauí", "2202251": "Canavieira", "2611533": "Quixaba", "3117836": "Cônego Marinho", "3152131": "Ponto Chique",
                   "4305871": "Coronel Barros", "5203939": "Buriti de Goiás", "5203962": "Buritinópolis"}
CODIGO_UF = {"11": "RO", "12": "AC", "13": "AM", "14": "RR", "15": "PA", "16": "AP", "17": "TO", "21": "MA", "22": "PI", "23": "CE", "24": "RN", "25": "PB", "26": "PE", "27": "AL", "28": "SE", "29": "BA",
             "31": "MG", "32": "ES", "33": "RJ", "35": "SP", "41": "PR", "42": "SC", "43": "RS", "50": "MS", "51": "MT", "52": "GO", "53": "DF"}


# ---------------- códigos ----------------
def digito_municipio(cod6: str) -> int:
    """Dígito verificador do código de município do IBGE (7º dígito): pesos 1,2,1,2,1,2 sobre os 6 primeiros; produto ≥ 10 soma os algarismos; (10 − soma mod 10) mod 10."""
    soma = 0
    for i, c in enumerate(cod6):
        p = int(c) * (1 if i % 2 == 0 else 2)
        soma += p // 10 + p % 10
    return (10 - soma % 10) % 10


def codigo_valido(cod: str, uf: str | None = None) -> tuple[bool, str]:
    cod = str(cod or "")
    if cod in ESPECIAIS:
        return True, ESPECIAIS[cod]
    if not (len(cod) == 7 and cod.isdigit()):
        return False, "código não tem 7 dígitos"
    if CODIGO_UF.get(cod[:2]) is None:
        return False, "prefixo de UF inexistente"
    if uf and CODIGO_UF[cod[:2]] != uf:
        return False, f"prefixo {cod[:2]} é de {CODIGO_UF[cod[:2]]}, não de {uf}"
    if digito_municipio(cod[:6]) != int(cod[6]):
        if cod in EXCECOES_DIGITO:
            return True, "exceção conhecida do IBGE: o dígito do código oficial não segue o algoritmo"
        return False, "dígito verificador não confere"
    return True, "ok"


# ---------------- geometria ----------------
def _albers_np(xy):
    """Albers de área igual (cone padrão para o Brasil: paralelos −2° e −22°, origem −12°/−54°), esfera de R = 6.371.008,8 m, vetorizado (Nx2 lon/lat em graus → Nx2 metros)."""
    l1, l2, l0, m0 = (np.radians(v) for v in (-2.0, -22.0, -12.0, -54.0))
    n = (np.sin(l1) + np.sin(l2)) / 2
    c = np.cos(l1) ** 2 + 2 * n * np.sin(l1)
    rho0 = np.sqrt(c - 2 * n * np.sin(l0)) / n
    lo, la = np.radians(xy[:, 0]), np.radians(xy[:, 1])
    rho = np.sqrt(c - 2 * n * np.sin(la)) / n
    th = n * (lo - m0)
    return np.column_stack((R_TERRA * rho * np.sin(th), R_TERRA * (rho0 - rho * np.cos(th))))


def projetar(geom):
    return shapely.transform(geom, _albers_np)


def area_km2(geom) -> float:
    return projetar(geom).area / 1e6


def _comprimento_m(coords) -> float:
    a = np.asarray(coords)
    p1, p2 = np.radians(a[:-1, 1]), np.radians(a[1:, 1])
    h = np.sin((p2 - p1) / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(np.radians(a[1:, 0] - a[:-1, 0]) / 2) ** 2
    return float(np.sum(2 * R_TERRA * np.arcsin(np.sqrt(h))))


def perimetro_km(geom) -> float:
    """Soma dos contornos (externos e internos) em km, por haversine."""
    total = 0.0
    for pol in (geom.geoms if hasattr(geom, "geoms") else [geom]):
        if not isinstance(pol, Polygon):
            continue
        for anel in [pol.exterior, *pol.interiors]:
            total += _comprimento_m(anel.coords)
    return total / 1000


def so_poligonos(g):
    """Mantém só os polígonos de uma geometria (make_valid pode devolver coleções com linhas/pontos)."""
    if isinstance(g, (Polygon, MultiPolygon)):
        return g
    partes = [p for p in getattr(g, "geoms", []) if isinstance(p, (Polygon, MultiPolygon))]
    flat = []
    for p in partes:
        flat += list(p.geoms) if isinstance(p, MultiPolygon) else [p]
    return MultiPolygon(flat) if flat else g


def verificar_geometria(geom) -> tuple[object, bool, str | None]:
    """(geometria usável, válida_na_origem, motivo). Inválida na origem é reparada para uso, mas continua contada como inválida."""
    if geom is None or geom.is_empty:
        return geom, False, "geometria vazia"
    if geom.is_valid:
        return geom, True, None
    return so_poligonos(make_valid(geom)), False, explain_validity(geom)[:200]


def para_wkb(geom, tolerancia=TOLERANCIA) -> bytes:
    g = geom.simplify(tolerancia, preserve_topology=True) if tolerancia else geom
    return wkb.dumps(g if not g.is_empty else geom)


# ---------------- fontes e importação ----------------
def obter_fonte(db, origem: str, versao: str, **campos) -> tuple[MalhaFonte, bool]:
    f = db.scalar(select(MalhaFonte).where(MalhaFonte.origem == origem, MalhaFonte.versao == versao))
    if f:
        return f, False
    f = MalhaFonte(origem=origem, versao=versao, coletado_em=campos.pop("coletado_em", datetime.now()), **campos)
    db.add(f)
    db.flush()
    return f, True


def inserir_municipios(db, fonte: MalhaFonte, itens: list[dict]) -> dict:
    """Grava as geometrias de uma importação (ainda NÃO ativas). `itens`: {cod, nome, uf, geom, area_atrib?}. Devolve o resumo da validação.
    Código inválido ou geometria inválida não impedem de guardar (fica o registro e o motivo), mas contam como inválidos."""
    n_ok = n_inv = 0
    cods = set()
    problemas: list[dict] = []
    dif_area = 0
    for it in itens:
        cod = str(it["cod"])
        ok_cod, motivo_cod = codigo_valido(cod, it.get("uf"))
        geom, ok_geo, motivo_geo = verificar_geometria(it["geom"])
        area = perim = None
        if geom is not None and not geom.is_empty:
            area, perim = area_km2(geom), perimetro_km(geom)
        if it.get("area_atrib") and area:
            if abs(area - it["area_atrib"]) / it["area_atrib"] > 0.02:
                dif_area += 1
                problemas.append({"cod": cod, "problema": f"área calculada {area:.1f} km² difere do atributo {it['area_atrib']:.1f} km²"})
        motivos = [m for m in ((None if ok_cod else motivo_cod), motivo_geo) if m]
        valida = ok_cod and ok_geo
        n_ok += valida
        n_inv += not valida
        if motivos:
            problemas.append({"cod": cod, "problema": "; ".join(motivos)})
        cods.add(cod)
        db.add(MalhaMunicipio(fonte_id=fonte.id, cod_ibge=cod, nome=it.get("nome"), uf=it.get("uf"), geom_wkb=para_wkb(geom) if geom is not None and not geom.is_empty else None,
                              tolerancia_graus=TOLERANCIA, area_km2=area, perimetro_km=perim, valida=valida, motivo="; ".join(motivos) or (motivo_cod if cod in ESPECIAIS or cod in EXCECOES_DIGITO else None)))
    db.flush()
    fonte.n_municipios, fonte.n_validos, fonte.n_invalidos = len(itens), n_ok, n_inv
    return {"codigos": len(cods), "validos": n_ok, "invalidos": n_inv, "diferenca_de_area_acima_de_2pct": dif_area, "problemas": problemas[:50]}


def codigos_esperados(db) -> set[str]:
    """Códigos que deveriam existir: a tabela `municipios` quando está completa (≥ 5.500 linhas); senão não há lista de referência (só a contagem oficial de 5.570)."""
    cods = set(db.scalars(select(Municipio.codigo_ibge)))
    return cods if len(cods) >= 5500 else set()


def avaliar_ibge(db, fonte: MalhaFonte, resumo: dict) -> str:
    """Decide se a importação do IBGE é `validada`: 5.570 municípios (fora as lagoas), nenhum código inválido, ≤ 0,5% de geometrias inválidas e ≤ 1% de áreas fora de 2% do atributo."""
    linhas = db.scalars(select(MalhaMunicipio).where(MalhaMunicipio.fonte_id == fonte.id)).all()
    municipios = [l for l in linhas if l.cod_ibge not in ESPECIAIS]
    cods = {l.cod_ibge for l in municipios}
    faltam = sorted(codigos_esperados(db) - cods)
    codigos_ruins = sum(1 for l in municipios if not codigo_valido(l.cod_ibge, l.uf)[0])    # decide pela validade do código, não pelo texto da observação
    geoms_ruins = sum(1 for l in municipios if not l.valida) - codigos_ruins
    ok = (len(municipios) == TOTAL_MUNICIPIOS and not faltam and codigos_ruins == 0 and geoms_ruins <= 0.005 * len(municipios) and resumo["diferenca_de_area_acima_de_2pct"] <= 0.01 * len(municipios))
    fonte.status = "validada" if ok else "reprovada"
    resumo.update({"municipios": len(municipios), "esperado": TOTAL_MUNICIPIOS, "faltando": faltam[:50], "codigos_invalidos": codigos_ruins, "geometrias_invalidas": geoms_ruins,
                   "corpos_dagua_na_malha": sorted(set(l.cod_ibge for l in linhas) & set(ESPECIAIS)), "aprovada": ok})
    fonte.verificacao = {**(fonte.verificacao or {}), "importacao": resumo}
    return fonte.status


# ---------------- ativação controlada ----------------
def ativar_fonte(db, fonte_id: int) -> dict:
    """Passa a usar as geometrias desta fonte (só se `validada`, ou `provisoria` para os municípios que ainda não têm nenhuma ativa). Tudo numa transação: ou troca tudo ou não troca nada.
    As geometrias antigas continuam guardadas, só deixam de estar ativas."""
    fonte = db.get(MalhaFonte, fonte_id)
    if fonte is None:
        raise ValueError("fonte inexistente")
    if fonte.status not in ("validada", "provisoria"):
        raise RuntimeError(f"fonte {fonte.origem} {fonte.versao} está {fonte.status}: só fonte validada (ou provisória, onde não há outra) pode ser ativada")
    novas = db.scalars(select(MalhaMunicipio).where(MalhaMunicipio.fonte_id == fonte.id, MalhaMunicipio.valida.is_(True), MalhaMunicipio.geom_wkb.isnot(None))).all()
    trocadas = ativadas = mantidas = 0
    try:
        with db.begin_nested():
            for m in novas:
                atual = db.scalar(select(MalhaMunicipio).where(MalhaMunicipio.cod_ibge == m.cod_ibge, MalhaMunicipio.ativa.is_(True)))
                if atual is not None and atual.id == m.id:
                    continue
                if atual is not None:
                    fa = db.get(MalhaFonte, atual.fonte_id)
                    if not fonte.oficial and fa.oficial:   # a provisória nunca derruba a oficial
                        mantidas += 1
                        continue
                    atual.ativa = False
                    db.flush()
                    trocadas += 1
                m.ativa = True
                db.flush()
                ativadas += 1
            # fontes cujas geometrias deixaram de estar ativas por inteiro viram `substituida` (continuam guardadas)
            for f in db.scalars(select(MalhaFonte).where(MalhaFonte.id != fonte.id, MalhaFonte.status.in_(("provisoria", "validada")))).all():
                if not db.scalar(select(MalhaMunicipio.id).where(MalhaMunicipio.fonte_id == f.id, MalhaMunicipio.ativa.is_(True)).limit(1)):
                    f.status = "substituida"
    except Exception:
        db.rollback()
        raise
    return {"fonte": f"{fonte.origem} {fonte.versao}", "ativadas": ativadas, "trocadas": trocadas, "mantidas_oficiais": mantidas}


def geometria_ativa(db, cod_ibge: str):
    """(geometria, origem, versao, oficial) da geometria ativa do município, ou None."""
    linha = db.execute(select(MalhaMunicipio, MalhaFonte).join(MalhaFonte, MalhaFonte.id == MalhaMunicipio.fonte_id)
                       .where(MalhaMunicipio.cod_ibge == str(cod_ibge), MalhaMunicipio.ativa.is_(True))).first()
    if not linha or not linha[0].geom_wkb:
        return None
    m, f = linha
    return wkb.loads(m.geom_wkb), f.origem, f.versao, f.oficial


def salvar_osm_provisorio(db, uf: str, cod_ibge: str, nome: str, geom, relacao: int | None = None, osm_base: str | None = None) -> MalhaMunicipio:
    """Guarda o limite do OSM (provisório) de um município e o ativa se ainda não há geometria oficial ativa. Uma importação OSM por dia (`osm-AAAA-MM-DD`)."""
    hoje = datetime.now().strftime("%Y-%m-%d")
    fonte, nova = obter_fonte(db, "osm", f"osm-{hoje}", oficial=False, escopo="municipios_pontuais", rotulo="OpenStreetMap (relação do município) — PROVISÓRIO", publicado_em=osm_base,
                              url="https://overpass-api.de (relação OSM)", status="provisoria")
    existe = db.scalar(select(MalhaMunicipio).where(MalhaMunicipio.fonte_id == fonte.id, MalhaMunicipio.cod_ibge == cod_ibge))
    if existe is not None:
        return existe
    resumo = inserir_municipios(db, fonte, [{"cod": cod_ibge, "nome": nome, "uf": uf, "geom": geom}])
    fonte.n_municipios = db.scalar(select(func.count()).select_from(MalhaMunicipio).where(MalhaMunicipio.fonte_id == fonte.id))
    fonte.verificacao = {**(fonte.verificacao or {}), "relacoes": {**((fonte.verificacao or {}).get("relacoes") or {}), cod_ibge: relacao}}
    ativar_fonte(db, fonte.id)
    return db.scalar(select(MalhaMunicipio).where(MalhaMunicipio.fonte_id == fonte.id, MalhaMunicipio.cod_ibge == cod_ibge))


# ---------------- verificação e comparação ----------------
def verificar_integridade(db, fonte_id: int, min_km2: float = 0.5) -> dict:
    """Sobre uma fonte: municípios ausentes, códigos e geometrias inválidos, SOBREPOSIÇÕES entre municípios vizinhos e LACUNAS (buracos na união dos municípios de cada UF). Áreas em km²;
    abaixo de `min_km2` é ruído da simplificação e não conta."""
    linhas = db.scalars(select(MalhaMunicipio).where(MalhaMunicipio.fonte_id == fonte_id, MalhaMunicipio.geom_wkb.isnot(None))).all()
    geoms = [wkb.loads(l.geom_wkb) for l in linhas]
    arvore = STRtree(geoms)
    sobrepostos = []
    for i, g in enumerate(geoms):
        for j in arvore.query(g, predicate="intersects"):
            if j <= i:
                continue
            inter = g.intersection(geoms[j])
            a = area_km2(inter) if not inter.is_empty and inter.area > 0 else 0.0
            if a >= min_km2:
                sobrepostos.append({"a": linhas[i].cod_ibge, "b": linhas[j].cod_ibge, "km2": round(a, 3)})
    lacunas = []
    por_uf: dict[str, list] = {}
    for l, g in zip(linhas, geoms):
        if l.uf and l.cod_ibge not in ESPECIAIS:
            por_uf.setdefault(l.uf, []).append(g)
    for uf, gs in por_uf.items():
        if len(gs) < 5:
            continue
        uniao = unary_union([g.buffer(1e-5) for g in gs])
        for pol in (uniao.geoms if hasattr(uniao, "geoms") else [uniao]):
            for anel in pol.interiors:
                buraco = Polygon(anel)
                a = area_km2(buraco)
                if a >= min_km2:
                    c = buraco.representative_point()
                    lacunas.append({"uf": uf, "km2": round(a, 3), "ponto": [round(c.x, 4), round(c.y, 4)]})
    fonte = db.get(MalhaFonte, fonte_id)
    invalidos = [{"cod": l.cod_ibge, "motivo": l.motivo} for l in linhas if not l.valida]
    return {"fonte": f"{fonte.origem} {fonte.versao}", "municipios": len(linhas), "ausentes": sorted(codigos_esperados(db) - {l.cod_ibge for l in linhas})[:100] if fonte.escopo == "municipios" else None,
            "invalidos": invalidos[:100], "n_invalidos": len(invalidos), "sobreposicoes": sorted(sobrepostos, key=lambda x: -x["km2"])[:50], "n_sobreposicoes": len(sobrepostos),
            "lacunas": sorted(lacunas, key=lambda x: -x["km2"])[:50], "n_lacunas": len(lacunas), "min_km2": min_km2}


def comparar_fontes(db, provisoria_id: int, oficial_id: int, tol_area_pct: float = 5.0) -> dict:
    """Compara, município a município, a geometria provisória (OSM) com a oficial (IBGE): diferença de área, de perímetro e sobreposição (IoU) — tudo em projeção de área igual.
    Só entra quem existe nas duas; quem só existe numa vira `so_na_provisoria`/`so_na_oficial` (esta última lista só quando a provisória tem escopo pontual)."""
    def carrega(fid):
        return {l.cod_ibge: l for l in db.scalars(select(MalhaMunicipio).where(MalhaMunicipio.fonte_id == fid, MalhaMunicipio.geom_wkb.isnot(None)))}
    prov, ofi = carrega(provisoria_id), carrega(oficial_id)
    fp, fo = db.get(MalhaFonte, provisoria_id), db.get(MalhaFonte, oficial_id)
    itens = []
    for cod in sorted(set(prov) & set(ofi)):
        gp, go = wkb.loads(prov[cod].geom_wkb), wkb.loads(ofi[cod].geom_wkb)
        pp, po = projetar(gp), projetar(go)
        inter, uni = pp.intersection(po).area, pp.union(po).area
        ap, ao = prov[cod].area_km2, ofi[cod].area_km2
        pe_p, pe_o = prov[cod].perimetro_km, ofi[cod].perimetro_km
        da, dp = (ap - ao) / ao * 100, (pe_p - pe_o) / pe_o * 100
        itens.append({"cod": cod, "nome": ofi[cod].nome, "area_osm_km2": round(ap, 2), "area_ibge_km2": round(ao, 2), "dif_area_pct": round(da, 2), "perimetro_osm_km": round(pe_p, 1), "perimetro_ibge_km": round(pe_o, 1),
                      "dif_perimetro_pct": round(dp, 2), "iou": round(inter / uni, 4) if uni else None, "fora_da_tolerancia": abs(da) > tol_area_pct})
    return {"provisoria": f"{fp.origem} {fp.versao}", "oficial": f"{fo.origem} {fo.versao}", "comparados": len(itens), "fora_da_tolerancia": sum(i["fora_da_tolerancia"] for i in itens), "tolerancia_area_pct": tol_area_pct,
            "so_na_provisoria": sorted(set(prov) - set(ofi)), "so_na_oficial": len(set(ofi) - set(prov)) if fp.escopo == "municipios" else None, "itens": itens}
