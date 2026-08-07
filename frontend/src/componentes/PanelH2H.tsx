// Detalle que se despliega al abrir una tarjeta, con tres vistas: el cara a
// cara y la racha reciente de cada equipo contra cualquier rival.
//
// Se pide al backend recien cuando el usuario despliega, no al renderizar la
// lista: con 28 tarjetas en pantalla serian 28 consultas que casi nadie mira.

import { useEffect, useState } from 'react'

import { api } from '../api'
import { formatearFecha } from '../formato'
import type { HistorialH2H, Partido, PromediosH2H, RachaEquipo } from '../tipos'
import { VistaNarrativa } from './VistaNarrativa'
import { VistaVeredicto } from './VistaVeredicto'

const FILAS: {
  clave: keyof PromediosH2H
  etiqueta: string
  estimado?: boolean
}[] = [
  { clave: 'goles_favor', etiqueta: 'Goles a favor' },
  { clave: 'goles_contra', etiqueta: 'Goles en contra' },
  { clave: 'remates', etiqueta: 'Remates' },
  { clave: 'remates_arco', etiqueta: 'Remates al arco' },
  { clave: 'corners', etiqueta: 'Corners' },
  { clave: 'atajadas', etiqueta: 'Atajadas', estimado: true },
  { clave: 'faltas', etiqueta: 'Faltas' },
  { clave: 'amarillas', etiqueta: 'Amarillas' },
  { clave: 'rojas', etiqueta: 'Rojas' },
]

const COLOR_RESULTADO: Record<string, string> = {
  G: 'bg-cancha-100 text-cancha-800',
  E: 'bg-pizarra-100 text-pizarra-600',
  P: 'bg-rose-100 text-rose-700',
}

const NOMBRE_RESULTADO: Record<string, string> = {
  G: 'Ganó',
  E: 'Empató',
  P: 'Perdió',
}

function Valor({ valor }: { valor: number | null }) {
  if (valor === null) {
    return (
      <span className="text-pizarra-300" title="La fuente no publica este dato">
        —
      </span>
    )
  }
  return <span className="tabular-nums">{valor.toFixed(2)}</span>
}

function Balance({ g, e, p }: { g: number; e: number; p: number }) {
  return (
    <span className="tabular-nums">
      <strong className="text-cancha-700">{g}</strong>
      <span className="text-pizarra-300">-</span>
      <strong className="text-pizarra-500">{e}</strong>
      <span className="text-pizarra-300">-</span>
      <strong className="text-rose-600">{p}</strong>
    </span>
  )
}

function TablaComparativa({
  izquierda,
  derecha,
  promediosIzquierda,
  promediosDerecha,
  aviso,
}: {
  izquierda: string
  derecha: string
  promediosIzquierda: PromediosH2H
  promediosDerecha: PromediosH2H
  aviso: string
}) {
  return (
    <table className="mt-3 w-full text-xs">
      <caption className="sr-only">Promedios por partido</caption>
      <thead>
        <tr className="text-pizarra-500">
          <th scope="col" className="py-1 text-right font-medium">
            {izquierda}
          </th>
          <th scope="col" className="py-1 text-center font-normal">
            promedio
          </th>
          <th scope="col" className="py-1 text-left font-medium">
            {derecha}
          </th>
        </tr>
      </thead>
      <tbody>
        {FILAS.map((fila) => (
          <tr key={fila.clave} className="border-t border-pizarra-50">
            <td className="py-1 text-right font-medium">
              <Valor valor={promediosIzquierda[fila.clave]} />
            </td>
            <td className="py-1 text-center text-pizarra-500">
              {fila.etiqueta}
              {fila.estimado && (
                <abbr title={aviso} className="ml-1 cursor-help text-pizarra-400 no-underline">
                  *
                </abbr>
              )}
            </td>
            <td className="py-1 text-left font-medium">
              <Valor valor={promediosDerecha[fila.clave]} />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function VistaRacha({ racha, aviso }: { racha: RachaEquipo; aviso: string }) {
  if (racha.jugados === 0) {
    return (
      <p className="mt-3 text-xs text-pizarra-500">
        No hay partidos previos de {racha.nombre} con esos filtros.
      </p>
    )
  }

  return (
    <>
      <p className="mt-3 flex flex-wrap items-center gap-2 text-xs text-pizarra-600">
        <span>
          Ultimos {racha.jugados}:{' '}
          <Balance g={racha.ganados} e={racha.empatados} p={racha.perdidos} />
        </span>
        <span className="flex gap-1" aria-hidden="true">
          {racha.partidos
            .slice(0, 10)
            .reverse()
            .map((p) => (
              <span
                key={p.partido_id}
                className={`flex h-5 w-5 items-center justify-center rounded text-[10px]
                            font-bold ${COLOR_RESULTADO[p.resultado]}`}
              >
                {p.resultado}
              </span>
            ))}
        </span>
      </p>

      <ul className="mt-3 space-y-1 text-xs">
        {racha.partidos.slice(0, 10).map((p) => (
          <li key={p.partido_id} className="flex items-baseline justify-between gap-2">
            <span className="min-w-0 truncate text-pizarra-600">
              <span className="text-pizarra-400">{formatearFecha(p.fecha)}</span>{' '}
              <span className="text-pizarra-400">{p.de_local ? '(L)' : '(V)'}</span> {p.rival}
            </span>
            <span className="shrink-0">
              <span className="font-medium tabular-nums">
                {p.goles_favor}-{p.goles_contra}
              </span>
              <span className="sr-only"> {NOMBRE_RESULTADO[p.resultado]}</span>
            </span>
          </li>
        ))}
      </ul>

      <table className="mt-3 w-full text-xs">
        <caption className="py-1 text-left text-pizarra-500">
          Promedios de {racha.nombre} por partido
          {racha.partidos_con_estadisticas < racha.jugados && (
            <span className="text-pizarra-400">
              {' '}
              (estadisticas en {racha.partidos_con_estadisticas} de {racha.jugados})
            </span>
          )}
        </caption>
        <tbody>
          {FILAS.map((fila) => (
            <tr key={fila.clave} className="border-t border-pizarra-50">
              <td className="py-1 text-pizarra-500">
                {fila.etiqueta}
                {fila.estimado && (
                  <abbr title={aviso} className="ml-1 cursor-help text-pizarra-400 no-underline">
                    *
                  </abbr>
                )}
              </td>
              <td className="py-1 text-right font-medium">
                <Valor valor={racha.promedios[fila.clave]} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  )
}

export function PanelH2H({ partido }: { partido: Partido }) {
  const [datos, setDatos] = useState<HistorialH2H | null>(null)
  const [cargando, setCargando] = useState(true)
  const [error, setError] = useState(false)
  const [vista, setVista] = useState<'veredicto' | 'analisis' | 'h2h' | 'local' | 'visitante'>(
    'veredicto',
  )
  const [soloMismaLocalia, setSoloMismaLocalia] = useState(false)
  const [soloEstaLiga, setSoloEstaLiga] = useState(false)

  useEffect(() => {
    let vigente = true
    setCargando(true)
    setError(false)
    api
      .h2h(partido.id, {
        solo_misma_localia: soloMismaLocalia,
        liga: soloEstaLiga ? partido.liga : undefined,
      })
      .then((r) => vigente && setDatos(r))
      .catch(() => vigente && setError(true))
      .finally(() => vigente && setCargando(false))
    return () => {
      // Evita que una respuesta vieja pise a una nueva si cambian los filtros rapido.
      vigente = false
    }
  }, [partido.id, partido.liga, soloMismaLocalia, soloEstaLiga])

  if (error) {
    return (
      <p className="mt-3 border-t border-pizarra-100 pt-3 text-xs text-rose-700">
        No se pudo cargar el historial.
      </p>
    )
  }

  const pestanas = [
    { id: 'veredicto' as const, texto: 'Veredicto' },
    { id: 'analisis' as const, texto: 'Analisis' },
    { id: 'h2h' as const, texto: 'Entre si' },
    {
      id: 'local' as const,
      texto: partido.equipo_local.nombre_corto ?? partido.equipo_local.nombre,
    },
    {
      id: 'visitante' as const,
      texto: partido.equipo_visitante.nombre_corto ?? partido.equipo_visitante.nombre,
    },
  ]

  return (
    <div className="mt-3 border-t border-pizarra-100 pt-3">
      <div className="flex gap-1" role="tablist" aria-label="Detalle del partido">
        {pestanas.map((pestana) => (
          <button
            key={pestana.id}
            type="button"
            role="tab"
            aria-selected={vista === pestana.id}
            onClick={() => setVista(pestana.id)}
            className={`rounded-lg px-2.5 py-1 text-xs font-medium transition ${
              vista === pestana.id
                ? 'bg-cancha-50 text-cancha-700'
                : 'text-pizarra-500 hover:bg-pizarra-50'
            }`}
          >
            {pestana.texto}
          </button>
        ))}
      </div>

      {/* Los filtros acotan el historial; el veredicto y el analisis no salen
          de esa consulta, asi que no aplican y se ocultan para no sugerir que si. */}
      {vista !== 'veredicto' && vista !== 'analisis' && (
        <div className="mt-2 flex flex-wrap gap-4 text-xs">
          <label className="flex items-center gap-1.5">
            <input
              type="checkbox"
              checked={soloMismaLocalia}
              onChange={(e) => setSoloMismaLocalia(e.target.checked)}
            />
            Solo con esta localia
          </label>
          <label className="flex items-center gap-1.5">
            <input
              type="checkbox"
              checked={soloEstaLiga}
              onChange={(e) => setSoloEstaLiga(e.target.checked)}
            />
            Solo {partido.liga}
          </label>
        </div>
      )}

      {vista === 'veredicto' ? (
        <VistaVeredicto partido={partido} />
      ) : vista === 'analisis' ? (
        <VistaNarrativa partido={partido} />
      ) : cargando && !datos ? (
        <p className="mt-3 text-xs text-pizarra-400">Cargando historial…</p>
      ) : !datos ? null : vista === 'local' ? (
        <VistaRacha racha={datos.racha_local} aviso={datos.aviso_atajadas} />
      ) : vista === 'visitante' ? (
        <VistaRacha racha={datos.racha_visitante} aviso={datos.aviso_atajadas} />
      ) : datos.total_cruces === 0 ? (
        <p className="mt-3 text-xs text-pizarra-500">
          No hay enfrentamientos previos entre estos equipos con esos filtros.
        </p>
      ) : (
        <>
          <p className="mt-3 text-xs text-pizarra-600">
            {datos.total_cruces} {datos.total_cruces === 1 ? 'cruce' : 'cruces'} ·{' '}
            <Balance g={datos.local.ganados} e={datos.local.empatados} p={datos.local.perdidos} />{' '}
            para {datos.local.nombre}
            {datos.cruces_con_estadisticas < datos.total_cruces && (
              <span className="text-pizarra-400">
                {' '}
                · estadisticas en {datos.cruces_con_estadisticas} de ellos
              </span>
            )}
          </p>

          <TablaComparativa
            izquierda={datos.local.nombre}
            derecha={datos.visitante.nombre}
            promediosIzquierda={datos.local.promedios}
            promediosDerecha={datos.visitante.promedios}
            aviso={datos.aviso_atajadas}
          />

          <ul className="mt-3 space-y-1 text-xs text-pizarra-600">
            {datos.cruces.slice(0, 8).map((cruce) => (
              <li key={cruce.partido_id} className="flex items-baseline justify-between gap-2">
                <span className="truncate">
                  <span className="text-pizarra-400">{formatearFecha(cruce.fecha)}</span>{' '}
                  {cruce.local} vs {cruce.visitante}
                </span>
                <span className="shrink-0 font-medium tabular-nums">
                  {cruce.goles_local}-{cruce.goles_visitante}
                </span>
              </li>
            ))}
          </ul>
        </>
      )}

      {datos && vista !== 'veredicto' && vista !== 'analisis' && (
        <p className="mt-3 text-[11px] text-pizarra-400">* {datos.aviso_atajadas}</p>
      )}
    </div>
  )
}
