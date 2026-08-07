"""CLI de administracion: bootstrap, jobs manuales y datos de demostracion.

Uso:
    python manage.py crear-admin
    python manage.py sincronizar
    python manage.py entrenar [--algoritmo random_forest]
    python manage.py predecir
    python manage.py metricas
    python manage.py demo            # datos simulados para probar sin API keys
"""

from __future__ import annotations

import argparse
import getpass
import logging
import random
import sys
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.config import obtener_config
from app.core.crypto import indice_ciego, normalizar_email
from app.core.seguridad import hashear_password, validar_fortaleza_password
from app.db.base import Base
from app.db.session import FabricaSesion, engine
from app.ml.elo import actualizar_elo
from app.modelos import (  # noqa: F401  (registra las tablas)
    Equipo,
    EstadoPartido,
    Fuente,
    Partido,
    Resultado,
    Rol,
    Usuario,
)
from app.servicios.entrenamiento import DatosInsuficientes, entrenar_modelo
from app.servicios.ingesta.sincronizacion import calcular_resultado, sincronizar_todo
from app.servicios.metricas import recalcular_metricas_por_jornada
from app.servicios.predicciones import (
    ModeloNoDisponible,
    backfill_historico,
    generar_predicciones,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("manage")


def crear_admin(email: str | None = None, password: str | None = None) -> int:
    config = obtener_config()
    email = email or config.admin_email_inicial or input("Email del admin: ").strip()
    password = password or config.admin_password_inicial or getpass.getpass("Contrasena: ")

    fallas = validar_fortaleza_password(password)
    if fallas:
        log.error("Contrasena debil: %s", "; ".join(fallas))
        return 1

    email = normalizar_email(email)
    db = FabricaSesion()
    try:
        existente = db.execute(
            select(Usuario).where(Usuario.email_indice == indice_ciego(email))
        ).scalar_one_or_none()
        if existente is not None:
            existente.rol = Rol.ADMIN
            existente.password_hash = hashear_password(password)
            db.commit()
            log.info("Usuario existente promovido a admin y contrasena actualizada")
            return 0
        db.add(
            Usuario(
                email=email,
                email_indice=indice_ciego(email),
                password_hash=hashear_password(password),
                rol=Rol.ADMIN,
            )
        )
        db.commit()
        log.info("Admin creado. Recordar borrar ADMIN_PASSWORD_INICIAL del .env.")
        return 0
    finally:
        db.close()


def cmd_sincronizar() -> int:
    db = FabricaSesion()
    try:
        log.info("Partidos sincronizados: %d", sincronizar_todo(db))
        return 0
    finally:
        db.close()


def cmd_entrenar(algoritmo: str) -> int:
    db = FabricaSesion()
    try:
        resumen = entrenar_modelo(db, algoritmo=algoritmo)
        log.info(
            "Modelo %s | %d partidos | accuracy walk-forward %.3f (linea base %.3f) | "
            "log-loss %.3f | brier %.3f",
            resumen.version,
            resumen.partidos_entrenamiento,
            resumen.accuracy,
            resumen.linea_base,
            resumen.log_loss,
            resumen.brier,
        )
        return 0
    except DatosInsuficientes as exc:
        log.error("%s", exc)
        return 1
    finally:
        db.close()


def cmd_predecir() -> int:
    db = FabricaSesion()
    try:
        log.info("Predicciones generadas: %d", generar_predicciones(db))
        return 0
    except ModeloNoDisponible as exc:
        log.error("%s", exc)
        return 1
    finally:
        db.close()


def cmd_backtest(algoritmo: str) -> int:
    db = FabricaSesion()
    try:
        creadas = backfill_historico(db, algoritmo=algoritmo)
        log.info("Predicciones historicas (walk-forward): %d", creadas)
        log.info("Jornadas recalculadas: %d", recalcular_metricas_por_jornada(db))
        return 0
    finally:
        db.close()


def cmd_metricas() -> int:
    db = FabricaSesion()
    try:
        log.info("Jornadas recalculadas: %d", recalcular_metricas_por_jornada(db))
        return 0
    finally:
        db.close()


# --- Datos de demostracion ---

EQUIPOS_DEMO = [
    ("Olimpia", "Primera Division de Paraguay", "Paraguay"),
    ("Cerro Porteno", "Primera Division de Paraguay", "Paraguay"),
    ("Libertad", "Primera Division de Paraguay", "Paraguay"),
    ("Guarani", "Primera Division de Paraguay", "Paraguay"),
    ("Nacional", "Primera Division de Paraguay", "Paraguay"),
    ("Sportivo Luqueno", "Primera Division de Paraguay", "Paraguay"),
    ("Sol de America", "Primera Division de Paraguay", "Paraguay"),
    ("General Diaz", "Primera Division de Paraguay", "Paraguay"),
    ("Tacuary", "Primera Division de Paraguay", "Paraguay"),
    ("Resistencia", "Primera Division de Paraguay", "Paraguay"),
]


def cmd_demo(temporadas: int = 3, semilla: int = 7) -> int:
    """Genera un historico simulado para poder probar el pipeline sin API keys.

    Los resultados se sortean con un Poisson cuya media depende de la fuerza
    latente de cada equipo, asi el modelo tiene senal real que aprender (y el
    accuracy resultante es interpretable, no ruido puro).
    """
    rng = random.Random(semilla)
    Base.metadata.create_all(bind=engine)
    db = FabricaSesion()
    try:
        if db.execute(select(Partido).limit(1)).scalar_one_or_none() is not None:
            log.warning("Ya hay partidos cargados; no se generan datos de demo")
            return 0

        equipos = []
        for i, (nombre, liga, pais) in enumerate(EQUIPOS_DEMO, start=1):
            equipo = Equipo(
                nombre=nombre,
                nombre_corto=nombre[:3].upper(),
                liga=liga,
                pais=pais,
                fuente=Fuente.API_FOOTBALL,
                external_id=f"demo-{i}",
            )
            db.add(equipo)
            equipos.append(equipo)
        db.flush()

        # Fuerza latente: el modelo no la ve, la tiene que inferir de los datos.
        fuerza = {e.id: rng.uniform(0.75, 1.45) for e in equipos}
        elo = {e.id: 1500.0 for e in equipos}

        inicio = datetime.now(timezone.utc) - timedelta(days=temporadas * 300)
        fecha = inicio
        jornada = 0
        externo = 0

        for temporada in range(temporadas):
            ids = [e.id for e in equipos]
            for vuelta in range(2):  # ida y vuelta
                for _ronda in range(len(ids) - 1):
                    jornada += 1
                    rng.shuffle(ids)
                    for a, b in zip(ids[::2], ids[1::2], strict=False):
                        local, visitante = (a, b) if vuelta == 0 else (b, a)
                        externo += 1
                        # Ventaja de localia incluida en la media de goles.
                        lam_l = 1.35 * fuerza[local] / fuerza[visitante]
                        lam_v = 1.05 * fuerza[visitante] / fuerza[local]
                        gl = _poisson(rng, lam_l)
                        gv = _poisson(rng, lam_v)
                        db.add(
                            Partido(
                                equipo_local_id=local,
                                equipo_visitante_id=visitante,
                                fecha=fecha,
                                liga=EQUIPOS_DEMO[0][1],
                                temporada=str(2023 + temporada),
                                jornada=jornada,
                                estado=EstadoPartido.FINALIZADO,
                                goles_local=gl,
                                goles_visitante=gv,
                                resultado_real=calcular_resultado(gl, gv),
                                fuente=Fuente.API_FOOTBALL,
                                external_id=f"demo-p-{externo}",
                            )
                        )
                        elo[local], elo[visitante] = actualizar_elo(
                            elo[local], elo[visitante], gl, gv
                        )
                    fecha += timedelta(days=7)

        # Fecha proxima sin resultado, para tener que predecir.
        ids = [e.id for e in equipos]
        jornada += 1
        for a, b in zip(ids[::2], ids[1::2], strict=False):
            externo += 1
            db.add(
                Partido(
                    equipo_local_id=a,
                    equipo_visitante_id=b,
                    fecha=datetime.now(timezone.utc) + timedelta(days=3),
                    liga=EQUIPOS_DEMO[0][1],
                    temporada=str(2023 + temporadas - 1),
                    jornada=jornada,
                    estado=EstadoPartido.PROGRAMADO,
                    fuente=Fuente.API_FOOTBALL,
                    external_id=f"demo-p-{externo}",
                )
            )
        db.commit()
        total = db.execute(select(Partido)).unique().scalars().all()
        log.info("Datos de demo generados: %d partidos, %d equipos", len(total), len(equipos))
        return 0
    finally:
        db.close()


def _poisson(rng: random.Random, lam: float) -> int:
    """Muestra de Poisson por el metodo de Knuth (lam chico, alcanza y sobra)."""
    limite, k, producto = pow(2.718281828459045, -lam), 0, 1.0
    while True:
        producto *= rng.random()
        if producto <= limite:
            return k
        k += 1
        if k > 15:  # corte de seguridad
            return k


def main() -> int:
    parser = argparse.ArgumentParser(description="Administracion de Prediccion Deportiva")
    sub = parser.add_subparsers(dest="comando", required=True)

    p_admin = sub.add_parser("crear-admin", help="Crea o promueve un usuario admin")
    p_admin.add_argument("--email")
    p_admin.add_argument("--password")

    sub.add_parser("sincronizar", help="Sincroniza datos de las APIs externas")

    p_entrenar = sub.add_parser("entrenar", help="Reentrena y valida el modelo")
    p_entrenar.add_argument(
        "--algoritmo", default="logistica", choices=["logistica", "random_forest"]
    )

    sub.add_parser("predecir", help="Genera predicciones para los proximos partidos")
    sub.add_parser("metricas", help="Recalcula el historial de aciertos por jornada")

    p_backtest = sub.add_parser(
        "backtest", help="Predice el historico walk-forward (llena el historial de aciertos)"
    )
    p_backtest.add_argument(
        "--algoritmo", default="logistica", choices=["logistica", "random_forest"]
    )

    p_demo = sub.add_parser("demo", help="Carga un historico simulado para probar el pipeline")
    p_demo.add_argument("--temporadas", type=int, default=3)

    args = parser.parse_args()
    match args.comando:
        case "crear-admin":
            return crear_admin(args.email, args.password)
        case "sincronizar":
            return cmd_sincronizar()
        case "entrenar":
            return cmd_entrenar(args.algoritmo)
        case "predecir":
            return cmd_predecir()
        case "metricas":
            return cmd_metricas()
        case "backtest":
            return cmd_backtest(args.algoritmo)
        case "demo":
            return cmd_demo(args.temporadas)
    return 1


if __name__ == "__main__":
    sys.exit(main())
