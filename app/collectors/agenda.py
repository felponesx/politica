"""O que está acontecendo hoje no Congresso: sessões, reuniões de comissão e audiências.
- Câmara: /eventos (situação "Em Andamento", "Convocada", "Encerrada"...) e /eventos/{id}/pauta
- Senado: /plenario/agenda/dia/{AAAAMMDD}
Roda a cada 15 minutos em horário de expediente (agendador).
"""
from datetime import date

from app import http
from app.collectors import camara, senado
from app.collectors.base import registrar_coleta
from app.models import Registro
from app.utils import achar_lista, cavar, pegar, upsert


def coletar_agenda(dia: date | None = None, com_pauta: bool = True):
    dia = dia or date.today()
    with registrar_coleta("congresso", "agenda", dia=dia) as (db, n):
        for e in camara.paginar("/eventos", {"dataInicio": dia.isoformat(), "dataFim": dia.isoformat(), "itens": 100}):
            pauta = []
            if com_pauta and "deliber" in str(e.get("descricaoTipo", "")).lower():
                try:
                    pauta = [{"titulo": pegar(p, "titulo", "proposicao_", "descricao") if not isinstance(pegar(p, "titulo"), dict) else None,
                              "proposicao": cavar(p, "proposicao_", "ementa") or pegar(p, "titulo"),
                              "situacao": pegar(p, "situacaoItem"), "relator": cavar(p, "relator", "nome")}
                             for p in (http.get_json(f"{camara.BASE}/eventos/{e['id']}/pauta") or {}).get("dados", [])][:40]
                except Exception:
                    pauta = []
            orgaos = ", ".join(o.get("sigla") or o.get("nome") or "" for o in e.get("orgaos") or [])
            upsert(db, Registro, {"fonte": "camara", "tipo": "evento", "chave": str(e["id"])}, {
                "ano": dia.year, "titulo": e.get("descricao") or e.get("descricaoTipo"),
                "dados": {"dia": dia.isoformat(), "inicio": e.get("dataHoraInicio"), "fim": e.get("dataHoraFim"),
                          "situacao": e.get("situacao"), "tipo": e.get("descricaoTipo"), "orgaos": orgaos,
                          "local": cavar(e, "localCamara", "nome"), "casa": "camara", "pauta": pauta,
                          "video": e.get("urlRegistro")}})
            n += 1
        try:
            dados = senado.get(f"/plenario/agenda/dia/{dia:%Y%m%d}")
            for s in achar_lista(dados, ("CodigoSessao", "codigoSessao")):
                itens = achar_lista(s, ("NomeMateria", "DescricaoIdentificacaoMateria", "IdentificacaoMateria"))
                upsert(db, Registro, {"fonte": "senado", "tipo": "evento", "chave": str(pegar(s, "CodigoSessao"))}, {
                    "ano": dia.year, "titulo": pegar(s, "TipoSessao", "DescricaoTipoSessao", "NomeSessao") or "Sessão do Senado",
                    "dados": {"dia": dia.isoformat(), "inicio": f"{dia.isoformat()}T{pegar(s, 'HoraInicioSessao', 'Hora') or '00:00'}",
                              "situacao": pegar(s, "SituacaoSessao", "DescricaoSituacao"), "tipo": "Sessão plenária",
                              "orgaos": "Plenário do Senado", "casa": "senado",
                              "pauta": [{"proposicao": pegar(i, "DescricaoIdentificacaoMateria", "NomeMateria"),
                                         "titulo": pegar(i, "Ementa", "EmentaMateria")} for i in itens][:40]}})
                n += 1
        except Exception:
            pass  # agenda do Senado indisponível não impede a da Câmara
    return n.itens
