import { useState } from 'react'

import { api } from '../api'
import { AvisoModelo } from '../componentes/AvisoModelo'
import { Cargando, ErrorCarga, SinDatos } from '../componentes/Estado'
import { InterruptorHistorico } from '../componentes/InterruptorHistorico'
import { formatearFecha, porcentaje } from '../formato'
import { usePeticion } from '../hooks/usePeticion'
import type { MetricaJornada } from '../tipos'

function Metrica({ titulo, valor, detalle }: { titulo: string; valor: string; detalle?: string }) {
  return (
    <div className="tarjeta">
      <p className="text-xs font-medium uppercase tracking-wide text-pizarra-400">{titulo}</p>
      <p className="mt-1 text-2xl font-bold tabular-nums">{valor}</p>
      {detalle && <p className="mt-1 text-xs text-pizarra-600">{detalle}</p>}
    </div>
  )
}

/** Grafico de barras por jornada, dibujado con divs (sin dependencias extra). */
function GraficoJornadas({ metricas }: { metricas: MetricaJornada[] }) {
  return (
    <div>
      <div className="flex h-40 items-end gap-1 overflow-x-auto border-b border-pizarra-200 pb-1">
        {metricas.map((m) => {
          const alto = Math.max(2, Math.round(m.accuracy * 100))
          return (
            <div
              key={`${m.liga}-${m.temporada}-${m.jornada}-${m.modelo_version}`}
              className="flex min-w-[14px] flex-1 flex-col justify-end"
              title={
                `Fecha ${m.jornada ?? '—'}: ${m.aciertos} de ${m.partidos_evaluados} ` +
                `(${porcentaje(m.accuracy)})`
              }
            >
              <div
                className={`rounded-t ${m.accuracy >= 0.5 ? 'bg-cancha-600' : 'bg-pizarra-400'}`}
                style={{ height: `${alto}%` }}
              />
            </div>
          )
        })}
      </div>
      <p className="mt-2 text-xs text-pizarra-400">
        Cada barra es una fecha. Altura = porcentaje de aciertos sobre los partidos evaluados.
      </p>
    </div>
  )
}

export default function Transparencia() {
  const [liga, setLiga] = useState('')
  const [historico, setHistorico] = useState(false)

  const ligas = usePeticion(() => api.ligas(), [])
  const resumen = usePeticion(
    () => api.resumenModelo(liga || undefined, historico),
    [liga, historico],
  )
  const jornadas = usePeticion(
    () => api.metricasPorJornada(liga || undefined, historico),
    [liga, historico],
  )
  const versiones = usePeticion(() => api.versionesModelo(), [])

  const r = resumen.datos

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-bold">Historial de aciertos</h1>
        <p className="mt-1 text-sm text-pizarra-600">
          Todo lo que el modelo predijo, evaluado contra lo que realmente paso. Sin recortes ni
          promedios convenientes.
        </p>
      </header>

      <AvisoModelo />

      <div className="flex flex-wrap items-start gap-6">
        <div className="min-w-[16rem] flex-1">
          <label htmlFor="filtro-liga-transparencia" className="mb-1 block text-sm font-medium">
            Liga
          </label>
          <select
            id="filtro-liga-transparencia"
            className="campo max-w-sm"
            value={liga}
            onChange={(e) => setLiga(e.target.value)}
          >
            <option value="">Todas las ligas</option>
            {(ligas.datos ?? []).map((nombre) => (
              <option key={nombre} value={nombre}>
                {nombre}
              </option>
            ))}
          </select>
        </div>

        <InterruptorHistorico
          id="historico-transparencia"
          activo={historico}
          onCambio={setHistorico}
          ayuda="Por defecto se evaluan solo los partidos de ayer y hoy. El historico completo es la medida representativa, pero tarda mas en calcularse."
        />
      </div>

      {!historico && (
        <p className="rounded-lg border border-pizarra-200 bg-white px-4 py-3 text-sm text-pizarra-600">
          Estos numeros salen de una muestra de dos dias, asi que se mueven mucho de un dia al
          otro. Para juzgar al modelo hay que mirar el{' '}
          <button
            type="button"
            className="font-medium text-cancha-700 underline"
            onClick={() => setHistorico(true)}
          >
            historico completo
          </button>
          .
        </p>
      )}

      {resumen.cargando && <Cargando />}
      {resumen.error && <ErrorCarga mensaje={resumen.error} />}

      {r && (
        <>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Metrica
              titulo="Aciertos reales"
              valor={porcentaje(r.accuracy_real)}
              detalle={`${r.aciertos} de ${r.partidos_evaluados} partidos evaluados`}
            />
            <Metrica
              titulo="Linea base"
              valor={porcentaje(r.linea_base_local)}
              detalle="Acertar siempre 'gana el local'"
            />
            <Metrica
              titulo="Accuracy walk-forward"
              valor={porcentaje(r.accuracy_walk_forward)}
              detalle="Medida en validacion temporal al entrenar"
            />
            <Metrica
              titulo="Brier score"
              valor={r.brier !== null ? r.brier.toFixed(3) : '—'}
              detalle="Calidad de calibracion (0 = perfecto)"
            />
          </div>

          <div className="tarjeta">
            <h2 className="font-semibold">Como se compara con la linea base</h2>
            <p className="mt-2 text-sm text-pizarra-600">
              {r.partidos_evaluados === 0 ? (
                'Todavia no hay partidos evaluados para esta seleccion.'
              ) : r.accuracy_real > r.linea_base_local ? (
                <>
                  El modelo acierta{' '}
                  <strong>{porcentaje(r.accuracy_real - r.linea_base_local)} mas</strong> que la
                  heuristica trivial de asumir siempre victoria local. La diferencia es chica en
                  terminos absolutos: el futbol es un deporte de baja predictibilidad.
                </>
              ) : (
                <>
                  En esta seleccion el modelo <strong>no supera</strong> a la heuristica de asumir
                  siempre victoria local. Se muestra igual porque ocultarlo seria justamente lo
                  contrario de la idea de esta seccion.
                </>
              )}
            </p>
          </div>
        </>
      )}

      <section className="tarjeta">
        <h2 className="font-semibold">Aciertos por fecha</h2>
        {jornadas.cargando && <Cargando />}
        {jornadas.error && <ErrorCarga mensaje={jornadas.error} />}
        {jornadas.datos && jornadas.datos.length === 0 && (
          <SinDatos
            texto={
              historico
                ? 'Todavia no hay fechas evaluadas.'
                : 'No hay fechas evaluadas entre ayer y hoy. Activa el historico para ver las anteriores.'
            }
          />
        )}
        {jornadas.datos && jornadas.datos.length > 0 && (
          <>
            <div className="mt-4">
              <GraficoJornadas metricas={jornadas.datos} />
            </div>
            <div className="mt-4 overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="border-b border-pizarra-200 text-xs uppercase text-pizarra-400">
                  <tr>
                    <th scope="col" className="py-2 pr-4">
                      Liga
                    </th>
                    <th scope="col" className="py-2 pr-4">
                      Fecha
                    </th>
                    <th scope="col" className="py-2 pr-4">
                      Evaluados
                    </th>
                    <th scope="col" className="py-2 pr-4">
                      Aciertos
                    </th>
                    <th scope="col" className="py-2">
                      Precision
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {jornadas.datos.map((m) => (
                    <tr
                      key={`${m.liga}-${m.temporada}-${m.jornada}-${m.modelo_version}`}
                      className="border-b border-pizarra-100"
                    >
                      <td className="py-2 pr-4">{m.liga}</td>
                      <td className="py-2 pr-4 tabular-nums">{m.jornada ?? '—'}</td>
                      <td className="py-2 pr-4 tabular-nums">{m.partidos_evaluados}</td>
                      <td className="py-2 pr-4 tabular-nums">{m.aciertos}</td>
                      <td className="py-2 tabular-nums">{porcentaje(m.accuracy)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </section>

      <section className="tarjeta">
        <h2 className="font-semibold">Versiones del modelo</h2>
        <p className="mt-1 text-sm text-pizarra-600">
          Cada reentrenamiento queda registrado con las metricas que obtuvo en validacion
          walk-forward.
        </p>
        {versiones.datos && versiones.datos.length === 0 && (
          <SinDatos texto="Todavia no se entreno ningun modelo." />
        )}
        {versiones.datos && versiones.datos.length > 0 && (
          <div className="mt-4 overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-pizarra-200 text-xs uppercase text-pizarra-400">
                <tr>
                  <th scope="col" className="py-2 pr-4">
                    Version
                  </th>
                  <th scope="col" className="py-2 pr-4">
                    Algoritmo
                  </th>
                  <th scope="col" className="py-2 pr-4">
                    Entrenada
                  </th>
                  <th scope="col" className="py-2 pr-4">
                    Partidos
                  </th>
                  <th scope="col" className="py-2 pr-4">
                    Accuracy
                  </th>
                  <th scope="col" className="py-2">
                    Estado
                  </th>
                </tr>
              </thead>
              <tbody>
                {versiones.datos.map((v) => (
                  <tr key={v.version} className="border-b border-pizarra-100">
                    <td className="py-2 pr-4 font-mono text-xs">{v.version}</td>
                    <td className="py-2 pr-4">{v.algoritmo}</td>
                    <td className="py-2 pr-4">{formatearFecha(v.entrenado_en)}</td>
                    <td className="py-2 pr-4 tabular-nums">{v.partidos_entrenamiento}</td>
                    <td className="py-2 pr-4 tabular-nums">{porcentaje(v.accuracy)}</td>
                    <td className="py-2">
                      {v.activa ? (
                        <span className="etiqueta bg-cancha-50 text-cancha-700">Activa</span>
                      ) : (
                        <span className="etiqueta bg-pizarra-100 text-pizarra-600">Historica</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="tarjeta">
        <h2 className="font-semibold">Como se miden estos numeros</h2>
        <ul className="mt-2 space-y-2 text-sm text-pizarra-600">
          <li>
            <strong>Validacion walk-forward:</strong> el modelo se entrena siempre con partidos
            anteriores a los que evalua. Nunca se usa un split aleatorio, porque eso permitiria
            entrenar con partidos del futuro y produciria un accuracy inflado que no se sostiene en
            produccion.
          </li>
          <li>
            <strong>Aciertos reales:</strong> se compara la prediccion emitida <em>antes</em> del
            partido contra el resultado final. Las predicciones historicas se generan con el mismo
            protocolo walk-forward, no con el modelo actual.
          </li>
          <li>
            <strong>Brier score:</strong> mide que tan bien calibradas estan las probabilidades, no
            solo si el escenario mas probable se cumplio. Un modelo que dice 55&nbsp;% y acierta el
            55&nbsp;% de las veces esta bien calibrado.
          </li>
          <li>
            <strong>Linea base:</strong> asumir siempre victoria local acierta alrededor del
            45&nbsp;% en la mayoria de las ligas. Cualquier modelo tiene que superarla para
            justificar su existencia.
          </li>
        </ul>
      </section>
    </div>
  )
}
