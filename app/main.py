import logging
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.config import settings
from app.db import criar_tabelas
from app.seguranca import Protecao
from app.routers import dados, eleicoes, legislacao, legislativo, ligacoes, normalizados, seguranca, v02, v03

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

@asynccontextmanager
async def lifespan(_app):
    if settings.migrar_ao_iniciar:
        criar_tabelas()
    yield


app = FastAPI(title="BRASIL+ API", description="Transparência em um só lugar", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"], allow_headers=["*"])
app.add_middleware(Protecao)


@app.get("/saude", tags=["Sistema"])
def saude():
    return {"status": "ok"}


app.include_router(legislativo.router)
app.include_router(dados.router)
app.include_router(legislacao.router)
app.include_router(eleicoes.router)
app.include_router(normalizados.router)
app.include_router(ligacoes.router)
app.include_router(v02.router)
app.include_router(v03.router)
app.include_router(seguranca.router)


# Site (frontend) servido pelo próprio backend: abra http://localhost:8000 e as telas já usam a API.
SITE = Path(__file__).resolve().parent.parent / "site" / "index.html"


@app.get("/", include_in_schema=False)
def site():
    if SITE.exists():
        return FileResponse(SITE, media_type="text/html; charset=utf-8", headers={"Cache-Control": "no-cache"})
    return {"status": "ok", "docs": "/docs", "aviso": "Coloque o site em site/index.html para servi-lo aqui."}
