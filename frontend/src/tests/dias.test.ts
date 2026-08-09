import { describe, expect, it } from 'vitest'

import { contarPorDia, diaDe, filtrarPorDia } from '../dias'
import type { Partido } from '../tipos'

function partido(id: number, fechaIso: string): Partido {
  return { id, fecha: fechaIso, estado: 'programado' } as unknown as Partido
}

// Asuncion esta en UTC-3, asi que las 21:00 locales del 9 son las 00:00 UTC del 10.
const AHORA = new Date('2026-08-09T18:00:00Z') // 15:00 en Asuncion, 9 de agosto

describe('reparto en ayer / hoy / manana', () => {
  it('usa la zona del publico y no UTC', () => {
    // Este es el caso que importa: un partido de las 21:00 del 9 en Asuncion ya
    // figura como 10 de agosto en UTC. Para el hincha es hoy, no manana.
    expect(diaDe(partido(1, '2026-08-10T00:00:00Z'), AHORA)).toBe('hoy')
  })

  it('ubica ayer, hoy y manana', () => {
    expect(diaDe(partido(1, '2026-08-08T20:00:00Z'), AHORA)).toBe('ayer')
    expect(diaDe(partido(2, '2026-08-09T18:00:00Z'), AHORA)).toBe('hoy')
    expect(diaDe(partido(3, '2026-08-10T18:00:00Z'), AHORA)).toBe('manana')
  })

  it('lo que cae fuera de la ventana no pertenece a ningun dia', () => {
    expect(diaDe(partido(1, '2026-08-01T18:00:00Z'), AHORA)).toBeNull()
    expect(diaDe(partido(2, '2026-08-20T18:00:00Z'), AHORA)).toBeNull()
  })

  it('una fecha invalida no rompe', () => {
    expect(diaDe(partido(1, 'no-es-fecha'), AHORA)).toBeNull()
  })

  it('sin dia elegido no filtra nada', () => {
    const lista = [partido(1, '2026-08-09T18:00:00Z'), partido(2, '2026-08-01T18:00:00Z')]
    expect(filtrarPorDia(lista, null)).toHaveLength(2)
  })

  it('cuenta por dia', () => {
    const hoy = new Date()
    const dia = 86_400_000
    const conteo = contarPorDia([
      partido(1, hoy.toISOString()),
      partido(2, hoy.toISOString()),
      partido(3, new Date(hoy.getTime() + dia).toISOString()),
    ])
    expect(conteo.hoy + conteo.manana + conteo.ayer).toBe(3)
  })
})
