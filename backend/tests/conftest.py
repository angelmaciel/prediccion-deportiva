"""Fixtures compartidas. Los tests corren sobre SQLite en memoria, aislados."""

from __future__ import annotations

import os
import shutil
import tempfile
from datetime import datetime, timedelta, timezone

# Directorio de artefactos aislado: si los tests usaran el real, un modelo
# entrenado a mano desde la CLI cambiaria el resultado de la suite.
DIRECTORIO_ARTEFACTOS_TEST = os.path.join(tempfile.gettempdir(), "pd_artefactos_test")

# Las variables se fijan ANTES de importar la app: la config se cachea al importar.
os.environ.setdefault("ENTORNO", "test")
os.environ.setdefault("DIRECTORIO_ARTEFACTOS", DIRECTORIO_ARTEFACTOS_TEST)
os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "clave-de-test-suficientemente-larga-1234567890")
# base64 de b"clave-de-test-aes-256-32-bytes!!" (32 bytes exactos, requisito de AES-256)
os.environ.setdefault("CLAVE_CIFRADO_DATOS", "Y2xhdmUtZGUtdGVzdC1hZXMtMjU2LTMyLWJ5dGVzISE=")
os.environ.setdefault("CLAVE_INDICE_CIEGO", "clave-indice-ciego-de-test")
os.environ.setdefault("SCHEDULER_ACTIVO", "false")
os.environ.setdefault("ORIGENES_PERMITIDOS", "http://localhost:5173")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.core.crypto import indice_ciego, normalizar_email  # noqa: E402
from app.core.limites import limiter  # noqa: E402
from app.core.seguridad import hashear_password  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import obtener_db  # noqa: E402
from app.main import app  # noqa: E402
from app.modelos import (  # noqa: E402
    Equipo,
    EstadoPartido,
    Fuente,
    Partido,
    Rol,
    Usuario,
)
from app.servicios.ingesta.sincronizacion import calcular_resultado  # noqa: E402

PASSWORD_VALIDA = "ContrasenaSegura123"


@pytest.fixture(autouse=True)
def artefactos_limpios():
    """Cada test arranca sin modelo entrenado, salvo que lo entrene el mismo."""
    shutil.rmtree(DIRECTORIO_ARTEFACTOS_TEST, ignore_errors=True)
    os.makedirs(DIRECTORIO_ARTEFACTOS_TEST, exist_ok=True)
    yield DIRECTORIO_ARTEFACTOS_TEST
    shutil.rmtree(DIRECTORIO_ARTEFACTOS_TEST, ignore_errors=True)


@pytest.fixture(scope="session")
def engine_test():
    # StaticPool mantiene viva la misma conexion: sin esto cada sesion veria una
    # base :memory: distinta y vacia.
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    engine.dispose()


@pytest.fixture
def db(engine_test) -> Session:
    """Sesion limpia por test: se borran todas las filas al terminar."""
    fabrica = sessionmaker(bind=engine_test, autoflush=False, autocommit=False, future=True)
    sesion = fabrica()
    try:
        yield sesion
    finally:
        sesion.rollback()
        for tabla in reversed(Base.metadata.sorted_tables):
            sesion.execute(tabla.delete())
        sesion.commit()
        sesion.close()


@pytest.fixture
def cliente(db) -> TestClient:
    """TestClient con la base de test inyectada y el rate limiting apagado.

    El limitador se desactiva salvo en los tests que lo prueban a proposito;
    si no, un test gastaria la cuota del siguiente.
    """
    app.dependency_overrides[obtener_db] = lambda: db
    limiter.enabled = False
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    limiter.enabled = True


@pytest.fixture
def limiter_activo():
    """Habilita el rate limiting con las cubetas vacias."""
    limiter.enabled = True
    limiter.reset()
    yield limiter
    limiter.reset()
    limiter.enabled = False


# --- Datos ---


def crear_usuario(
    db: Session, email: str, password: str = PASSWORD_VALIDA, rol: Rol = Rol.USUARIO
) -> Usuario:
    email = normalizar_email(email)
    usuario = Usuario(
        email=email,
        email_indice=indice_ciego(email),
        password_hash=hashear_password(password),
        rol=rol,
    )
    db.add(usuario)
    db.commit()
    db.refresh(usuario)
    return usuario


@pytest.fixture
def usuario_normal(db) -> Usuario:
    return crear_usuario(db, "usuario@ejemplo.py")


@pytest.fixture
def usuario_admin(db) -> Usuario:
    return crear_usuario(db, "admin@ejemplo.py", rol=Rol.ADMIN)


def iniciar_sesion(cliente: TestClient, email: str, password: str = PASSWORD_VALIDA):
    return cliente.post("/auth/login", json={"email": email, "password": password})


@pytest.fixture
def cliente_admin(cliente, usuario_admin) -> TestClient:
    respuesta = iniciar_sesion(cliente, "admin@ejemplo.py")
    assert respuesta.status_code == 200, respuesta.text
    return cliente


@pytest.fixture
def cliente_usuario(cliente, usuario_normal) -> TestClient:
    respuesta = iniciar_sesion(cliente, "usuario@ejemplo.py")
    assert respuesta.status_code == 200, respuesta.text
    return cliente


# Diez equipos: hacen falta para que una liga simulada genere las 200+ fechas
# que el pipeline exige para entrenar.
NOMBRES_EQUIPOS = [
    "Olimpia",
    "Cerro Porteno",
    "Libertad",
    "Guarani",
    "Nacional",
    "Sportivo Luqueno",
    "Sol de America",
    "General Diaz",
    "Tacuary",
    "Resistencia",
]


@pytest.fixture
def equipos(db) -> list[Equipo]:
    creados = []
    for i, nombre in enumerate(NOMBRES_EQUIPOS, start=1):
        equipo = Equipo(
            nombre=nombre,
            liga="Primera Division de Paraguay",
            pais="Paraguay",
            fuente=Fuente.API_FOOTBALL,
            external_id=f"test-{i}",
        )
        db.add(equipo)
        creados.append(equipo)
    db.commit()
    for e in creados:
        db.refresh(e)
    return creados


def crear_partido(
    db: Session,
    local: Equipo,
    visitante: Equipo,
    fecha: datetime,
    goles_local: int | None = None,
    goles_visitante: int | None = None,
    jornada: int = 1,
    externo: str | None = None,
) -> Partido:
    finalizado = goles_local is not None and goles_visitante is not None
    partido = Partido(
        equipo_local_id=local.id,
        equipo_visitante_id=visitante.id,
        fecha=fecha,
        liga=local.liga,
        temporada="2026",
        jornada=jornada,
        estado=EstadoPartido.FINALIZADO if finalizado else EstadoPartido.PROGRAMADO,
        goles_local=goles_local,
        goles_visitante=goles_visitante,
        resultado_real=calcular_resultado(goles_local, goles_visitante) if finalizado else None,
        fuente=Fuente.API_FOOTBALL,
        external_id=externo or f"p-{fecha.isoformat()}-{local.id}-{visitante.id}",
    )
    db.add(partido)
    db.commit()
    db.refresh(partido)
    return partido


@pytest.fixture
def partido_futuro(db, equipos) -> Partido:
    return crear_partido(
        db, equipos[0], equipos[1], datetime.now(timezone.utc) + timedelta(days=2)
    )
