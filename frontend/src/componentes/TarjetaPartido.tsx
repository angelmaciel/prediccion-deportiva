import { useState } from 'react'

import type { Partido } from '../tipos'
import { etiquetaResultado, formatearFechaHora, nivelDeConfianza } from '../formato'
import { BarraProbabilidades } from './BarraProbabilidades'
import { PanelH2H } from './PanelH2H'

function Escudo({ url, nombre }: { url: string | null; nombre: string }) {
  if (!url) {
    return (
      <span
        className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full
                   bg-pizarra-100 text-[10px] font-bold text-pizarra-600"
        aria-hidden="true"
      >
        {nombre.slice(0, 2).toUpperCase()}
      </span>
    )
  }
  return <img src={url} alt="" className="h-6 w-6 shrink-0 object-contain" aria-hidden="true" />
}

export function TarjetaPartido({ partido }: { partido: Partido }) {
  const { prediccion, equipo_local: local, equipo_visitante: visitante } = partido
  const finalizado = partido.estado === 'finalizado'
  const acerto =
    finalizado && prediccion ? prediccion.resultado_predicho === partido.resultado_real : null
  const [abierto, setAbierto] = useState(false)
  const idPanel = `h2h-${partido.id}`

  return (
    <article className="tarjeta">
      <header className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate text-xs font-medium text-pizarra-600">{partido.liga}</p>
          <p className="text-xs text-pizarra-400">
            {formatearFechaHora(partido.fecha)}
            {partido.jornada ? ` · Fecha ${partido.jornada}` : ''}
          </p>
        </div>
        {finalizado ? (
          <span className="etiqueta bg-pizarra-100 text-pizarra-600">Finalizado</span>
        ) : (
          <span className="etiqueta bg-cancha-50 text-cancha-700">Programado</span>
        )}
      </header>

      <div className="my-3 flex items-center justify-between gap-3">
        <div className="flex min-w-0 flex-1 items-center gap-2">
          <Escudo url={local.escudo_url} nombre={local.nombre} />
          <span className="truncate font-medium">{local.nombre}</span>
        </div>
        <div className="shrink-0 text-center font-bold tabular-nums">
          {finalizado ? (
            <span className="text-lg">
              {partido.goles_local} - {partido.goles_visitante}
            </span>
          ) : (
            <span className="text-sm text-pizarra-400">vs</span>
          )}
        </div>
        <div className="flex min-w-0 flex-1 items-center justify-end gap-2">
          <span className="truncate text-right font-medium">{visitante.nombre}</span>
          <Escudo url={visitante.escudo_url} nombre={visitante.nombre} />
        </div>
      </div>

      {prediccion ? (
        <div className="border-t border-pizarra-100 pt-3">
          <BarraProbabilidades
            probLocal={prediccion.prob_local}
            probEmpate={prediccion.prob_empate}
            probVisitante={prediccion.prob_visitante}
            nombreLocal={local.nombre_corto ?? local.nombre}
            nombreVisitante={visitante.nombre_corto ?? visitante.nombre}
          />
          <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-xs">
            <span className="text-pizarra-600">
              Escenario mas probable:{' '}
              <strong>{etiquetaResultado(prediccion.resultado_predicho)}</strong> ·{' '}
              {nivelDeConfianza(prediccion.confianza)}
            </span>
            {prediccion.marcador_probable_local !== null && (
              <span className="text-pizarra-400">
                Marcador modal (Poisson): {prediccion.marcador_probable_local}-
                {prediccion.marcador_probable_visitante}
              </span>
            )}
          </div>
          {acerto !== null && (
            <p className="mt-2 text-xs">
              {acerto ? (
                <span className="etiqueta bg-cancha-50 text-cancha-700">
                  El escenario mas probable se cumplio
                </span>
              ) : (
                <span className="etiqueta bg-rose-50 text-rose-700">
                  Ocurrio otro resultado: {etiquetaResultado(partido.resultado_real)}
                </span>
              )}
            </p>
          )}
        </div>
      ) : (
        <p className="border-t border-pizarra-100 pt-3 text-xs text-pizarra-400">
          Todavia no hay una estimacion para este partido.
        </p>
      )}

      <button
        type="button"
        onClick={() => setAbierto(!abierto)}
        aria-expanded={abierto}
        aria-controls={idPanel}
        className="mt-3 flex w-full items-center justify-center gap-1 rounded-lg
                   py-1.5 text-xs font-medium text-cancha-700 transition hover:bg-cancha-50"
      >
        {abierto ? 'Ocultar historial' : 'Ver historial entre estos equipos'}
        <span aria-hidden="true" className={abierto ? 'rotate-180' : undefined}>
          ▾
        </span>
      </button>

      {abierto && (
        <div id={idPanel}>
          <PanelH2H partido={partido} />
        </div>
      )}
    </article>
  )
}
