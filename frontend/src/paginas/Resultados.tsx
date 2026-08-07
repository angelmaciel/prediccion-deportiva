import { useState } from 'react'

import { api } from '../api'
import { Cargando, ErrorCarga, SinDatos } from '../componentes/Estado'
import { TarjetaPartido } from '../componentes/TarjetaPartido'
import { usePeticion } from '../hooks/usePeticion'

export default function Resultados() {
  const [liga, setLiga] = useState('')
  const [pagina, setPagina] = useState(1)

  const ligas = usePeticion(() => api.ligas(), [])
  const pagina_ = usePeticion(
    () => api.listarPartidos({ liga: liga || undefined, estado: 'finalizado', pagina }),
    [liga, pagina],
  )

  const totalPaginas = pagina_.datos
    ? Math.max(1, Math.ceil(pagina_.datos.total / pagina_.datos.por_pagina))
    : 1

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-bold">Resultados</h1>
        <p className="mt-1 text-sm text-pizarra-600">
          Partidos ya jugados, con la estimacion que el modelo habia emitido antes de que se
          disputaran.
        </p>
      </header>

      <div>
        <label htmlFor="filtro-liga-resultados" className="mb-1 block text-sm font-medium">
          Liga
        </label>
        <select
          id="filtro-liga-resultados"
          className="campo max-w-sm"
          value={liga}
          onChange={(e) => {
            setLiga(e.target.value)
            setPagina(1)
          }}
        >
          <option value="">Todas las ligas</option>
          {(ligas.datos ?? []).map((nombre) => (
            <option key={nombre} value={nombre}>
              {nombre}
            </option>
          ))}
        </select>
      </div>

      {pagina_.cargando && <Cargando />}
      {pagina_.error && <ErrorCarga mensaje={pagina_.error} />}
      {pagina_.datos?.items.length === 0 && <SinDatos texto="Todavia no hay resultados cargados." />}

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {(pagina_.datos?.items ?? []).map((partido) => (
          <TarjetaPartido key={partido.id} partido={partido} />
        ))}
      </div>

      {pagina_.datos && pagina_.datos.total > pagina_.datos.por_pagina && (
        <nav className="flex items-center justify-center gap-4" aria-label="Paginacion">
          <button
            className="boton disabled:opacity-40"
            onClick={() => setPagina((p) => Math.max(1, p - 1))}
            disabled={pagina <= 1}
          >
            Anterior
          </button>
          <span className="text-sm text-pizarra-600">
            Pagina {pagina} de {totalPaginas}
          </span>
          <button
            className="boton disabled:opacity-40"
            onClick={() => setPagina((p) => p + 1)}
            disabled={pagina >= totalPaginas}
          >
            Siguiente
          </button>
        </nav>
      )}
    </div>
  )
}
