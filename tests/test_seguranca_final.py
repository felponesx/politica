"""Revisão de segurança (nov/2026): painel com política de segurança, XML malicioso recusado, nada de segredo versionado."""
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app

RAIZ = Path(__file__).resolve().parents[1]


def test_painel_tem_politica_de_seguranca_e_nao_abre_em_moldura():
    r = TestClient(app).get("/painel")
    csp = r.headers["content-security-policy"]
    assert "default-src 'none'" in csp and "frame-ancestors 'none'" in csp and "connect-src 'self'" in csp
    assert "http" not in csp.replace("'self'", "")   # nenhum endereço de fora liberado
    assert r.headers["x-frame-options"] == "DENY" and r.headers["x-content-type-options"] == "nosniff"


def test_xml_com_entidade_externa_e_recusado_nos_coletores():
    from defusedxml.common import DefusedXmlException

    from app.collectors import coletor_externo
    malicioso = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]><lista><item id="&e;"/></lista>'
    with pytest.raises(DefusedXmlException):
        coletor_externo._linhas_xml(malicioso, None)


def test_nenhum_segredo_nem_arquivo_de_ambiente_versionado():
    rastreados = subprocess.run(["git", "ls-files"], cwd=RAIZ, capture_output=True, text=True).stdout.split("\n")
    proibidos = [f for f in rastreados if f and (f.endswith((".env", ".pem", ".key")) or f.endswith("config.env") or f.endswith("destinos.toml"))]
    assert not proibidos, proibidos
