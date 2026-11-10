"""Limpeza de 10/11/2026: pacotes da cópia estática, resumo da tela inicial e contratos com data no futuro."""
from datetime import date, timedelta

from fastapi.testclient import TestClient

from app.db import SessionLocal, criar_tabelas
from app.main import app
from app.models import Contrato, Registro
from scripts.pacotes_copia import acrescentar_resumos, montar_pacotes


def test_contrato_com_data_no_futuro_vai_para_o_fim():
    criar_tabelas()
    hoje = date.today()
    with SessionLocal() as db:
        regs = [Registro(fonte="teste", tipo="contrato", chave=f"limpeza-{i}") for i in range(2)]
        db.add_all(regs)
        db.flush()
        novos = [Contrato(registro_id=regs[0].id, fonte="pncp", numero_controle="t-futuro", data_assinatura=hoje + timedelta(days=400), valor=1, orgao="X"),
                 Contrato(registro_id=regs[1].id, fonte="pncp", numero_controle="t-hoje", data_assinatura=hoje, valor=1, orgao="Y")]
        db.add_all(novos)
        db.commit()
        ids = [c.id for c in novos]
        rids = [r.id for r in regs]
    try:
        itens = TestClient(app).get("/contratos?ordenar=data&limit=500").json()["itens"]
        pos = {x["id"]: i for i, x in enumerate(itens)}
        assert pos[ids[1]] < pos[ids[0]]
    finally:
        with SessionLocal() as db:
            db.query(Contrato).filter(Contrato.id.in_(ids)).delete(synchronize_session=False)
            db.query(Registro).filter(Registro.id.in_(rids)).delete(synchronize_session=False)
            db.commit()


def test_resumo_da_inicial_e_pacotes():
    futuro = (date.today() + timedelta(days=300)).isoformat()
    dados = {
        "/proposicoes": {"total": 3, "itens": [{"sigla_tipo": "PL", "data_apresentacao": "2026-01-02"}, {"sigla_tipo": "PL", "data_apresentacao": "2026-03-01"},
                                               {"sigla_tipo": "PEC", "data_apresentacao": "2025-12-01"}]},
        "/contratos?ordenar=data": {"total": 2, "itens": [{"id": 1, "data_assinatura": futuro}, {"id": 2, "data_assinatura": "2026-10-01"}]},
        "/contadores": {"a": 1}, "/estados/SP/fluxo": {"x": 1}, "/orgaos?ano=2020": {"y": 1}, "/policias/pm-SP": {"z": 1},
        "/malhas/SP": {"m": 1}, "/eleicoes/2026/SP/mapa?cargo=PRESIDENTE&turno=1": {"e": 1}, "/escandalos": {"c": 1},
    }
    acrescentar_resumos(dados)
    r = dados["/inicio/proposicoes"]
    assert r["total"] == 3 and r["por_tipo"] == {"PL": 2, "PEC": 1} and r["data_min"] == "2025-12-01" and r["data_max"] == "2026-03-01"
    assert [x["id"] for x in dados["/contratos?limit=1&ordenar=data"]["itens"]] == [2]  # a data no futuro não é a "última"
    pac = montar_pacotes(dados, ["/escandalos", "/policias/pm-SP"])
    assert "/contadores" in pac["p/inicio.json"]["valores"] and "/estados/SP/fluxo" in pac["p/inicio.json"]["valores"]
    assert pac["p/eleicoes.json"]["telas"] == ["eleicoes"] and "/malhas/SP" in pac["p/eleicoes.json"]["valores"]
    assert "/orgaos?ano=2020" in pac["p/governo.json"]["valores"] and "/escandalos" in pac["p/escandalos.json"]["valores"]
    todas = {k for p in pac.values() for k in p["valores"]}
    assert "/policias/pm-SP" not in todas  # ficha de uma polícia fica só na parte
    assert sum(len(p["valores"]) for p in pac.values()) == len(todas)  # cada chave em um pacote só
