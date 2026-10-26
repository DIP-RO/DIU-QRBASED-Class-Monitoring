from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from backend.api import router as api_router
from backend.auth import router as auth_router
from backend.config import get_settings
from backend.database import engine
from backend.models import Base

settings=get_settings(); app=FastAPI(title="DIU QR Class Monitoring API",version="1.0.0",docs_url="/api/docs",openapi_url="/api/openapi.json")
app.add_middleware(SessionMiddleware,secret_key=settings.session_secret,https_only=settings.cookie_secure,same_site="lax",max_age=8*60*60)
class OriginCSRFMiddleware(BaseHTTPMiddleware):
    async def dispatch(self,request,call_next):
        if request.method in {"POST","PUT","PATCH","DELETE"} and settings.environment=="production":
            origin=request.headers.get("origin")
            if origin and origin.rstrip("/")!=settings.public_base_url.rstrip("/"):
                from starlette.responses import JSONResponse
                return JSONResponse({"detail":"CSRF origin rejected"},status_code=403)
        return await call_next(request)
app.add_middleware(OriginCSRFMiddleware)
app.include_router(auth_router); app.include_router(api_router)
@app.on_event("startup")
def startup(): Base.metadata.create_all(engine)
@app.get("/health/live")
def live(): return {"status":"ok"}
@app.get("/health/ready")
def ready():
    try:
        with engine.connect() as c: c.exec_driver_sql("SELECT 1")
        return {"status":"ready","database":"ok"}
    except Exception as exc: raise HTTPException(503,"database unavailable") from exc

dist=Path("frontend/dist")
if dist.exists():
    app.mount("/assets",StaticFiles(directory=dist/"assets"),name="assets")
    @app.get("/{path:path}",include_in_schema=False)
    def spa(path:str):
        target=dist/path
        return FileResponse(target if target.is_file() else dist/"index.html")
