// Instantanea estatica: la copia del dia que el sitio sirve desde el CDN.
//
// La API corre en el plan gratuito de Render, que duerme el servicio tras unos
// minutos sin trafico. La primera visita despues de eso espera el arranque en
// frio entero. Este archivo lo genera el job diario y viaja junto al frontend,
// asi que se baja del borde en milisegundos aunque el backend este dormido: la
// portada pinta con esto y despues se corrige sola cuando responde la API.
//
// Importante: se pide sin credenciales. Una respuesta atada a cookies no la
// puede cachear una capa compartida, y todo el punto de esto es que la sirva el
// CDN sin consultarle a nadie.

import type { PaginaPartidos, Partido } from './tipos'

interface Instantanea {
  generado_en: string
  dias: number
  ligas: string[]
  proximos: Partido[]
  resultados: Partido[]
}

const RUTA = '/datos/instantanea.json'
const DIA_MS = 86_400_000

let enCache: Promise<Instantanea | null> | null = null

function esInstantanea(dato: unknown): dato is Instantanea {
  // El servidor estatico responde el index.html ante una ruta que no existe,
  // asi que un 200 no alcanza para dar por buena la respuesta.
  const posible = dato as Instantanea | null
  return (
    !!posible && Array.isArray(posible.proximos) && Array.isArray(posible.resultados)
  )
}

function cargar(): Promise<Instantanea | null> {
  enCache ??= fetch(RUTA, { credentials: 'omit' })
    .then((respuesta) => (respuesta.ok ? respuesta.json() : null))
    .then((dato) => (esInstantanea(dato) ? dato : null))
    // Que no exista o este rota no es un error: solo significa que hay que
    // esperar a la API, que es exactamente lo que pasaba antes.
    .catch(() => null)
  return enCache
}

/** [inicio de ayer, inicio de pasado manana) en UTC: la misma ventana que aplica la API. */
export function ventanaReciente(ahora: Date = new Date()): [number, number] {
  const inicioDeHoy = Date.UTC(ahora.getUTCFullYear(), ahora.getUTCMonth(), ahora.getUTCDate())
  return [inicioDeHoy - DIA_MS, inicioDeHoy + 2 * DIA_MS]
}

function enLaVentana(partidos: Partido[], liga?: string): Partido[] {
  const [inicio, fin] = ventanaReciente()
  return partidos.filter((partido) => {
    const momento = Date.parse(partido.fecha)
    return momento >= inicio && momento < fin && (!liga || partido.liga === liga)
  })
}

/**
 * Una instantanea vieja se queda sin partidos al recortarla a la ventana de hoy.
 * En ese caso devuelve null y no una lista vacia: vacio significa "hoy no se
 * juega nada", y mostrar eso porque el archivo caduco seria mentir.
 */
function siHayAlgo(partidos: Partido[]): Partido[] | null {
  return partidos.length ? partidos : null
}

export async function proximosDeLaInstantanea(liga?: string): Promise<Partido[] | null> {
  const datos = await cargar()
  return datos ? siHayAlgo(enLaVentana(datos.proximos, liga)) : null
}

export async function resultadosDeLaInstantanea(liga?: string): Promise<PaginaPartidos | null> {
  const datos = await cargar()
  if (!datos) return null
  const items = siHayAlgo(enLaVentana(datos.resultados, liga))
  // `total` es la cantidad real: la instantanea no pagina, y con la ventana
  // puesta entran de sobra en una pagina.
  return items ? { total: items.length, pagina: 1, por_pagina: 20, items } : null
}

export async function ligasDeLaInstantanea(): Promise<string[] | null> {
  const datos = await cargar()
  return datos?.ligas.length ? datos.ligas : null
}

/** Vacia el cache. Existe para que cada test arranque en limpio. */
export function reiniciarCacheDeInstantanea() {
  enCache = null
}
