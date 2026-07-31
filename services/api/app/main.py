from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .db import connect_mongo, close_mongo, ensure_indexes
from .db.supabase_client import init_supabase, close_supabase
from .queue import connect_queue, close_queue
from .auth import router as auth_router
from .uploads import router as uploads_router
from .analysis import router as analysis_router
from .models.router import router as models_router
from .reviews import router as reviews_router
from .abyss import router as abyss_router
from .reports import router as reports_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    try:
        await connect_mongo()
        print(f"[startup] MongoDB connected: {settings.mongodb_db}")
        from .db import get_db
        await ensure_indexes(get_db())
        print("[startup] MongoDB indexes ensured")
    except Exception as exc:
        print(f"[startup] MongoDB connection failed: {exc} — continuing without DB")

    try:
        await init_supabase()
        if settings.supabase_url:
            print("[startup] Supabase client initialized")
    except Exception as exc:
        print(f"[startup] Supabase init failed: {exc} — continuing without Supabase")

    try:
        await connect_queue()
        print("[startup] Redis queue connected")
    except Exception as exc:
        print(f"[startup] Redis queue unavailable: {exc} — jobs will queue in MongoDB only")

    yield

    await close_queue()
    await close_supabase()
    await close_mongo()
    print("[shutdown] connections closed")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Core routes
    @app.get("/health", tags=["meta"])
    async def health():
        return {"status": "ok", "version": settings.app_version}

    @app.get("/version", tags=["meta"])
    async def version():
        return {"version": settings.app_version, "name": settings.app_name}

    # Feature routers
    app.include_router(auth_router)
    app.include_router(uploads_router)
    app.include_router(analysis_router)
    app.include_router(models_router)
    app.include_router(reviews_router)
    app.include_router(abyss_router)
    app.include_router(reports_router)

    return app


app = create_app()
