import { useState } from 'react'

import { api } from '../api'
import { AvisoModelo } from '../componentes/AvisoModelo'
import { Cargando, ErrorCarga, SinDatos } from '../componentes/Estado'
import { TarjetaPartido } from '../componentes/TarjetaPartido'
import { usePeticion } from '../hooks/usePeticion'
import { ligasDeLaInstantanea, proximosDeLaInstantanea } from '../instantanea'

export default function Proximos() {
  const [liga, setLiga] = useState('')

  const ligas = usePeticion(() => api.ligas(), [], { respaldo: ligasDeLaInstantanea })
  const partidos = usePeticion(() => api.proximosPartidos(liga || undefined), [liga], {
    respaldo: () => proximosDeLaInstantanea(liga || undefined),
  })

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-bold">Proximos partidos</h1>
        <p className="mt-1 text-sm text-pizarra-600">
          Estimaciones para los partidos de ayer, hoy y manana.
        </p>
      </header>

      <AvisoModelo />

      <div>
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

      {partidos.cargando && <Cargando texto="Cargando partidos…" />}
      {partidos.error && <ErrorCarga mensaje={partidos.error} />}
      {partidos.provisional && (
        <p className="text-xs text-pizarra-400">
          Mostrando la copia guardada del dia mientras se actualiza.
        </p>
      )}
      {partidos.datos && partidos.datos.length === 0 && (
        <SinDatos texto="No hay partidos programados entre ayer y manana." />
      )}

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {(partidos.datos ?? []).map((partido) => (
          <TarjetaPartido key={partido.id} partido={partido} />
        ))}
      </div>
    </div>
  )
}
