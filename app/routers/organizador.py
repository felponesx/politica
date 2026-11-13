"""POST /organizar: transforma links colados em propostas de cadastro (Gemini + regra local). Exige o token de administrador."""
from fastapi import APIRouter, Header, Request
from pydantic import BaseModel, Field

from app import organizador
from app.routers.fontes_cadastro import _exige_admin

router = APIRouter(tags=["Organizador"])


class TextoIn(BaseModel):
    texto: str = Field(max_length=8000)


@router.post("/organizar")
def organizar(corpo: TextoIn, request: Request, x_admin_token: str = Header(default="")):
    _exige_admin(request, x_admin_token)
    return organizador.organizar(corpo.texto)
