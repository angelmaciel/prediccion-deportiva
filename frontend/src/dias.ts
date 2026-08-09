// Reparto de partidos en ayer / hoy / manana.
//
// El corte es en la zona del publico y no en la del navegador ni en UTC, por la
// misma razon que en el backend: un partido de las 21:00 en Asuncion ya cayo al
// dia siguiente en UTC, y etiquetarlo como "manana" cuando el hincha lo esta por
// ver hoy es directamente incorrecto.
//
// El filtrado es en memoria y no otra consulta: la ventana entera son tres dias
// que el navegador ya tiene, asi que cambiar de dia es instantaneo.

import type { Partido } from './tipos'

export const ZONA = 'America/Asuncion'

export type Dia = 'ayer' | 'hoy' | 'manana'

export const DIAS: { clave: Dia; etiqueta: string }[] = [
  { clave: 'ayer', etiqueta: 'Ayer' },
  { clave: 'hoy', etiqueta: 'Hoy' },
  { clave: 'manana', etiqueta: 'Manana' },
]

// `en-CA` da directamente AAAA-MM-DD, que ordena y compara como texto.
const FECHA_ISO = new Intl.DateTimeFormat('en-CA', {
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  timeZone: ZONA,
})

function diaLocal(fecha: Date): string {
  return FECHA_ISO.format(fecha)
}

/** El dia al que pertenece el partido, o null si cae fuera de la ventana. */
export function diaDe(partido: Partido, ahora: Date = new Date()): Dia | null {
  const momento = new Date(partido.fecha)
  if (Number.isNaN(momento.getTime())) return null

  const hoy = diaLocal(ahora)
  const suyo = diaLocal(momento)
  if (suyo === hoy) return 'hoy'

  const dia = 86_400_000
  if (suyo === diaLocal(new Date(ahora.getTime() - dia))) return 'ayer'
  if (suyo === diaLocal(new Date(ahora.getTime() + dia))) return 'manana'
  return null
}

export function filtrarPorDia(partidos: Partido[], dia: Dia | null): Partido[] {
  if (dia === null) return partidos
  return partidos.filter((partido) => diaDe(partido) === dia)
}

/** Cuantos partidos hay en cada dia, para poder mostrarlo en los botones. */
export function contarPorDia(partidos: Partido[]): Record<Dia, number> {
  const conteo: Record<Dia, number> = { ayer: 0, hoy: 0, manana: 0 }
  for (const partido of partidos) {
    const dia = diaDe(partido)
    if (dia) conteo[dia] += 1
  }
  return conteo
}
