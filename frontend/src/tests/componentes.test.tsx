import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { AvisoModelo } from '../componentes/AvisoModelo'
import { BarraProbabilidades } from '../componentes/BarraProbabilidades'
import { TarjetaPartido } from '../componentes/TarjetaPartido'
import type { Partido } from '../tipos'

const EQUIPO_LOCAL = {
  id: 1,
  nombre: 'Olimpia',
  nombre_corto: 'OLI',
  liga: 'Primera Division de Paraguay',
  pais: 'Paraguay',
  escudo_url: null,
}

const EQUIPO_VISITANTE = {
  id: 2,
  nombre: 'Cerro Porteno',
  nombre_corto: 'CER',
  liga: 'Primera Division de Paraguay',
  pais: 'Paraguay',
  escudo_url: null,
}

const PARTIDO_PROGRAMADO: Partido = {
  id: 10,
  fecha: '2026-09-01T23:00:00Z',
  liga: 'Primera Division de Paraguay',
  temporada: '2026',
  jornada: 12,
  estado: 'programado',
  equipo_local: EQUIPO_LOCAL,
  equipo_visitante: EQUIPO_VISITANTE,
  goles_local: null,
  goles_visitante: null,
  resultado_real: null,
  prediccion: {
    prob_local: 0.52,
    prob_empate: 0.26,
    prob_visitante: 0.22,
    marcador_probable_local: 1,
    marcador_probable_visitante: 0,
    modelo_version: 'v20260807T0300',
    resultado_predicho: 'L',
    confianza: 0.52,
    creado_en: '2026-08-30T10:00:00Z',
  },
}

describe('BarraProbabilidades', () => {
  it('muestra las tres probabilidades, no solo la mas alta', () => {
    render(
      <BarraProbabilidades
        probLocal={0.52}
        probEmpate={0.26}
        probVisitante={0.22}
        nombreLocal="Olimpia"
        nombreVisitante="Cerro Porteno"
      />,
    )
    expect(screen.getByText('52.0 %')).toBeInTheDocument()
    expect(screen.getByText('26.0 %')).toBeInTheDocument()
    expect(screen.getByText('22.0 %')).toBeInTheDocument()
  })

  it('expone una descripcion accesible del grafico', () => {
    render(
      <BarraProbabilidades
        probLocal={0.52}
        probEmpate={0.26}
        probVisitante={0.22}
        nombreLocal="Olimpia"
        nombreVisitante="Cerro Porteno"
      />,
    )
    const grafico = screen.getByRole('img')
    expect(grafico).toHaveAccessibleName(/probabilidades estimadas/i)
  })
})

describe('AvisoModelo', () => {
  it('aclara que las predicciones no son garantias', () => {
    render(<AvisoModelo />)
    expect(screen.getByText(/no son garantias/i)).toBeInTheDocument()
  })

  it('deja claro que no se intermedian apuestas', () => {
    render(<AvisoModelo />)
    expect(screen.getByText(/no intermedia apuestas/i)).toBeInTheDocument()
  })

  it('la version compacta tambien lleva la aclaracion', () => {
    render(<AvisoModelo compacto />)
    expect(screen.getByText(/no son garantias/i)).toBeInTheDocument()
  })
})

describe('TarjetaPartido', () => {
  it('muestra los equipos y la liga', () => {
    render(<TarjetaPartido partido={PARTIDO_PROGRAMADO} />)
    expect(screen.getByText('Olimpia')).toBeInTheDocument()
    expect(screen.getByText('Cerro Porteno')).toBeInTheDocument()
    expect(screen.getByText('Primera Division de Paraguay')).toBeInTheDocument()
  })

  it('describe el escenario mas probable sin afirmar certeza', () => {
    render(<TarjetaPartido partido={PARTIDO_PROGRAMADO} />)
    expect(screen.getByText(/escenario mas probable/i)).toBeInTheDocument()
    expect(screen.queryByText(/va a ganar|resultado asegurado/i)).not.toBeInTheDocument()
  })

  it('avisa cuando el partido no tiene estimacion', () => {
    render(<TarjetaPartido partido={{ ...PARTIDO_PROGRAMADO, prediccion: null }} />)
    expect(screen.getByText(/todavia no hay una estimacion/i)).toBeInTheDocument()
  })

  it('muestra el marcador cuando el partido termino', () => {
    render(
      <TarjetaPartido
        partido={{
          ...PARTIDO_PROGRAMADO,
          estado: 'finalizado',
          goles_local: 2,
          goles_visitante: 1,
          resultado_real: 'L',
        }}
      />,
    )
    expect(screen.getByText('2 - 1')).toBeInTheDocument()
    expect(screen.getByText('Finalizado')).toBeInTheDocument()
  })

  it('marca si el escenario mas probable se cumplio', () => {
    render(
      <TarjetaPartido
        partido={{
          ...PARTIDO_PROGRAMADO,
          estado: 'finalizado',
          goles_local: 2,
          goles_visitante: 1,
          resultado_real: 'L',
        }}
      />,
    )
    expect(screen.getByText(/se cumplio/i)).toBeInTheDocument()
  })

  it('reconoce el fallo cuando ocurrio otro resultado', () => {
    render(
      <TarjetaPartido
        partido={{
          ...PARTIDO_PROGRAMADO,
          estado: 'finalizado',
          goles_local: 0,
          goles_visitante: 3,
          resultado_real: 'V',
        }}
      />,
    )
    expect(screen.getByText(/ocurrio otro resultado/i)).toBeInTheDocument()
  })
})
