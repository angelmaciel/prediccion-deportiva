import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '../api'
import { PanelH2H } from '../componentes/PanelH2H'
import { TarjetaPartido } from '../componentes/TarjetaPartido'
import type { HistorialH2H, Partido } from '../tipos'

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

const AVISO = 'Las atajadas son una estimacion: la fuente no las publica.'

const HISTORIAL: HistorialH2H = {
  partido_id: 10,
  solo_misma_localia: false,
  liga: null,
  total_cruces: 3,
  cruces_con_estadisticas: 2,
  local: {
    equipo_id: 1,
    nombre: 'Arsenal',
    jugados: 3,
    ganados: 2,
    empatados: 1,
    perdidos: 0,
    promedios: {
      goles_favor: 2.0,
      goles_contra: 0.67,
      remates: 15.5,
      remates_arco: 6.0,
      corners: 7.5,
      faltas: 9.0,
      amarillas: 1.5,
      rojas: 0,
      atajadas: 3.5,
    },
  },
  visitante: {
    equipo_id: 2,
    nombre: 'Chelsea',
    jugados: 3,
    ganados: 0,
    empatados: 1,
    perdidos: 2,
    promedios: {
      goles_favor: 0.67,
      goles_contra: 2.0,
      remates: null,
      remates_arco: null,
      corners: 4.0,
      faltas: 11.0,
      amarillas: 2.0,
      rojas: 0,
      atajadas: null,
    },
  },
  cruces: [
    {
      partido_id: 5,
      fecha: '2026-03-01T15:00:00Z',
      liga: 'Premier League',
      temporada: '25/26',
      local: 'Arsenal',
      visitante: 'Chelsea',
      goles_local: 3,
      goles_visitante: 1,
      tiene_estadisticas: true,
    },
  ],
  aviso_atajadas: AVISO,
}

describe('PanelH2H', () => {
  beforeEach(() => {
    vi.spyOn(api, 'h2h').mockResolvedValue(HISTORIAL)
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('muestra los promedios de cada equipo', async () => {
    render(<PanelH2H partido={PARTIDO} />)
    expect(await screen.findByText('Corners')).toBeInTheDocument()
    expect(screen.getByText('7.50')).toBeInTheDocument()
    expect(screen.getByText('4.00')).toBeInTheDocument()
    expect(screen.getByText('Remates al arco')).toBeInTheDocument()
  })

  it('no inventa ceros cuando la fuente no trae el dato', async () => {
    render(<PanelH2H partido={PARTIDO} />)
    await screen.findByText('Remates')
    // Chelsea no tiene remates ni remates al arco ni atajadas: tres guiones.
    expect(screen.getAllByTitle(/no publica este dato/i)).toHaveLength(3)
  })

  it('avisa que las atajadas son estimadas', async () => {
    render(<PanelH2H partido={PARTIDO} />)
    expect(await screen.findByText(new RegExp(AVISO, 'i'))).toBeInTheDocument()
  })

  it('aclara cuantos cruces tienen estadisticas', async () => {
    render(<PanelH2H partido={PARTIDO} />)
    expect(await screen.findByText(/estadisticas en 2 de ellos/i)).toBeInTheDocument()
  })

  it('vuelve a pedir el historial al filtrar por localia', async () => {
    const usuario = userEvent.setup()
    render(<PanelH2H partido={PARTIDO} />)
    await screen.findByText('Corners')

    await usuario.click(screen.getByLabelText(/solo con esta localia/i))

    await waitFor(() =>
      expect(api.h2h).toHaveBeenLastCalledWith(10, {
        solo_misma_localia: true,
        liga: undefined,
      }),
    )
  })

  it('vuelve a pedir el historial al filtrar por liga', async () => {
    const usuario = userEvent.setup()
    render(<PanelH2H partido={PARTIDO} />)
    await screen.findByText('Corners')

    await usuario.click(screen.getByLabelText(/solo premier league/i))

    await waitFor(() =>
      expect(api.h2h).toHaveBeenLastCalledWith(10, {
        solo_misma_localia: false,
        liga: 'Premier League',
      }),
    )
  })

  it('explica cuando no hay enfrentamientos previos', async () => {
    vi.spyOn(api, 'h2h').mockResolvedValue({
      ...HISTORIAL,
      total_cruces: 0,
      cruces: [],
    })
    render(<PanelH2H partido={PARTIDO} />)
    expect(await screen.findByText(/no hay enfrentamientos previos/i)).toBeInTheDocument()
  })

  it('avisa si la consulta falla', async () => {
    vi.spyOn(api, 'h2h').mockRejectedValue(new Error('sin red'))
    render(<PanelH2H partido={PARTIDO} />)
    expect(await screen.findByText(/no se pudo cargar el historial/i)).toBeInTheDocument()
  })
})

describe('TarjetaPartido con historial', () => {
  beforeEach(() => {
    vi.spyOn(api, 'h2h').mockResolvedValue(HISTORIAL)
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('no consulta el historial hasta que se despliega', () => {
    render(<TarjetaPartido partido={PARTIDO} />)
    expect(api.h2h).not.toHaveBeenCalled()
  })

  it('despliega el historial al hacer clic', async () => {
    const usuario = userEvent.setup()
    render(<TarjetaPartido partido={PARTIDO} />)

    const boton = screen.getByRole('button', { name: /ver historial/i })
    expect(boton).toHaveAttribute('aria-expanded', 'false')

    await usuario.click(boton)

    expect(await screen.findByText('Corners')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /ocultar historial/i })).toHaveAttribute(
      'aria-expanded',
      'true',
    )
  })
})
