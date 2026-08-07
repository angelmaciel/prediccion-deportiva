// Panel de enfrentamientos directos que se despliega al abrir una tarjeta.
//
// Se pide al backend recien cuando el usuario despliega, no al renderizar la
// lista: con 28 tarjetas en pantalla serian 28 consultas que casi nadie mira.

import { useEffect, useState } from 'react'

import { api } from '../api'
import { formatearFecha } from '../formato'
import type { HistorialH2H, Partido, PromediosH2H } from '../tipos'

const FILAS: { clave: keyof PromediosH2H; etiqueta: string; estimado?: boolean }[] = [
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

export function PanelH2H({ partido }: { partido: Partido }) {
  const [datos, setDatos] = useState<HistorialH2H | null>(null)
  const [cargando, setCargando] = useState(true)
  const [error, setError] = useState(false)
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

  return (
    <div className="mt-3 border-t border-pizarra-100 pt-3">
      <div className="flex flex-wrap gap-4 text-xs">
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

      {cargando && !datos ? (
        <p className="mt-3 text-xs text-pizarra-400">Cargando historial…</p>
      ) : !datos || datos.total_cruces === 0 ? (
        <p className="mt-3 text-xs text-pizarra-500">
          No hay enfrentamientos previos entre estos equipos con esos filtros.
        </p>
      ) : (
        <>
          <p className="mt-3 text-xs text-pizarra-600">
            {datos.total_cruces} {datos.total_cruces === 1 ? 'cruce' : 'cruces'} ·{' '}
            <strong>{datos.local.ganados}</strong>-<strong>{datos.local.empatados}</strong>-
            <strong>{datos.local.perdidos}</strong> para {datos.local.nombre}
            {datos.cruces_con_estadisticas < datos.total_cruces && (
              <span className="text-pizarra-400">
                {' '}
                · estadisticas en {datos.cruces_con_estadisticas} de ellos
              </span>
            )}
          </p>

          <table className="mt-3 w-full text-xs">
            <caption className="sr-only">
              Promedios por partido en los enfrentamientos directos
            </caption>
            <thead>
              <tr className="text-pizarra-500">
                <th scope="col" className="py-1 text-right font-medium">
                  {datos.local.nombre}
                </th>
                <th scope="col" className="py-1 text-center font-normal">
                  promedio
                </th>
                <th scope="col" className="py-1 text-left font-medium">
                  {datos.visitante.nombre}
                </th>
              </tr>
            </thead>
            <tbody>
              {FILAS.map((fila) => (
                <tr key={fila.clave} className="border-t border-pizarra-50">
                  <td className="py-1 text-right font-medium">
                    <Valor valor={datos.local.promedios[fila.clave]} />
                  </td>
                  <td className="py-1 text-center text-pizarra-500">
                    {fila.etiqueta}
                    {fila.estimado && (
                      <abbr
                        title={datos.aviso_atajadas}
                        className="ml-1 cursor-help text-pizarra-400 no-underline"
                      >
                        *
                      </abbr>
                    )}
                  </td>
                  <td className="py-1 text-left font-medium">
                    <Valor valor={datos.visitante.promedios[fila.clave]} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

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

          <p className="mt-3 text-[11px] text-pizarra-400">* {datos.aviso_atajadas}</p>
        </>
      )}
    </div>
  )
}
