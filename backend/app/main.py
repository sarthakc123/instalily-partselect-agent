"""FastAPI entry point. Wires routes, CORS, and a lifespan that pre-warms
the KG (so the first /chat request doesn't pay the build cost)."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import chat as chat_api
from app.api import conversations as conv_api
from app.api import health as health_api
from app.config import settings
from app.db.pool import apply_schema, close_pool
from app.agents.graph import get_kg


def _configure_logging() -> None:
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(message)s",
    )
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ]
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    _configure_logging()
    log = structlog.get_logger("startup")
    apply_schema()  # idempotent; safe on every boot
    kg = get_kg()
    log.info("kg_ready", **kg.stats())
    log.info("server_ready", cors_origins=settings.cors_origin_list)
    yield
    close_pool()


def create_app() -> FastAPI:
    app = FastAPI(title="PartSelect Chat Agent", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Conversation-Id"],
    )
    app.include_router(health_api.router)
    app.include_router(chat_api.router)
    app.include_router(conv_api.router)
    return app


app = create_app()
