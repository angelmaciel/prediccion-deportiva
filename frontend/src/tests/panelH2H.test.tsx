import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '../api'
import { PanelH2H } from '../componentes/PanelH2H'
import { TarjetaPartido } from '../componentes/TarjetaPartido'
import type { HistorialH2H, Partido, Veredicto } from '../tipos'

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
  racha_local: {
    equipo_id: 1,
    nombre: 'Arsenal',
    jugados: 3,
    ganados: 2,
    empatados: 0,
    perdidos: 1,
    partidos_con_estadisticas: 3,
    promedios: {
      goles_favor: 1.67,
      goles_contra: 1.0,
      remates: 14.0,
      remates_arco: 5.0,
      corners: 6.0,
      faltas: 10.0,
      amarillas: 1.0,
      rojas: 0,
      atajadas: 3.0,
    },
    partidos: [
      {
        partido_id: 21,
        fecha: '2026-08-20T15:00:00Z',
        liga: 'Premier League',
        temporada: '26/27',
        rival: 'Everton',
        de_local: true,
        goles_favor: 2,
        goles_contra: 0,
        resultado: 'G',
        tiene_estadisticas: true,
      },
      {
        partido_id: 22,
        fecha: '2026-08-13T15:00:00Z',
        liga: 'Premier League',
        temporada: '26/27',
        rival: 'Fulham',
        de_local: false,
        goles_favor: 1,
        goles_contra: 3,
        resultado: 'P',
        tiene_estadisticas: true,
      },
    ],
  },
  racha_visitante: {
    equipo_id: 2,
    nombre: 'Chelsea',
    jugados: 0,
    ganados: 0,
    empatados: 0,
    perdidos: 0,
    partidos_con_estadisticas: 0,
    promedios: {
      goles_favor: null,
      goles_contra: null,
      remates: null,
      remates_arco: null,
      corners: null,
      faltas: null,
      amarillas: null,
      rojas: null,
      atajadas: null,
    },
    partidos: [],
  },
  aviso_atajadas: AVISO,
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
    { nombre: 'Forma reciente', detalle: '10 contra 4 puntos en los ultimos 5', favorece: 'L' },
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
  senales: [
    {
      nombre: 'Presion ofensiva',
      detalle: '6.1 contra 3.4 remates al arco por partido',
      favorece: 'L',
      peso: 0.7,
    },
  ],
  aviso: 'Un veredicto no es un pronostico ni una recomendacion.',
}

/** El panel abre en "Veredicto"; el historial vive en las otras pestanas. */
async function verHistorial(usuario: ReturnType<typeof userEvent.setup>) {
  await usuario.click(await screen.findByRole('tab', { name: 'Entre si' }))
}

describe('PanelH2H', () => {
  beforeEach(() => {
    vi.spyOn(api, 'h2h').mockResolvedValue(HISTORIAL)
    vi.spyOn(api, 'veredicto').mockResolvedValue(VEREDICTO)
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('muestra los promedios de cada equipo', async () => {
    const usuario = userEvent.setup()
    render(<PanelH2H partido={PARTIDO} />)
    await verHistorial(usuario)
    expect(await screen.findByText('Corners')).toBeInTheDocument()
    expect(screen.getByText('7.50')).toBeInTheDocument()
    expect(screen.getByText('4.00')).toBeInTheDocument()
    expect(screen.getByText('Remates al arco')).toBeInTheDocument()
  })

  it('no inventa ceros cuando la fuente no trae el dato', async () => {
    const usuario = userEvent.setup()
    render(<PanelH2H partido={PARTIDO} />)
    await verHistorial(usuario)
    await screen.findByText('Remates')
    // Chelsea no tiene remates ni remates al arco ni atajadas: tres guiones.
    expect(screen.getAllByTitle(/no publica este dato/i)).toHaveLength(3)
  })

  it('avisa que las atajadas son estimadas', async () => {
    const usuario = userEvent.setup()
    render(<PanelH2H partido={PARTIDO} />)
    await verHistorial(usuario)
    expect(await screen.findByText(new RegExp(AVISO, 'i'))).toBeInTheDocument()
  })

  it('aclara cuantos cruces tienen estadisticas', async () => {
    const usuario = userEvent.setup()
    render(<PanelH2H partido={PARTIDO} />)
    await verHistorial(usuario)
    expect(await screen.findByText(/estadisticas en 2 de ellos/i)).toBeInTheDocument()
  })

  it('vuelve a pedir el historial al filtrar por localia', async () => {
    const usuario = userEvent.setup()
    render(<PanelH2H partido={PARTIDO} />)
    await verHistorial(usuario)
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
    await verHistorial(usuario)
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
    const usuario = userEvent.setup()
    vi.spyOn(api, 'h2h').mockResolvedValue({
      ...HISTORIAL,
      total_cruces: 0,
      cruces: [],
    })
    render(<PanelH2H partido={PARTIDO} />)
    await verHistorial(usuario)
    expect(await screen.findByText(/no hay enfrentamientos previos/i)).toBeInTheDocument()
  })

  it('avisa si la consulta falla', async () => {
    const usuario = userEvent.setup()
    vi.spyOn(api, 'h2h').mockRejectedValue(new Error('sin red'))
    render(<PanelH2H partido={PARTIDO} />)
    await verHistorial(usuario)
    expect(await screen.findByText(/no se pudo cargar el historial/i)).toBeInTheDocument()
  })
})

describe('PanelH2H: racha de cada equipo', () => {
  beforeEach(() => {
    vi.spyOn(api, 'h2h').mockResolvedValue(HISTORIAL)
    vi.spyOn(api, 'veredicto').mockResolvedValue(VEREDICTO)
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('arranca mostrando el veredicto', async () => {
    render(<PanelH2H partido={PARTIDO} />)
    expect(await screen.findByText('Gana el local')).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Veredicto' })).toHaveAttribute('aria-selected', 'true')
  })

  it('muestra los partidos contra otros rivales al cambiar de pestana', async () => {
    const usuario = userEvent.setup()
    render(<PanelH2H partido={PARTIDO} />)
    await usuario.click(await screen.findByRole('tab', { name: 'ARS' }))

    expect(await screen.findByText(/everton/i)).toBeInTheDocument()
    expect(screen.getByText(/fulham/i)).toBeInTheDocument()
    expect(screen.getByText(/promedios de arsenal/i)).toBeInTheDocument()
  })

  it('distingue si el equipo jugo de local o de visitante', async () => {
    const usuario = userEvent.setup()
    render(<PanelH2H partido={PARTIDO} />)
    await usuario.click(await screen.findByRole('tab', { name: 'ARS' }))

    // Everton fue de local y Fulham de visitante. La marca (L)/(V) vive en un
    // span aparte, asi que se mira el texto de la fila entera.
    expect((await screen.findByText(/everton/i)).closest('li')).toHaveTextContent('(L) Everton')
    expect(screen.getByText(/fulham/i).closest('li')).toHaveTextContent('(V) Fulham')
  })

  it('explica cuando el equipo no tiene partidos previos', async () => {
    const usuario = userEvent.setup()
    render(<PanelH2H partido={PARTIDO} />)
    await usuario.click(await screen.findByRole('tab', { name: 'CHE' }))

    expect(await screen.findByText(/no hay partidos previos de chelsea/i)).toBeInTheDocument()
  })
})

describe('TarjetaPartido con historial', () => {
  beforeEach(() => {
    vi.spyOn(api, 'h2h').mockResolvedValue(HISTORIAL)
    vi.spyOn(api, 'veredicto').mockResolvedValue(VEREDICTO)
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

    expect(await screen.findByRole('tab', { name: 'Veredicto' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /ocultar historial/i })).toHaveAttribute(
      'aria-expanded',
      'true',
    )
  })
})
