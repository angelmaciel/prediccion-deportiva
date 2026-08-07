// Veredicto del partido: la lectura unica que sale de cruzar los dos modelos.
//
// El copy es deliberadamente analitico. Este proyecto no recomienda apostar:
// muestra que escenario es mas probable y con cuanta incertidumbre.

import { useEffect, useState } from 'react'

import { api } from '../api'
import { porcentaje } from '../formato'
import type { Escenario, Partido, Veredicto } from '../tipos'

const COLOR_CONFIANZA: Record<string, string> = {
  alta: 'bg-cancha-100 text-cancha-800',
  media: 'bg-amber-100 text-amber-800',
  baja: 'bg-pizarra-100 text-pizarra-600',
}

// Mismos colores que la barra de probabilidades: verde el local, celeste el
// visitante. Que el mismo equipo cambie de color entre secciones confunde.
const COLOR_FAVORECE: Record<string, string> = {
  L: 'text-cancha-700',
  V: 'text-sky-700',
  '-': 'text-pizarra-400',
}

function Barra({ valor }: { valor: number }) {
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-pizarra-100">
      <div
        className="h-full rounded-full bg-cancha-500"
        style={{ width: `${Math.round(valor * 100)}%` }}
      />
    </div>
  )
}

function ListaEscenarios({
  titulo,
  escenarios,
  explicacion,
}: {
  titulo: string
  escenarios: Escenario[]
  explicacion?: string
}) {
  if (escenarios.length === 0) return null
  return (
    <section className="mt-4">
      <h4 className="text-xs font-semibold text-pizarra-700">{titulo}</h4>
      {explicacion && <p className="mt-0.5 text-[11px] text-pizarra-500">{explicacion}</p>}
      <ul className="mt-2 space-y-2">
        {escenarios.map((escenario) => (
          <li key={escenario.claves.join('+')}>
            <div className="flex items-baseline justify-between gap-2 text-xs">
              <span className="min-w-0 truncate text-pizarra-700">{escenario.etiqueta}</span>
              <span className="shrink-0 font-semibold tabular-nums">
                {porcentaje(escenario.probabilidad)}
              </span>
            </div>
            <Barra valor={escenario.probabilidad} />
            {escenario.correlacion !== null && Math.abs(escenario.correlacion) >= 0.01 && (
              <p className="mt-0.5 text-[11px] text-pizarra-400">
                Multiplicando cada parte por separado daria{' '}
                {porcentaje(escenario.probabilidad_ingenua ?? 0)} (
                {escenario.correlacion > 0 ? '+' : ''}
                {porcentaje(escenario.correlacion)} de correlacion)
              </p>
            )}
          </li>
        ))}
      </ul>
    </section>
  )
}

export function VistaVeredicto({ partido }: { partido: Partido }) {
  const [datos, setDatos] = useState<Veredicto | null>(null)
  const [estado, setEstado] = useState<'cargando' | 'listo' | 'error'>('cargando')

  useEffect(() => {
    let vigente = true
    api
      .veredicto(partido.id)
      .then((r) => {
        if (!vigente) return
        setDatos(r)
        setEstado('listo')
      })
      .catch(() => vigente && setEstado('error'))
    return () => {
      vigente = false
    }
  }, [partido.id])

  if (estado === 'cargando') {
    return <p className="mt-3 text-xs text-pizarra-400">Calculando veredicto…</p>
  }
  if (estado === 'error' || !datos) {
    return (
      <p className="mt-3 text-xs text-pizarra-500">
        Todavia no hay un veredicto para este partido: hace falta un modelo entrenado y las
        features calculadas.
      </p>
    )
  }

  return (
    <div className="mt-3">
      <div className="rounded-lg bg-pizarra-50 p-3">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <strong className="text-sm">{datos.etiqueta}</strong>
          <span className="flex items-center gap-2">
            <span className="text-sm font-bold tabular-nums">
              {porcentaje(datos.probabilidad)}
            </span>
            <span className={`etiqueta ${COLOR_CONFIANZA[datos.confianza]}`}>
              confianza {datos.confianza}
            </span>
          </span>
        </div>

        <p className="mt-2 text-[11px] text-pizarra-600">
          {datos.consenso ? (
            <>Los dos modelos coinciden en el resultado.</>
          ) : (
            <>
              <strong>Los modelos no coinciden.</strong> La logistica y el Poisson apuntan a
              resultados distintos, asi que la confianza baja un escalon.
            </>
          )}
        </p>

        <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-[11px] text-pizarra-600">
          <dt>Logistica (L/E/V)</dt>
          <dd className="text-right tabular-nums">
            {datos.prob_logistica.map((p) => porcentaje(p, 0)).join(' · ')}
          </dd>
          <dt>Poisson (L/E/V)</dt>
          <dd className="text-right tabular-nums">
            {datos.prob_poisson.map((p) => porcentaje(p, 0)).join(' · ')}
          </dd>
          {datos.marcador_probable && (
            <>
              <dt>Marcador mas probable</dt>
              <dd className="text-right tabular-nums">
                {datos.marcador_probable[0]}-{datos.marcador_probable[1]} (
                {porcentaje(datos.prob_marcador_probable ?? 0)})
              </dd>
            </>
          )}
        </dl>
      </div>

      {datos.factores.length > 0 && (
        <section className="mt-4">
          <h4 className="text-xs font-semibold text-pizarra-700">Que lo empuja</h4>
          <ul className="mt-2 space-y-1 text-xs">
            {datos.factores.map((factor) => (
              <li key={factor.nombre} className="flex justify-between gap-2">
                <span className="text-pizarra-500">{factor.nombre}</span>
                <span className={`text-right ${COLOR_FAVORECE[factor.favorece]}`}>
                  {factor.detalle}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {datos.senales.length > 0 && (
        <section className="mt-4">
          <h4 className="text-xs font-semibold text-pizarra-700">Analisis propio</h4>
          <p className="mt-0.5 text-[11px] text-pizarra-500">
            Reglas escritas a mano. No mueven las probabilidades del modelo: se leen al lado.
          </p>
          <ul className="mt-2 space-y-1 text-xs">
            {datos.senales.map((senial) => (
              <li key={senial.nombre} className="flex justify-between gap-2">
                <span className="text-pizarra-500">{senial.nombre}</span>
                <span className={`text-right ${COLOR_FAVORECE[senial.favorece]}`}>
                  {senial.detalle}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}

      <ListaEscenarios titulo="Escenarios simples" escenarios={datos.escenarios_simples} />

      <ListaEscenarios
        titulo="Escenarios combinados"
        escenarios={datos.escenarios_combinados}
        explicacion="Probabilidad de que se cumplan las dos cosas a la vez, calculada sobre la matriz de marcadores."
      />

      <p className="mt-4 text-[11px] text-pizarra-400">{datos.aviso}</p>
    </div>
  )
}
