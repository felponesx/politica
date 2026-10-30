"""CPIs e CPMIs da Câmara dos Deputados e do Senado Federal.

Câmara: `/orgaos?sigla=CPI` e `?sigla=CPMI` (id, nome, apelido) e `/orgaos/{id}` (dataInicio, dataInstalacao, dataFim, situacao, urlWebsite). O número de membros vem de `/orgaos/{id}/membros`.
Senado: `/dadosabertos/comissao/lista/cpi` (XML; só as em atividade). Guarda uma lista por casa (`cpis_casa`)."""
import xml.etree.ElementTree as ET

from app import http
from app.collectors.base import registrar_coleta
from app.collectors.camara import BASE, paginar
from app.models import Registro
from app.utils import upsert

SENADO = "https://legis.senado.leg.br/dadosabertos/comissao/lista/cpi"
MINIMO_CAMARA = 5


def _dia(v) -> str | None:
    return str(v)[:10] if v else None


def cpis_camara() -> list[dict]:
    vistos: dict[int, dict] = {}
    for sigla in ("CPI", "CPMI"):
        for o in paginar("/orgaos", {"sigla": sigla, "itens": 100}):
            vistos[o["id"]] = o
    saida = []
    for i, o in sorted(vistos.items()):
        d = (http.get_json(f"{BASE}/orgaos/{i}") or {}).get("dados") or {}
        saida.append({"id": i, "casa": "camara", "sigla": o.get("sigla"), "nome": o.get("apelido") or o.get("nome"), "nome_completo": o.get("nome"),
                      "inicio": _dia(d.get("dataInicio")), "instalacao": _dia(d.get("dataInstalacao")), "fim": _dia(d.get("dataFim")),
                      "situacao": d.get("situacao"), "site": d.get("urlWebsite") or None})
    return saida


def ler_xml_senado(texto: str) -> list[dict]:
    """Lista as comissões do XML do Senado sem depender do nome exato das tags (procura as que terminam em Codigo/Sigla/Nome...)."""
    raiz = ET.fromstring(texto)
    saida = []
    for el in raiz.iter():
        filhos = {f.tag.split("}")[-1].lower(): (f.text or "").strip() for f in el if len(f) == 0}
        cod = next((v for k, v in filhos.items() if k.startswith("codigo")), "")
        nome = next((v for k, v in filhos.items() if k.startswith("nome")), "")
        if cod and nome:
            saida.append({"id": cod, "casa": "senado", "sigla": next((v for k, v in filhos.items() if k.startswith("sigla")), None), "nome": nome,
                          "inicio": _dia(next((v for k, v in filhos.items() if k.startswith("datainicio")), None)),
                          "fim": _dia(next((v for k, v in filhos.items() if k.startswith("datafim")), None)), "situacao": "em atividade"})
    return saida


def coletar_cpis():
    with registrar_coleta("congresso", "cpis") as (db, n):
        camara = cpis_camara()
        if len(camara) < MINIMO_CAMARA:
            raise RuntimeError(f"vieram {len(camara)} CPIs da Câmara (esperado ao menos {MINIMO_CAMARA}); nada foi gravado")
        try:
            r = http.get(SENADO, headers={"Accept": "application/xml"})
            senado = ler_xml_senado(r.text)
        except Exception as e:  # noqa: BLE001 - a Câmara basta para publicar; o Senado vira aviso
            senado = []
            n.avisos.append(f"Senado: {type(e).__name__}: {str(e)[:120]}")
        for casa, itens in (("camara", camara), ("senado", senado)):
            upsert(db, Registro, {"fonte": "congresso", "tipo": "cpis_casa", "chave": casa}, {"titulo": f"CPIs {casa}", "valor": float(len(itens)), "dados": {"itens": itens}})
        db.commit()
        n += len(camara) + len(senado)
    return n.itens
