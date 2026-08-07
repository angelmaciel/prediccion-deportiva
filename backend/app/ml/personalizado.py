"""Punto de extension para analisis propios.

Aca va la logica de analisis que uno escribe a mano: reglas, heuristicas,
lecturas de un dato que el modelo no mira. Un analizador recibe todo lo que se
sabe del partido y devuelve una `Senial`, o `None` si no tiene nada para decir.

Como agregar uno:

    @registrar
    def mi_analisis(c: ContextoPartido) -> Senial | None:
        if c.local.corners_promedio() > 7:
            return Senial("Corners", "El local promedia mas de 7", favorece="L")
        return None

Nada mas: el veredicto de cada partido lo va a ejecutar y mostrar. No hace falta
reentrenar ni migrar la base, porque una senial no toca las probabilidades del
modelo — se muestra al lado de ellas.

**Por que no ajustan las probabilidades.** Seria facil sumarle o restarle unos
puntos al modelo segun las seniales, y es tentador. Pero las probabilidades del
sistema estan calibradas contra 30.000 partidos y se publican como tales;
moverlas a mano con pesos elegidos a ojo rompe esa calibracion sin dejar rastro,
y el historial de aciertos dejaria de medir lo que dice medir. Si una senial es
buena de verdad, el lugar honesto es convertirla en feature y dejar que el
entrenamiento le asigne su peso con evidencia.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from statistics import mean

from app.modelos.futbol import FeaturesPartido, Partido

logger = logging.getLogger(__name__)

LOCAL = "L"
VISITANTE = "V"
NINGUNO = "-"


@dataclass(slots=True)
class Senial:
    """La lectura que deja un analizador."""

    nombre: str
    detalle: str
    favorece: str = NINGUNO  # "L", "V" o "-"
    # Cuanta importancia le da el autor, de 0 a 1. No altera las probabilidades:
    # solo ordena las seniales y regula su peso visual.
    peso: float = 0.5


@dataclass(slots=True)
class LadoPartido:
    """Todo lo que se sabe de uno de los dos equipos llegando a este partido."""

    equipo_id: int
    nombre: str
    de_local: bool
    # Partidos previos del equipo contra cualquier rival, del mas reciente al
    # mas viejo. Ya vienen filtrados a finalizados.
    previos: list[Partido] = field(default_factory=list)

    def _mio(self, previo: Partido) -> bool:
        return previo.equipo_local_id == self.equipo_id

    def goles_favor(self) -> list[int]:
        return [(p.goles_local if self._mio(p) else p.goles_visitante) or 0 for p in self.previos]

    def goles_contra(self) -> list[int]:
        return [(p.goles_visitante if self._mio(p) else p.goles_local) or 0 for p in self.previos]

    def estadistica(self, campo: str) -> list[int]:
        """Valores de una estadistica propia ('corners', 'remates', ...).

        Solo devuelve los partidos que tienen el dato: promediar sobre los que
        faltan como si fueran cero inventaria un equipo que no patea al arco.
        """
        valores = []
        for previo in self.previos:
            if previo.estadisticas is None:
                continue
            lado = "local" if self._mio(previo) else "visitante"
            valor = getattr(previo.estadisticas, f"{campo}_{lado}", None)
            if valor is not None:
                valores.append(valor)
        return valores

    def promedio(self, campo: str) -> float | None:
        valores = self.estadistica(campo)
        return mean(valores) if valores else None

    def puntos_recientes(self, ventana: int = 5) -> int:
        puntos = 0
        for favor, contra in list(zip(self.goles_favor(), self.goles_contra(), strict=True))[
            :ventana
        ]:
            puntos += 3 if favor > contra else 1 if favor == contra else 0
        return puntos


@dataclass(slots=True)
class ContextoPartido:
    """Lo que recibe un analizador."""

    partido: Partido
    local: LadoPartido
    visitante: LadoPartido
    # Cruces directos previos, del mas reciente al mas viejo.
    h2h: list[Partido] = field(default_factory=list)
    # Features ya calculadas (Elo, forma, descanso, H2H) del mismo partido.
    features: FeaturesPartido | None = None
    # Matriz de marcadores del Poisson, si hay modelo ajustado.
    matriz: list[list[float]] | None = None


Analizador = Callable[[ContextoPartido], Senial | None]

ANALIZADORES: list[Analizador] = []


def registrar(analizador: Analizador) -> Analizador:
    """Decorador que suma un analizador a los que corren en cada partido."""
    ANALIZADORES.append(analizador)
    return analizador


def evaluar(contexto: ContextoPartido) -> list[Senial]:
    """Corre todos los analizadores.

    Un analizador que explota no tumba el veredicto, pero si queda en el log:
    fallar en silencio haria que una regla rota parezca simplemente una regla
    que no tenia nada para decir.
    """
    seniales: list[Senial] = []
    for analizador in ANALIZADORES:
        try:
            senial = analizador(contexto)
        except Exception:
            logger.exception(
                "El analizador %s fallo en el partido %s",
                getattr(analizador, "__name__", analizador),
                contexto.partido.id,
            )
            continue
        if senial is not None:
            seniales.append(senial)
    return sorted(seniales, key=lambda s: s.peso, reverse=True)


# --------------------------------------------------------------------------
# Ejemplos. Se pueden borrar: estan para mostrar la forma de un analizador.
# --------------------------------------------------------------------------


@registrar
def presion_ofensiva(contexto: ContextoPartido) -> Senial | None:
    """Quien llega generando mas peligro, medido en remates al arco."""
    local = contexto.local.promedio("remates_arco")
    visitante = contexto.visitante.promedio("remates_arco")
    if local is None or visitante is None:
        return None

    diferencia = local - visitante
    if abs(diferencia) < 1.0:  # menos de un remate al arco de diferencia es ruido
        return None
    return Senial(
        nombre="Presion ofensiva",
        detalle=f"{local:.1f} contra {visitante:.1f} remates al arco por partido",
        favorece=LOCAL if diferencia > 0 else VISITANTE,
        peso=min(1.0, abs(diferencia) / 4),
    )


@registrar
def solidez_defensiva(contexto: ContextoPartido) -> Senial | None:
    """Quien recibe menos goles llegando al partido."""
    local = contexto.local.goles_contra()
    visitante = contexto.visitante.goles_contra()
    if len(local) < 3 or len(visitante) < 3:
        return None

    promedio_local, promedio_visitante = mean(local[:5]), mean(visitante[:5])
    diferencia = promedio_visitante - promedio_local  # positivo: el local recibe menos
    if abs(diferencia) < 0.5:
        return None
    return Senial(
        nombre="Solidez defensiva",
        detalle=(
            f"{promedio_local:.1f} contra {promedio_visitante:.1f} goles recibidos por partido"
        ),
        favorece=LOCAL if diferencia > 0 else VISITANTE,
        peso=min(1.0, abs(diferencia) / 1.5),
    )


@registrar
def dominio_historico(contexto: ContextoPartido) -> Senial | None:
    """Un historial directo muy parejo para un lado dice algo por si solo."""
    if len(contexto.h2h) < 4:
        return None

    local_id = contexto.partido.equipo_local_id
    ganados = sum(
        1
        for p in contexto.h2h
        if (p.equipo_local_id == local_id and (p.goles_local or 0) > (p.goles_visitante or 0))
        or (p.equipo_visitante_id == local_id and (p.goles_visitante or 0) > (p.goles_local or 0))
    )
    proporcion = ganados / len(contexto.h2h)
    if 0.25 < proporcion < 0.75:
        return None
    return Senial(
        nombre="Dominio historico",
        detalle=f"{ganados} de {len(contexto.h2h)} cruces para {contexto.local.nombre}",
        favorece=LOCAL if proporcion >= 0.75 else VISITANTE,
        peso=0.6,
    )
