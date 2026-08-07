"""Importador del historico gratuito de football-data.co.uk.

No es una API: son CSV estaticos, publicos y sin credenciales, con una decada
larga de resultados por liga. Es la unica fuente gratuita con esa profundidad,
y la profundidad es justamente lo que el Elo y la forma reciente necesitan: el
plan gratis de football-data.org solo trae la temporada en curso, asi que al
arrancar una temporada los equipos no tienen historia y las features salen frias.

El trabajo delicado esta en `_resolver`: los CSV usan nombres cortos ("Man
United", "Betis") y football-data.org nombres largos ("Manchester United FC",
"Real Betis Balompie"). Si no se reconcilian, el historico queda colgado de
equipos distintos a los de los partidos futuros y no mejora ninguna prediccion.
"""

from __future__ import annotations

import csv
import hashlib
import io
import logging
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modelos.futbol import (
    Equipo,
    EstadisticasPartido,
    EstadoPartido,
    Fuente,
    Partido,
    Resultado,
)

logger = logging.getLogger(__name__)

BASE = "https://www.football-data.co.uk/mmz4281"

# Divisiones que se corresponden con las competiciones que ya sincronizamos de
# football-data.org; el nombre de liga debe coincidir exactamente para que la
# reconciliacion de equipos busque en el conjunto correcto.
DIVISIONES = {
    "E0": ("Premier League", "Inglaterra"),
    "E1": ("Championship", "Inglaterra"),
    "SP1": ("La Liga", "Espana"),
    "I1": ("Serie A", "Italia"),
    "D1": ("Bundesliga", "Alemania"),
    "F1": ("Ligue 1", "Francia"),
    "N1": ("Eredivisie", "Paises Bajos"),
    "P1": ("Primeira Liga", "Portugal"),
}

# Formas juridicas que no hacen a la identidad del club. Ojo con lo que se saca:
# "real" y "sporting" parecen ruido pero distinguen clubes enteros (Real Madrid
# vs Rayo Vallecano de Madrid), asi que se conservan.
RUIDO = {
    "fc",
    "afc",
    "cf",
    "ac",
    "sc",
    "ss",
    "ssc",
    "as",
    "us",
    "ud",
    "cd",
    "rc",
    "rcd",
    "ca",
    "sv",
    "sd",
    "bv",
    "vv",
    "bsc",
    "fsv",
    "tsg",
    "tsv",
    "vfb",
    "vfl",
    "sbv",
    "pec",
    "club",
    "de",
    "the",
    "calcio",
    "futbol",
    "football",
    "balompie",
}

# Casos que ninguna heuristica razonable resuelve: abreviaturas del CSV que no
# comparten palabras con el nombre oficial. La clave es el nombre del CSV ya
# normalizado; el valor es el nombre oficial tal cual, que se normaliza igual.
ALIAS_CRUDO = {
    # Inglaterra
    "man united": "Manchester United",
    "man city": "Manchester City",
    "nott forest": "Nottingham Forest",
    "wolves": "Wolverhampton Wanderers",
    "sheffield weds": "Sheffield Wednesday",
    "west brom": "West Bromwich Albion",
    "qpr": "Queens Park Rangers",
    "newcastle": "Newcastle United",
    "leeds": "Leeds United",
    "tottenham": "Tottenham Hotspur",
    "brighton": "Brighton Hove Albion",
    "leicester": "Leicester City",
    "norwich": "Norwich City",
    "stoke": "Stoke City",
    "swansea": "Swansea City",
    "cardiff": "Cardiff City",
    "hull": "Hull City",
    "birmingham": "Birmingham City",
    "coventry": "Coventry City",
    "ipswich": "Ipswich Town",
    "luton": "Luton Town",
    "preston": "Preston North End",
    "blackburn": "Blackburn Rovers",
    "bolton": "Bolton Wanderers",
    "derby": "Derby County",
    "wigan": "Wigan Athletic",
    "sheffield united": "Sheffield United",
    # Espana
    "ath madrid": "Atletico Madrid",
    "ath bilbao": "Athletic Club",
    "espanol": "Espanyol Barcelona",
    "sociedad": "Real Sociedad",
    "betis": "Real Betis",
    "vallecano": "Rayo Vallecano",
    "celta": "Celta Vigo",
    "la coruna": "Deportivo La Coruna",
    "sp gijon": "Sporting Gijon",
    "santander": "Racing Santander",
    "vallodolid": "Real Valladolid",
    # Italia
    "inter": "Internazionale",
    # Alemania
    "gladbach": "Monchengladbach",
    "bayern munich": "Bayern Munchen",
    "ein frankfurt": "Eintracht Frankfurt",
    "hamburg": "Hamburger",
    # Francia
    "paris sg": "Paris Saint-Germain",
    "marseille": "Marseille",
    "lyon": "Lyonnais",
    "st etienne": "Saint-Etienne",
    "brest": "Brestois",
    "rennes": "Rennais",
    # Paises Bajos
    "psv eindhoven": "PSV",
    "az alkmaar": "AZ",
    "nijmegen": "NEC",
    "for sittard": "Fortuna Sittard",
    # Portugal
    "sp lisbon": "Sporting Clube de Portugal",
    "sp braga": "Braga",
    "guimaraes": "Vitoria",
}

# Cuantas palabras puede tener de mas el nombre oficial. Con 2 entra
# "Racing Club de Lens" para el "Lens" del CSV; con mas empiezan los disparates.
MAX_PALABRAS_SOBRANTES = 2


# Columna del CSV -> campo de EstadisticasPartido. Las viejas temporadas a veces
# no traen alguna, por eso todo lo que falte queda en None y no en cero.
ESTADISTICAS = {
    "HS": "remates_local",
    "AS": "remates_visitante",
    "HST": "remates_arco_local",
    "AST": "remates_arco_visitante",
    "HC": "corners_local",
    "AC": "corners_visitante",
    "HF": "faltas_local",
    "AF": "faltas_visitante",
    "HY": "amarillas_local",
    "AY": "amarillas_visitante",
    "HR": "rojas_local",
    "AR": "rojas_visitante",
}


@dataclass(slots=True)
class FilaHistorica:
    fecha: datetime
    local: str
    visitante: str
    goles_local: int
    goles_visitante: int
    estadisticas: dict[str, int]


@dataclass(slots=True)
class ResultadoImportacion:
    partidos_nuevos: int = 0
    partidos_actualizados: int = 0
    equipos_creados: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.equipos_creados is None:
            self.equipos_creados = []


def normalizar(nombre: str) -> str:
    """Reduce un nombre de club a su nucleo comparable.

    Saca acentos, puntuacion, numeros sueltos y formas juridicas: "1. FC Koln"
    y "FC Koln" colapsan a "koln".
    """
    sin_acentos = "".join(
        c for c in unicodedata.normalize("NFKD", nombre) if not unicodedata.combining(c)
    )
    limpio = re.sub(r"[^a-z0-9 ]+", " ", sin_acentos.lower())
    # Se descartan numeros de fundacion ("Como 1907") y letras sueltas ("Sport
    # Lisboa e Benfica"): solo suman palabras de sobra al comparar.
    palabras = [p for p in limpio.split() if len(p) > 1 and p not in RUIDO and not p.isdigit()]
    return " ".join(palabras)


def _tokens(nombre: str) -> list[str]:
    return normalizar(nombre).split()


def _misma_palabra(a: str, b: str) -> bool:
    """Tolera variantes ortograficas ("munich"/"munchen") sin unir palabras distintas."""
    return a == b or SequenceMatcher(None, a, b).ratio() >= 0.86


def _sobrantes(objetivo: list[str], candidato: list[str]) -> int | None:
    """Cuantas palabras le sobran al candidato si contiene a todas las del objetivo.

    Devuelve None si no lo contiene. La contencion es la relacion correcta:
    el CSV usa nombres cortos ("Angers") y la API nombres largos ("Angers SCO"),
    pero siempre el corto esta adentro del largo.
    """
    usados: set[int] = set()
    for palabra in objetivo:
        for i, otra in enumerate(candidato):
            if i not in usados and _misma_palabra(palabra, otra):
                usados.add(i)
                break
        else:
            return None
    return len(candidato) - len(usados)


def _indice_equipos(db: Session, pais: str) -> list[tuple[list[str], Equipo]]:
    """Indexa por pais, no por liga.

    La sincronizacion pisa el campo `liga` con la ultima competicion vista, asi
    que despues de sincronizar la Champions los grandes quedan con liga
    "Champions League". El pais, en cambio, no se sobrescribe nunca.
    """
    equipos = db.execute(select(Equipo).where(Equipo.pais == pais)).scalars().all()
    return [(_tokens(e.nombre), e) for e in equipos]


def _resolver(
    nombre_csv: str, indice: list[tuple[list[str], Equipo]]
) -> tuple[Equipo | None, float]:
    """Busca el equipo ya existente que corresponde a un nombre del CSV.

    Gana el que contiene al nombre del CSV con menos palabras de sobra. El
    desempate importa: "Barcelona" esta dentro de "FC Barcelona" (0 sobrantes) y
    de "RCD Espanyol de Barcelona" (1 sobrante), y confundirlos le regalaria al
    Espanyol una decada de resultados del Barca. Si dos candidatos empatan, se
    prefiere no resolver antes que arriesgar.
    """
    objetivo = _tokens(ALIAS_CRUDO.get(normalizar(nombre_csv), nombre_csv))
    if not objetivo:
        return None, 0.0

    candidatos: list[tuple[int, Equipo]] = []
    for tokens, equipo in indice:
        sobran = _sobrantes(objetivo, tokens)
        if sobran is not None:
            candidatos.append((sobran, equipo))
    if not candidatos:
        return None, 0.0

    candidatos.sort(key=lambda c: c[0])
    if len(candidatos) > 1 and candidatos[0][0] == candidatos[1][0]:
        logger.warning(
            "Nombre ambiguo '%s': empatan %s y %s",
            nombre_csv,
            candidatos[0][1].nombre,
            candidatos[1][1].nombre,
        )
        return None, 0.0

    sobran, equipo = candidatos[0]
    if sobran > MAX_PALABRAS_SOBRANTES:
        return None, 0.0
    return equipo, 1.0 - 0.1 * sobran


def _obtener_o_crear(
    db: Session,
    nombre_csv: str,
    liga: str,
    pais: str,
    indice: list[tuple[list[str], Equipo]],
    creados: list[str],
) -> Equipo:
    equipo, puntaje = _resolver(nombre_csv, indice)
    if equipo is not None:
        return equipo

    # Sin coincidencia: suele ser un equipo descendido que ya no juega la
    # temporada actual. Vale la pena guardarlo igual, porque sus partidos son
    # historia real de los rivales que si van a jugar.
    externo = f"{pais[:3].lower()}-{normalizar(nombre_csv)}"[:40]
    equipo = db.execute(
        select(Equipo).where(Equipo.fuente == Fuente.CSV_HISTORICO, Equipo.external_id == externo)
    ).scalar_one_or_none()
    if equipo is None:
        equipo = Equipo(
            nombre=nombre_csv,
            liga=liga,
            pais=pais,
            fuente=Fuente.CSV_HISTORICO,
            external_id=externo,
        )
        db.add(equipo)
        db.flush()
        creados.append(f"{nombre_csv} (mejor parecido {puntaje:.2f})")
        indice.append((_tokens(nombre_csv), equipo))
    return equipo


def url_temporada(division: str, temporada: str) -> str:
    return f"{BASE}/{temporada}/{division}.csv"


def descargar(division: str, temporada: str, timeout: float = 60.0) -> str:
    respuesta = httpx.get(url_temporada(division, temporada), timeout=timeout)
    if respuesta.status_code == 404:
        raise FileNotFoundError(f"{division} {temporada} no publicado")
    respuesta.raise_for_status()
    # Los archivos viejos vienen en latin-1 y los nuevos en utf-8 con BOM.
    try:
        return respuesta.content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return respuesta.content.decode("latin-1")


def parsear(texto: str) -> list[FilaHistorica]:
    filas: list[FilaHistorica] = []
    for fila in csv.DictReader(io.StringIO(texto)):
        local = (fila.get("HomeTeam") or "").strip()
        visitante = (fila.get("AwayTeam") or "").strip()
        goles_local = fila.get("FTHG") or fila.get("HG")
        goles_visitante = fila.get("FTAG") or fila.get("AG")
        crudo_fecha = (fila.get("Date") or "").strip()
        if not (local and visitante and goles_local and goles_visitante and crudo_fecha):
            # Filas vacias de relleno o partidos sin jugar.
            continue
        fecha = _fecha(crudo_fecha, (fila.get("Time") or "").strip())
        if fecha is None:
            continue
        try:
            filas.append(
                FilaHistorica(
                    fecha=fecha,
                    local=local,
                    visitante=visitante,
                    goles_local=int(goles_local),
                    goles_visitante=int(goles_visitante),
                    estadisticas=_estadisticas(fila),
                )
            )
        except ValueError:
            continue
    return filas


def _estadisticas(fila: dict) -> dict[str, int]:
    """Toma solo las columnas que estan y traen un entero."""
    leidas: dict[str, int] = {}
    for columna, campo in ESTADISTICAS.items():
        crudo = (fila.get(columna) or "").strip()
        if not crudo:
            continue
        try:
            leidas[campo] = int(float(crudo))
        except ValueError:
            continue
    return leidas


def _fecha(crudo: str, hora: str) -> datetime | None:
    """El CSV alterna dd/mm/yy y dd/mm/yyyy segun la temporada."""
    for formato in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            fecha = datetime.strptime(crudo, formato)
        except ValueError:
            continue
        if hora:
            try:
                reloj = datetime.strptime(hora, "%H:%M")
                fecha = fecha.replace(hour=reloj.hour, minute=reloj.minute)
            except ValueError:
                pass
        return fecha.replace(tzinfo=timezone.utc)
    return None


def _external_id(division: str, fila: FilaHistorica) -> str:
    firma = f"{division}|{fila.fecha:%Y%m%d}|{fila.local}|{fila.visitante}"
    # Solo se usa para dar identidad estable a la fila, no para seguridad.
    digest = hashlib.md5(firma.encode(), usedforsecurity=False).hexdigest()
    return f"csv-{division}-{digest[:12]}"


def importar_division(db: Session, division: str, temporada: str) -> ResultadoImportacion:
    """Importa una temporada de una division. Idempotente: reimportar no duplica."""
    liga, pais = DIVISIONES[division]
    texto = descargar(division, temporada)
    filas = parsear(texto)

    indice = _indice_equipos(db, pais)
    resultado = ResultadoImportacion()
    etiqueta = f"{temporada[:2]}/{temporada[2:]}"

    for fila in filas:
        local = _obtener_o_crear(db, fila.local, liga, pais, indice, resultado.equipos_creados)
        visitante = _obtener_o_crear(
            db, fila.visitante, liga, pais, indice, resultado.equipos_creados
        )
        externo = _external_id(division, fila)

        partido = db.execute(
            select(Partido).where(
                Partido.fuente == Fuente.CSV_HISTORICO, Partido.external_id == externo
            )
        ).scalar_one_or_none()
        if partido is None:
            partido = Partido(fuente=Fuente.CSV_HISTORICO, external_id=externo)
            db.add(partido)
            resultado.partidos_nuevos += 1
        else:
            resultado.partidos_actualizados += 1

        partido.equipo_local_id = local.id
        partido.equipo_visitante_id = visitante.id
        partido.fecha = fila.fecha
        partido.liga = liga
        partido.temporada = etiqueta
        partido.estado = EstadoPartido.FINALIZADO
        partido.goles_local = fila.goles_local
        partido.goles_visitante = fila.goles_visitante
        partido.resultado_real = (
            Resultado.LOCAL
            if fila.goles_local > fila.goles_visitante
            else Resultado.VISITANTE
            if fila.goles_local < fila.goles_visitante
            else Resultado.EMPATE
        )
        db.flush()

        if fila.estadisticas:
            _guardar_estadisticas(db, partido, fila.estadisticas)

    return resultado


def _guardar_estadisticas(db: Session, partido: Partido, valores: dict[str, int]) -> None:
    registro = db.execute(
        select(EstadisticasPartido).where(EstadisticasPartido.partido_id == partido.id)
    ).scalar_one_or_none()
    if registro is None:
        registro = EstadisticasPartido(partido_id=partido.id)
        db.add(registro)
    for campo, valor in valores.items():
        setattr(registro, campo, valor)
    db.flush()


def temporadas_recientes(cantidad: int, hasta: int | None = None) -> list[str]:
    """Codigos de temporada del sitio: 2025/26 se pide como '2526'."""
    fin = hasta if hasta is not None else datetime.now(timezone.utc).year
    codigos = []
    for inicio in range(fin - cantidad, fin):
        codigos.append(f"{inicio % 100:02d}{(inicio + 1) % 100:02d}")
    return codigos
