"""Engine y sesiones de base de datos."""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import obtener_config

config = obtener_config()

_opciones: dict = {"pool_pre_ping": True, "future": True}
if config.database_url.startswith("postgresql"):
    # Render free duerme las conexiones; reciclar antes evita "server closed connection".
    _opciones.update(pool_size=5, max_overflow=5, pool_recycle=280)

engine = create_engine(config.database_url, **_opciones)
FabricaSesion = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def obtener_db() -> Iterator[Session]:
    """Dependencia de FastAPI: una sesion por request, siempre cerrada."""
    db = FabricaSesion()
    try:
        yield db
    finally:
        db.close()
