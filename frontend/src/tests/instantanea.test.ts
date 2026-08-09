import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  ligasDeLaInstantanea,
  proximosDeLaInstantanea,
  reiniciarCacheDeInstantanea,
  resultadosDeLaInstantanea,
} from '../instantanea'

const DIA_MS = 86_400_000

function enDias(n: number): string {
  const ahora = new Date()
  const inicioDeHoy = Date.UTC(ahora.getUTCFullYear(), ahora.getUTCMonth(), ahora.getUTCDate())
  return new Date(inicioDeHoy + n * DIA_MS + 12 * 3600_000).toISOString()
}

function partido(id: number, fecha: string, liga = 'La Liga') {
  return { id, fecha, liga, estado: 'programado' }
}

function archivo(cuerpo: unknown, estado = 200) {
  return { ok: estado >= 200 && estado < 300, status: estado, json: async () => cuerpo } as Response
}

describe('instantanea estatica', () => {
  let fetchSimulado: ReturnType<typeof vi.fn>

  beforeEach(() => {
    fetchSimulado = vi.fn()
    vi.stubGlobal('fetch', fetchSimulado)
    reiniciarCacheDeInstantanea()
  })

  it('se pide sin credenciales para que la pueda cachear el CDN', async () => {
    fetchSimulado.mockResolvedValue(archivo({ proximos: [], resultados: [], ligas: [] }))
    await ligasDeLaInstantanea()

    const [, opciones] = fetchSimulado.mock.calls[0]
    expect(opciones.credentials).toBe('omit')
  })

  it('se baja una sola vez aunque la consulten varias secciones', async () => {
    fetchSimulado.mockResolvedValue(
      archivo({ proximos: [partido(1, enDias(0))], resultados: [], ligas: ['La Liga'] }),
    )

    await Promise.all([proximosDeLaInstantanea(), ligasDeLaInstantanea()])
    await resultadosDeLaInstantanea()
    expect(fetchSimulado).toHaveBeenCalledTimes(1)
  })

  it('recorta a la ventana de ayer, hoy y manana', async () => {
    fetchSimulado.mockResolvedValue(
      archivo({
        proximos: [partido(1, enDias(0)), partido(2, enDias(1)), partido(3, enDias(2))],
        resultados: [],
        ligas: [],
      }),
    )

    const partidos = await proximosDeLaInstantanea()
    expect(partidos?.map((p) => p.id)).toEqual([1, 2])
  })

  it('filtra por liga', async () => {
    fetchSimulado.mockResolvedValue(
      archivo({
        proximos: [partido(1, enDias(0), 'La Liga'), partido(2, enDias(0), 'Serie A')],
        resultados: [],
        ligas: [],
      }),
    )

    const partidos = await proximosDeLaInstantanea('Serie A')
    expect(partidos?.map((p) => p.id)).toEqual([2])
  })

  it('un archivo caducado devuelve null, no una lista vacia', async () => {
    // Vacio significaria "hoy no se juega nada" y taparia los partidos reales
    // que la API sí va a traer.
    fetchSimulado.mockResolvedValue(
      archivo({ proximos: [partido(1, enDias(-9))], resultados: [], ligas: [] }),
    )

    expect(await proximosDeLaInstantanea()).toBeNull()
  })

  it('si el archivo no existe no rompe', async () => {
    fetchSimulado.mockResolvedValue(archivo(null, 404))
    expect(await proximosDeLaInstantanea()).toBeNull()
  })

  it('descarta el index.html que devuelve el servidor estatico ante un 404', async () => {
    fetchSimulado.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => {
        throw new Error('no es JSON')
      },
    } as unknown as Response)

    expect(await proximosDeLaInstantanea()).toBeNull()
  })

  it('descarta una respuesta con forma inesperada', async () => {
    fetchSimulado.mockResolvedValue(archivo({ cualquier: 'cosa' }))
    expect(await ligasDeLaInstantanea()).toBeNull()
  })

  it('los resultados salen con forma de pagina', async () => {
    fetchSimulado.mockResolvedValue(
      archivo({ proximos: [], resultados: [partido(9, enDias(-1))], ligas: [] }),
    )

    const pagina = await resultadosDeLaInstantanea()
    expect(pagina).toMatchObject({ total: 1, pagina: 1, por_pagina: 20 })
    expect(pagina?.items.map((p) => p.id)).toEqual([9])
  })
})
