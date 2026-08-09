// Cliente HTTP del backend propio.
//
// El frontend NUNCA llama a football-data.org ni a API-Football: todo pasa por
// nuestra API, que sirve datos ya cacheados en su base. Eso protege la cuota
// gratuita y evita exponer las claves en el navegador.
//
// Hay dos formas de pedir, y la diferencia es de rendimiento, no de estilo:
//
// - `pedirPublico` para partidos y transparencia. Va sin cookie a proposito.
//   Una respuesta atada a credenciales no la puede guardar ninguna cache
//   compartida, y estas son identicas para todos los visitantes: mandarles la
//   cookie tiraba a la basura el `Cache-Control` que devuelve el backend.
// - `pedir` para lo que sí depende de quien mira (sesion y panel de admin).
//   Esa sesion viaja en cookie HttpOnly, nunca en localStorage.

import type {
  HistorialH2H,
  MetricaJornada,
  Narrativa,
  PaginaPartidos,
  Partido,
  Proveedores,
  ResumenModelo,
  Usuario,
  Veredicto,
  VersionModelo,
} from './tipos'

const BASE = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

export class ErrorApi extends Error {
  constructor(
    public readonly estado: number,
    mensaje: string,
  ) {
    super(mensaje)
    this.name = 'ErrorApi'
  }
}

async function llamar<T>(
  ruta: string,
  credentials: RequestCredentials,
  opciones: RequestInit = {},
): Promise<T> {
  const respuesta = await fetch(`${BASE}${ruta}`, {
    ...opciones,
    credentials,
    headers: {
      'Content-Type': 'application/json',
      ...opciones.headers,
    },
  })

  if (!respuesta.ok) {
    // El backend responde mensajes genericos a proposito; se muestran tal cual.
    let detalle = `Error ${respuesta.status}`
    try {
      const cuerpo = await respuesta.json()
      if (typeof cuerpo?.detail === 'string') detalle = cuerpo.detail
    } catch {
      // respuesta sin JSON: se conserva el mensaje por defecto
    }
    throw new ErrorApi(respuesta.status, detalle)
  }

  if (respuesta.status === 204) return undefined as T
  return (await respuesta.json()) as T
}

/** Lectura publica: cacheable por el navegador y por cualquier capa intermedia. */
const pedirPublico = <T,>(ruta: string) => llamar<T>(ruta, 'omit')

/** Llamada que depende de la sesion. */
const pedir = <T,>(ruta: string, opciones: RequestInit = {}) =>
  llamar<T>(ruta, 'include', opciones)

function query(params: Record<string, string | number | boolean | undefined>): string {
  const buscador = new URLSearchParams()
  for (const [clave, valor] of Object.entries(params)) {
    // `false` se omite: los flags booleanos del backend ya tienen ese default,
    // y mandarlos vacia la URL de ruido.
    if (valor === undefined || valor === '' || valor === false) continue
    buscador.set(clave, String(valor))
  }
  const texto = buscador.toString()
  return texto ? `?${texto}` : ''
}

let ligasEnCache: Promise<string[]> | null = null

/** Vacia el cache de ligas. Existe para que cada test arranque en limpio. */
export function reiniciarCacheDeLigas() {
  ligasEnCache = null
}

export const api = {
  // `dias` son dias alrededor de hoy: 1 = ayer, hoy y manana.
  proximosPartidos: (liga?: string, dias = 1) =>
    pedirPublico<Partido[]>(`/partidos/proximos${query({ liga, dias })}`),

  // Sin `historico` el backend acota a ayer/hoy/manana. Es el default a
  // proposito: es lo que mira casi todo el mundo y es lo que carga rapido.
  listarPartidos: (
    params: { liga?: string; estado?: string; pagina?: number; historico?: boolean } = {},
  ) => pedirPublico<PaginaPartidos>(`/partidos${query({ ...params, por_pagina: 20 })}`),

  detallePartido: (id: number) => pedirPublico<Partido>(`/partidos/${id}`),

  narrativa: (id: number) => pedirPublico<Narrativa>(`/partidos/${id}/narrativa`),

  veredicto: (id: number) => pedirPublico<Veredicto>(`/partidos/${id}/veredicto`),

  h2h: (id: number, opciones: { solo_misma_localia?: boolean; liga?: string } = {}) =>
    pedirPublico<HistorialH2H>(
      `/partidos/${id}/h2h${query({
        solo_misma_localia: opciones.solo_misma_localia ? 'true' : undefined,
        liga: opciones.liga,
      })}`,
    ),

  // El listado de ligas es el mismo en las tres paginas y cambia una vez por
  // temporada, pero cada `usePeticion` lo volvia a pedir en cada navegacion.
  // Se cachea la promesa (no el resultado) para que dos componentes que montan
  // a la vez compartan una sola peticion en lugar de disparar dos.
  ligas: () => {
    ligasEnCache ??= pedirPublico<string[]>('/partidos/ligas').catch((error) => {
      ligasEnCache = null // un fallo no se cachea: el proximo intento reintenta
      throw error
    })
    return ligasEnCache
  },

  resumenModelo: (liga?: string, historico = false) =>
    pedirPublico<ResumenModelo>(`/transparencia/resumen${query({ liga, historico })}`),

  metricasPorJornada: (liga?: string, historico = false) =>
    pedirPublico<MetricaJornada[]>(`/transparencia/jornadas${query({ liga, historico })}`),

  versionesModelo: () => pedirPublico<VersionModelo[]>('/transparencia/versiones'),

  yo: () => pedir<Usuario>('/auth/yo'),

  proveedores: () => pedir<Proveedores>('/auth/proveedores'),

  // No es un fetch: el ingreso con Google es una navegacion de la pestana
  // entera, porque el rodeo pasa por accounts.google.com y vuelve con la
  // cookie ya puesta por el backend.
  irAGoogle: () => {
    window.location.href = `${BASE}/auth/google/inicio`
  },

  login: (email: string, password: string, codigo_totp?: string) =>
    pedir<Usuario>('/auth/login', {
      method: 'POST',
      body: JSON.stringify(codigo_totp ? { email, password, codigo_totp } : { email, password }),
    }),

  registro: (email: string, password: string) =>
    pedir<Usuario>('/auth/registro', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    }),

  logout: () => pedir<{ mensaje: string }>('/auth/logout', { method: 'POST' }),
}
