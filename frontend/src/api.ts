// Cliente HTTP del backend propio.
//
// El frontend NUNCA llama a football-data.org ni a API-Football: todo pasa por
// nuestra API, que sirve datos ya cacheados en su base. Eso protege la cuota
// gratuita y evita exponer las claves en el navegador.
//
// La sesion viaja en una cookie HttpOnly, por eso todas las llamadas usan
// `credentials: 'include'` y no hay ningun token en localStorage.

import type {
  MetricaJornada,
  PaginaPartidos,
  Partido,
  Proveedores,
  ResumenModelo,
  Usuario,
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

async function pedir<T>(ruta: string, opciones: RequestInit = {}): Promise<T> {
  const respuesta = await fetch(`${BASE}${ruta}`, {
    ...opciones,
    credentials: 'include',
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

function query(params: Record<string, string | number | undefined>): string {
  const buscador = new URLSearchParams()
  for (const [clave, valor] of Object.entries(params)) {
    if (valor !== undefined && valor !== '') buscador.set(clave, String(valor))
  }
  const texto = buscador.toString()
  return texto ? `?${texto}` : ''
}

export const api = {
  proximosPartidos: (liga?: string, dias = 14) =>
    pedir<Partido[]>(`/partidos/proximos${query({ liga, dias })}`),

  listarPartidos: (params: { liga?: string; estado?: string; pagina?: number } = {}) =>
    pedir<PaginaPartidos>(`/partidos${query({ ...params, por_pagina: 20 })}`),

  detallePartido: (id: number) => pedir<Partido>(`/partidos/${id}`),

  ligas: () => pedir<string[]>('/partidos/ligas'),

  resumenModelo: (liga?: string) =>
    pedir<ResumenModelo>(`/transparencia/resumen${query({ liga })}`),

  metricasPorJornada: (liga?: string) =>
    pedir<MetricaJornada[]>(`/transparencia/jornadas${query({ liga })}`),

  versionesModelo: () => pedir<VersionModelo[]>('/transparencia/versiones'),

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
