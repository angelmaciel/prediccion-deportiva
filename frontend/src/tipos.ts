// Tipos que reflejan los esquemas Pydantic del backend.

export interface Equipo {
  id: number
  nombre: string
  nombre_corto: string | null
  liga: string
  pais: string
  escudo_url: string | null
}

export interface Prediccion {
  prob_local: number
  prob_empate: number
  prob_visitante: number
  marcador_probable_local: number | null
  marcador_probable_visitante: number | null
  modelo_version: string
  resultado_predicho: 'L' | 'E' | 'V'
  confianza: number
  creado_en: string
}

export type EstadoPartido = 'programado' | 'en_juego' | 'finalizado' | 'suspendido'

export interface Partido {
  id: number
  fecha: string
  liga: string
  temporada: string | null
  jornada: number | null
  estado: EstadoPartido
  equipo_local: Equipo
  equipo_visitante: Equipo
  goles_local: number | null
  goles_visitante: number | null
  resultado_real: 'L' | 'E' | 'V' | null
  prediccion: Prediccion | null
}

export interface PaginaPartidos {
  total: number
  pagina: number
  por_pagina: number
  items: Partido[]
}

export interface MetricaJornada {
  liga: string
  temporada: string | null
  jornada: number | null
  modelo_version: string
  partidos_evaluados: number
  aciertos: number
  accuracy: number
  brier: number | null
}

export interface ResumenModelo {
  version_activa: string | null
  algoritmo: string | null
  entrenado_en: string | null
  partidos_entrenamiento: number
  accuracy_walk_forward: number | null
  log_loss: number | null
  brier: number | null
  partidos_evaluados: number
  aciertos: number
  accuracy_real: number
  linea_base_local: number
  aviso: string
}

export interface VersionModelo {
  version: string
  algoritmo: string
  entrenado_en: string
  partidos_entrenamiento: number
  accuracy: number | null
  log_loss: number | null
  brier: number | null
  activa: boolean
}

export interface Usuario {
  id: number
  email: string
  rol: 'usuario' | 'admin'
  totp_activo: boolean
  creado_en: string
}

/** Formas de ingreso habilitadas en el backend que esta sirviendo. */
export interface Proveedores {
  google: boolean
}

/** Promedios por partido. `null` = la fuente no publica ese dato. */
export interface PromediosH2H {
  goles_favor: number | null
  goles_contra: number | null
  remates: number | null
  remates_arco: number | null
  corners: number | null
  faltas: number | null
  amarillas: number | null
  rojas: number | null
  atajadas: number | null
}

export interface EquipoH2H {
  equipo_id: number
  nombre: string
  jugados: number
  ganados: number
  empatados: number
  perdidos: number
  promedios: PromediosH2H
}

export interface CruceH2H {
  partido_id: number
  fecha: string
  liga: string
  temporada: string | null
  local: string
  visitante: string
  goles_local: number
  goles_visitante: number
  tiene_estadisticas: boolean
}

/** Un partido contado desde la optica de uno de los dos equipos. */
export interface PartidoDeRacha {
  partido_id: number
  fecha: string
  liga: string
  temporada: string | null
  rival: string
  de_local: boolean
  goles_favor: number
  goles_contra: number
  resultado: 'G' | 'E' | 'P'
  tiene_estadisticas: boolean
}

/** Como viene el equipo contra cualquier rival, no solo contra este. */
export interface RachaEquipo {
  equipo_id: number
  nombre: string
  jugados: number
  ganados: number
  empatados: number
  perdidos: number
  promedios: PromediosH2H
  partidos_con_estadisticas: number
  partidos: PartidoDeRacha[]
}

export interface HistorialH2H {
  partido_id: number
  solo_misma_localia: boolean
  liga: string | null
  total_cruces: number
  cruces_con_estadisticas: number
  local: EquipoH2H
  visitante: EquipoH2H
  cruces: CruceH2H[]
  racha_local: RachaEquipo
  racha_visitante: RachaEquipo
  aviso_atajadas: string
}
