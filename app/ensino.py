"""Ensino: IDEB do Brasil e dos estados, IGC das instituições de ensino superior e IDEB das escolas (INEP).

Os números vêm dos registros coletados (`ensino-ideb`, `ensino-igc`, `ensino-escolas`); onde falta coleta, a chave fica vazia e a tela avisa."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Registro

TIPOS = {"ideb": "ensino_ideb", "superior": "ensino_igc", "escolas": "ensino_escolas"}


def _ultimo(db: Session, tipo: str) -> dict | None:
    r = db.scalars(select(Registro).where(Registro.tipo == tipo).order_by(Registro.id.desc()).limit(1)).first()
    return r.dados if r else None


def montar(db: Session) -> dict:
    out = {k: _ultimo(db, t) for k, t in TIPOS.items()}
    out["fontes"] = ["INEP — Índice de Desenvolvimento da Educação Básica (IDEB)", "INEP — Índice Geral de Cursos (IGC)"]
    return out
