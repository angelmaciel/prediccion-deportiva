import { render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '../api'
import { VistaVeredicto } from '../componentes/VistaVeredicto'
import type { Partido, Veredicto } from '../tipos'

const EQUIPO = (id: number, nombre: string) => ({
  id,
  nombre,
  nombre_corto: nombre.slice(0, 3).toUpperCase(),
  liga: 'Premier League',
  pais: 'Inglaterra',
  escudo_url: null,
})

const PARTIDO: Partido = {
  id: 10,
  fecha: '2026-09-01T15:00:00Z',
  liga: 'Premier League',
  temporada: '26/27',
  jornada: 3,
  estado: 'programado',
  equipo_local: EQUIPO(1, 'Arsenal'),
  equipo_visitante: EQUIPO(2, 'Chelsea'),
  goles_local: null,
  goles_visitante: null,
  resultado_real: null,
  prediccion: null,
}

const VEREDICTO: Veredicto = {
  partido_id: 10,
  resultado: 'L',
  etiqueta: 'Gana el local',
  probabilidad: 0.472,
  confianza: 'media',
  consenso: true,
  prob_logistica: [0.48, 0.3, 0.22],
  prob_poisson: [0.464, 0.28, 0.256],
  marcador_probable: [1, 1],
  prob_marcador_probable: 0.11,
  factores: [
    { nombre: 'Elo', detalle: '1612 contra 1498 (+114 para el local)', favorece: 'L' },
    { nombre: 'Historial directo', detalle: '1-1-1 en 3 cruces', favorece: '-' },
  ],
  escenarios_simples: [
    {
      claves: ['mas_1_5'],
      etiqueta: 'Mas de 1.5 goles',
      probabilidad: 0.81,
      probabilidad_ingenua: null,
      correlacion: null,
    },
  ],
  escenarios_combinados: [
    {
      claves: ['local', 'mas_2_5'],
      etiqueta: 'Gana el local + Mas de 2.5 goles',
      probabilidad: 0.31,
      probabilidad_ingenua: 0.24,
      correlacion: 0.07,
    },
  ],
  aviso: 'Un veredicto no es un pronostico ni una recomendacion.',
}

describe('VistaVeredicto', () => {
  beforeEach(() => {
    vi.spyOn(api, 'veredicto').mockResolvedValue(VEREDICTO)
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('muestra el resultado, su probabilidad y la confianza', async () => {
    render(<VistaVeredicto partido={PARTIDO} />)
    expect(await screen.findByText('Gana el local')).toBeInTheDocument()
    expect(screen.getByText('47.2 %')).toBeInTheDocument()
    expect(screen.getByText(/confianza media/i)).toBeInTheDocument()
  })

  it('avisa cuando los modelos coinciden', async () => {
    render(<VistaVeredicto partido={PARTIDO} />)
    expect(await screen.findByText(/los dos modelos coinciden/i)).toBeInTheDocument()
  })

  it('destaca la discrepancia entre modelos', async () => {
    vi.spyOn(api, 'veredicto').mockResolvedValue({
      ...VEREDICTO,
      consenso: false,
      confianza: 'baja',
    })
    render(<VistaVeredicto partido={PARTIDO} />)
    expect(await screen.findByText(/los modelos no coinciden/i)).toBeInTheDocument()
  })

  it('lista los factores que empujan el partido', async () => {
    render(<VistaVeredicto partido={PARTIDO} />)
    expect(await screen.findByText('Elo')).toBeInTheDocument()
    expect(screen.getByText(/\+114 para el local/)).toBeInTheDocument()
  })

  it('compara la combinada contra multiplicar cada parte', async () => {
    render(<VistaVeredicto partido={PARTIDO} />)
    expect(await screen.findByText('Gana el local + Mas de 2.5 goles')).toBeInTheDocument()
    expect(screen.getByText(/multiplicando cada parte por separado/i)).toHaveTextContent(
      '24.0 %',
    )
  })

  it('no muestra la comparacion en los escenarios simples', async () => {
    render(<VistaVeredicto partido={PARTIDO} />)
    await screen.findByText('Mas de 1.5 goles')
    // Solo la combinada trae `correlacion`, asi que la aclaracion aparece una vez.
    expect(screen.getAllByText(/multiplicando cada parte por separado/i)).toHaveLength(1)
  })

  it('deja claro que no es una recomendacion', async () => {
    render(<VistaVeredicto partido={PARTIDO} />)
    expect(await screen.findByText(/no es un pronostico ni una recomendacion/i)).toBeInTheDocument()
  })

  it('explica cuando todavia no hay veredicto', async () => {
    vi.spyOn(api, 'veredicto').mockRejectedValue(new Error('sin modelo'))
    render(<VistaVeredicto partido={PARTIDO} />)
    expect(await screen.findByText(/todavia no hay un veredicto/i)).toBeInTheDocument()
  })
})
