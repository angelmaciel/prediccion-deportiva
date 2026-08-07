"""Veredicto: una lectura unica del partido a partir de los dos modelos.

El sistema entrena dos cosas distintas sobre los mismos datos: una logistica
que estima directamente 1X2 a partir de features (Elo, forma, descanso, H2H) y
un Poisson bivariado que estima el marcador. Miran el partido desde angulos
distintos, y por eso vale mas su acuerdo que cualquiera de los dos por separado.

El veredicto no es un pronostico ni un consejo: es el escenario al que los dos
modelos le asignan mas probabilidad, acompaniado de cuanto se parecen entre si
y de los factores que lo empujan. Cuando discrepan, se dice.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.core.config import obtener_config
from app.ml.features import NOMBRES_FEATURES
from app.ml.mercados import ResultadoEscenario, combinadas, simples
from app.ml.modelo import CLASES, ModeloPrediccion
from app.ml.persistencia import cargar_poisson_activo
from app.ml.personalizado import ContextoPartido, LadoPartido, Senial, evaluar
from app.ml.poisson import ModeloPoissonBivariado
from app.modelos.futbol import FeaturesPartido, Partido

ETIQUETAS = {"L": "Gana el local", "E": "Empate", "V": "Gana el visitante"}

# Umbrales de confianza. Son deliberadamente conservadores: en 1X2 la clase mas
# probable rara vez pasa del 60%, y llamar "alta" a un 45% seria vender humo.
UMBRAL_ALTA = 0.55
UMBRAL_MEDIA = 0.42


class SinModelo(RuntimeError):
    """No hay modelo entrenado todavia."""


@dataclass(slots=True)
class Factor:
    """Un dato observable que empuja el partido para un lado."""

    nombre: str
    detalle: str
    favorece: str  # "L", "V" o "-"


@dataclass(slots=True)
class Veredicto:
    partido_id: int
    resultado: str
    etiqueta: str
    probabilidad: float
    confianza: str
    consenso: bool
    prob_logistica: tuple[float, float, float]
    prob_poisson: tuple[float, float, float]
    marcador_probable: tuple[int, int, float] | None
    factores: list[Factor] = field(default_factory=list)
    escenarios_simples: list[ResultadoEscenario] = field(default_factory=list)
    escenarios_combinados: list[ResultadoEscenario] = field(default_factory=list)
    # Lo que devuelven los analizadores propios de `app.ml.personalizado`. Van
    # aparte de `factores` para que se vea que no salen del modelo entrenado.
    senales: list[Senial] = field(default_factory=list)


def _factores(features: FeaturesPartido | None) -> list[Factor]:
    if features is None:
        return []

    diferencia_elo = features.elo_local - features.elo_visitante
    diferencia_forma = features.forma_reciente_local - features.forma_reciente_visitante
    total_h2h = features.h2h_local_wins + features.h2h_draws + features.h2h_away_wins

    factores = [
        Factor(
            nombre="Elo",
            detalle=(
                f"{features.elo_local:.0f} contra {features.elo_visitante:.0f} "
                f"({diferencia_elo:+.0f} para el local)"
            ),
            # Menos de 25 puntos de Elo es ruido: no alcanza para inclinar nada.
            favorece="L" if diferencia_elo > 25 else "V" if diferencia_elo < -25 else "-",
        ),
        Factor(
            nombre="Forma reciente",
            detalle=(
                f"{features.forma_reciente_local:.0f} contra "
                f"{features.forma_reciente_visitante:.0f} puntos en los ultimos 5"
            ),
            favorece="L" if diferencia_forma > 2 else "V" if diferencia_forma < -2 else "-",
        ),
    ]

    if total_h2h:
        factores.append(
            Factor(
                nombre="Historial directo",
                detalle=(
                    f"{features.h2h_local_wins}-{features.h2h_draws}-"
                    f"{features.h2h_away_wins} en {total_h2h} cruces"
                ),
                favorece=(
                    "L"
                    if features.h2h_local_wins > features.h2h_away_wins
                    else "V"
                    if features.h2h_away_wins > features.h2h_local_wins
                    else "-"
                ),
            )
        )

    diferencia_descanso = features.dias_descanso_local - features.dias_descanso_visitante
    if abs(diferencia_descanso) >= 2:
        factores.append(
            Factor(
                nombre="Descanso",
                detalle=(
                    f"{features.dias_descanso_local:.0f} contra "
                    f"{features.dias_descanso_visitante:.0f} dias desde el ultimo partido"
                ),
                favorece="L" if diferencia_descanso > 0 else "V",
            )
        )

    return factores


def _confianza(probabilidad: float, consenso: bool) -> str:
    """Baja el escalon cuando los modelos no coinciden, por mas alta que sea la
    probabilidad: la discrepancia es en si misma una senial de incertidumbre."""
    if not consenso:
        return "media" if probabilidad >= UMBRAL_ALTA else "baja"
    if probabilidad >= UMBRAL_ALTA:
        return "alta"
    if probabilidad >= UMBRAL_MEDIA:
        return "media"
    return "baja"


def _contexto(db: Session | None, partido: Partido, matriz: list[list[float]] | None):
    """Arma lo que reciben los analizadores propios.

    Sin sesion de base se arma igual, pero sin historial: los analizadores que
    lo necesiten devolveran `None` y simplemente no apareceran.
    """
    h2h: list[Partido] = []
    previos_local: list[Partido] = []
    previos_visitante: list[Partido] = []
    if db is not None:
        from app.servicios.h2h import enfrentamientos_previos, ultimos_partidos

        h2h = enfrentamientos_previos(db, partido)
        previos_local = ultimos_partidos(db, partido.equipo_local_id, partido.fecha)
        previos_visitante = ultimos_partidos(db, partido.equipo_visitante_id, partido.fecha)

    return ContextoPartido(
        partido=partido,
        local=LadoPartido(
            equipo_id=partido.equipo_local_id,
            nombre=partido.equipo_local.nombre,
            de_local=True,
            previos=previos_local,
        ),
        visitante=LadoPartido(
            equipo_id=partido.equipo_visitante_id,
            nombre=partido.equipo_visitante.nombre,
            de_local=False,
            previos=previos_visitante,
        ),
        h2h=h2h,
        features=partido.features,
        matriz=matriz,
    )


def construir_veredicto(
    partido: Partido,
    modelo: ModeloPrediccion,
    poisson: ModeloPoissonBivariado | None = None,
    max_simples: int = 8,
    max_combinadas: int = 8,
    db: Session | None = None,
) -> Veredicto:
    features = partido.features
    if features is None:
        raise SinModelo("El partido todavia no tiene features calculadas")

    vector = [getattr(features, nombre) for nombre in NOMBRES_FEATURES]
    probs = modelo.predecir_probabilidades([vector])[0]
    prob_logistica = (float(probs[0]), float(probs[1]), float(probs[2]))

    poisson = poisson or cargar_poisson_activo(obtener_config().directorio_artefactos)
    if poisson is None or not poisson.ajustado:
        # Sin Poisson no hay matriz y por lo tanto no hay escenarios; el
        # veredicto se apoya solo en la logistica y se dice que no hubo consenso.
        return _sin_poisson(partido, prob_logistica, _factores(features))

    matriz = poisson.matriz_marcadores(partido.equipo_local_id, partido.equipo_visitante_id)
    prob_poisson = poisson.probabilidades_1x2(partido.equipo_local_id, partido.equipo_visitante_id)

    # Promedio simple de los dos modelos: sin pesos ajustados a mano, que serian
    # imposibles de justificar con la evidencia que hay.
    promedio = tuple((a + b) / 2 for a, b in zip(prob_logistica, prob_poisson, strict=True))
    indice = max(range(3), key=lambda i: promedio[i])
    resultado = CLASES[indice]

    consenso = (
        CLASES[max(range(3), key=lambda i: prob_logistica[i])]
        == CLASES[max(range(3), key=lambda i: prob_poisson[i])]
    )

    return Veredicto(
        partido_id=partido.id,
        resultado=resultado,
        etiqueta=ETIQUETAS[resultado],
        probabilidad=promedio[indice],
        confianza=_confianza(promedio[indice], consenso),
        consenso=consenso,
        prob_logistica=prob_logistica,
        prob_poisson=prob_poisson,
        marcador_probable=poisson.marcador_mas_probable(
            partido.equipo_local_id, partido.equipo_visitante_id
        ),
        factores=_factores(features),
        escenarios_simples=simples(matriz)[:max_simples],
        escenarios_combinados=combinadas(matriz)[:max_combinadas],
        senales=evaluar(_contexto(db, partido, matriz)),
    )


def _sin_poisson(
    partido: Partido, prob_logistica: tuple[float, float, float], factores: list[Factor]
) -> Veredicto:
    indice = max(range(3), key=lambda i: prob_logistica[i])
    resultado = CLASES[indice]
    return Veredicto(
        partido_id=partido.id,
        resultado=resultado,
        etiqueta=ETIQUETAS[resultado],
        probabilidad=prob_logistica[indice],
        confianza=_confianza(prob_logistica[indice], consenso=False),
        consenso=False,
        prob_logistica=prob_logistica,
        prob_poisson=(0.0, 0.0, 0.0),
        marcador_probable=None,
        factores=factores,
    )
