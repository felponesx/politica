import logging
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.db import criar_tabelas
from app.seguranca import LimiteCorpo, Protecao
from app.routers import dados, eleicoes, legislacao, legislativo, ligacoes, normalizados, seguranca, v02, v03, ensino as ensino_rotas, lacunas as lacunas_rotas, sancoes as sancoes_rotas, saude as saude_rotas

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

@asynccontextmanager
async def lifespan(_app):
    if settings.migrar_ao_iniciar:
        criar_tabelas()
    yield


app = FastAPI(title="BRASIL+ API", description="Transparência em um só lugar", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"], allow_headers=["*"])
app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=5)  # respostas grandes (listas, cópias) viajam bem menores
app.add_middleware(Protecao)
app.add_middleware(LimiteCorpo)  # o mais externo: barra corpo grande antes de qualquer outra coisa


@app.exception_handler(Exception)
async def erro_inesperado(request, exc):
    """Erro não previsto: vai para o log com o caminho, e quem chamou recebe só uma mensagem simples (nada de pilha de erro ou SQL)."""
    logging.getLogger("brasilplus.api").exception("erro em %s %s", request.method, request.url.path)
    return JSONResponse({"detail": "Erro interno. Tente de novo em instantes."}, status_code=500)


@app.get("/saude", tags=["Sistema"])
def saude():
    """Vivo? Não consulta nada (é o que o Docker chama a cada 30 s)."""
    return {"status": "ok"}


@app.get("/pronto", tags=["Sistema"])
def pronto():
    """Pronto para atender? Confere o banco e se as migrações estão em dia. Só diz ok ou não (sem detalhes internos); o motivo vai para o log."""
    from pathlib import Path

    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from sqlalchemy import text

    from app.db import engine
    try:
        raiz = Path(__file__).resolve().parent.parent
        cfg = Config(str(raiz / "alembic.ini"))
        cfg.set_main_option("script_location", str(raiz / "migrations"))
        esperado = ScriptDirectory.from_config(cfg).get_current_head()
        with engine.connect() as c:
            atual = c.execute(text("SELECT version_num FROM alembic_version")).scalar()
        if atual != esperado:
            logging.getLogger("brasilplus.api").error("migrações atrasadas: banco em %s, código em %s", atual, esperado)
            return JSONResponse({"status": "indisponivel"}, status_code=503)
    except Exception as e:
        logging.getLogger("brasilplus.api").error("banco indisponível: %s", type(e).__name__)
        return JSONResponse({"status": "indisponivel"}, status_code=503)
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
app.include_router(saude_rotas.router)
app.include_router(ensino_rotas.router)
app.include_router(lacunas_rotas.router)
app.include_router(sancoes_rotas.router)


# Site (frontend) servido pelo próprio backend: abra http://localhost:8000 e as telas já usam a API.
SITE = Path(__file__).resolve().parent.parent / "site" / "index.html"
# fotos e logos gerados pelo robô (scripts/midia_site.py); o site busca em midia/
app.mount("/midia", StaticFiles(directory=SITE.parent / "midia", check_dir=False), name="midia")


@app.get("/", include_in_schema=False)
def site():
    if SITE.exists():
        return FileResponse(SITE, media_type="text/html; charset=utf-8", headers={"Cache-Control": "no-cache"})
    return {"status": "ok", "docs": "/docs", "aviso": "Coloque o site em site/index.html para servi-lo aqui."}
