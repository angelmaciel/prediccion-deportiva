import { useMemo, useState } from 'react'

import { api } from '../api'
import { AvisoModelo } from '../componentes/AvisoModelo'
import { Cargando, ErrorCarga, SinDatos } from '../componentes/Estado'
import { FiltroDeDia } from '../componentes/FiltroDeDia'
import { TarjetaPartido } from '../componentes/TarjetaPartido'
import type { Dia } from '../dias'
import { contarPorDia, filtrarPorDia } from '../dias'
import { usePeticion } from '../hooks/usePeticion'
import { ligasDeLaInstantanea, proximosDeLaInstantanea } from '../instantanea'

export default function Proximos() {
  const [liga, setLiga] = useState('')
  const [dia, setDia] = useState<Dia | null>(null)

  const ligas = usePeticion(() => api.ligas(), [], { respaldo: ligasDeLaInstantanea })
  const partidos = usePeticion(() => api.proximosPartidos(liga || undefined), [liga], {
    respaldo: () => proximosDeLaInstantanea(liga || undefined),
  })

  const todos = useMemo(() => partidos.datos ?? [], [partidos.datos])
  const conteo = useMemo(() => contarPorDia(todos), [todos])
  const visibles = useMemo(() => filtrarPorDia(todos, dia), [todos, dia])
  const enVivo = visibles.filter((partido) => partido.estado === 'en_juego').length

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-bold">Proximos partidos</h1>
        <p className="mt-1 text-sm text-pizarra-600">
          Estimaciones para los partidos de ayer, hoy y manana.
          {enVivo > 0 && (
            <>
              {' '}
              <strong className="text-rose-700">
                {enVivo} {enVivo === 1 ? 'partido' : 'partidos'} en juego ahora.
              </strong>
            </>
          )}
        </p>
      </header>

      <AvisoModelo />

      <div className="flex flex-wrap items-end gap-6">
        <div className="min-w-[16rem] flex-1">
          <label htmlFor="filtro-liga" className="mb-1 block text-sm font-medium">
            Liga
          </label>
          <select
            id="filtro-liga"
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

        <FiltroDeDia valor={dia} onCambio={setDia} conteo={conteo} />
      </div>

      {partidos.cargando && <Cargando texto="Cargando partidos…" />}
      {partidos.error && <ErrorCarga mensaje={partidos.error} />}
      {partidos.provisional && (
        <p className="text-xs text-pizarra-400">
          Mostrando la copia guardada del dia mientras se actualiza.
        </p>
      )}
      {partidos.datos && visibles.length === 0 && (
        <SinDatos
          texto={
            dia === null
              ? 'No hay partidos programados entre ayer y manana.'
              : 'No hay partidos programados ese dia.'
          }
        />
      )}

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {visibles.map((partido) => (
          <TarjetaPartido key={partido.id} partido={partido} />
        ))}
      </div>
    </div>
  )
}
