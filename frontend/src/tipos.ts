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
