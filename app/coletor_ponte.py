"""Ponte entre a API e o coletor (coletor/coletor.py, o mesmo que o programa roda a cada 5 minutos): lê o estado de cada fonte, a
verificação e a correção de formato, e aplica as decisões da pessoa (aprovar, rejeitar, desfazer correção).

O coletor guarda tudo no SQLite dele (COLETOR_RAIZ/dados/manifesto.db). Aqui só se abre esse banco por um instante. Não coleta nada."""
from __future__ import annotations

import sys
from pathlib import Path


class ColetorIndisponivel(RuntimeError):
    pass


def modulo():
    """O módulo `coletor` (arquivo coletor/coletor.py): no programa instalado já está no pacote; pelo código, a pasta coletor/ entra no
    caminho. Cuidado: a pasta coletor/ do projeto também pode ser importada como pacote vazio, e isso não serve."""
    import importlib
    coletor = sys.modules.get("coletor")
    if coletor is None or not hasattr(coletor, "abrir_db"):
        pasta = Path(__file__).resolve().parent.parent / "coletor"
        if str(pasta) not in sys.path and (pasta / "coletor.py").exists():
            sys.path.insert(0, str(pasta))
        sys.modules.pop("coletor", None)
        try:
            coletor = importlib.import_module("coletor")
        except ImportError:
            raise ColetorIndisponivel("o coletor não está neste programa")
        if not hasattr(coletor, "abrir_db"):
            raise ColetorIndisponivel("o coletor não está neste programa")
    if not getattr(coletor, "_cadastro_direto", False):
        coletor._do_cadastro = _cadastro_direto       # lê as fontes cadastradas direto do banco do BRASIL+ (sem chamar a própria API)
        coletor._cadastro_direto = True
    return coletor


def _cadastro_direto() -> list:
    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models import FonteCadastrada
    with SessionLocal() as db:
        return [{"nome": f.nome, "produto": f.produto, "url": f.url, "intervalo_min": f.intervalo_min, "formato": f.formato,
                 "campos": {k: v for k, v in (f.campos or {}).items() if k != "categoria"}}
                for f in db.scalars(select(FonteCadastrada).where(FonteCadastrada.ativa.is_(True)))]


def status() -> dict:
    c = modulo()
    db = c.abrir_db()
    try:
        return c.status_fontes(db)
    finally:
        db.close()


def decidir(fonte: str, acao: str) -> str:
    """acao: "aprovar" ou "rejeitar" o dado retido da fonte."""
    if acao not in ("aprovar", "rejeitar"):
        raise ValueError("ação inválida")
    return _aplicar(lambda c, db: c.decidir(db, fonte, acao))


def desfazer(fonte: str) -> str:
    return _aplicar(lambda c, db: c.desfazer(db, fonte))


def _aplicar(fn) -> str:
    c = modulo()
    db = c.abrir_db()
    try:
        fn(c, db)
        return "ok"
    except SystemExit as e:           # o coletor avisa "nada para decidir" saindo; aqui vira mensagem
        raise ValueError(str(e.code or "nada a fazer"))
    finally:
        db.close()
