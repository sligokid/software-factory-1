"""FastAPI application that mounts every enabled slice."""

from fastapi import FastAPI

from app.registry import SLICE_ROUTERS


def create_app() -> FastAPI:
    application = FastAPI(title="software-factory")

    @application.get("/healthz", tags=["ops"])
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    for router in SLICE_ROUTERS:
        application.include_router(router)
    return application


app = create_app()
