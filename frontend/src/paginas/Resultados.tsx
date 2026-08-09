import { useMemo, useState } from 'react'

import { api } from '../api'
import { Cargando, ErrorCarga, SinDatos } from '../componentes/Estado'
import { FiltroDeDia } from '../componentes/FiltroDeDia'
import { InterruptorHistorico } from '../componentes/InterruptorHistorico'
import { TarjetaPartido } from '../componentes/TarjetaPartido'
import type { Dia } from '../dias'
import { contarPorDia, filtrarPorDia } from '../dias'
import { usePeticion } from '../hooks/usePeticion'
import { ligasDeLaInstantanea, resultadosDeLaInstantanea } from '../instantanea'

export default function Resultados() {
  const [liga, setLiga] = useState('')
  const [historico, setHistorico] = useState(false)
  const [dia, setDia] = useState<Dia | null>(null)
  const [pagina, setPagina] = useState(1)

  const ligas = usePeticion(() => api.ligas(), [], { respaldo: ligasDeLaInstantanea })
  const pagina_ = usePeticion(
    () =>
      api.listarPartidos({ liga: liga || undefined, estado: 'finalizado', pagina, historico }),
    [liga, pagina, historico],
    {
      // La instantanea solo cubre la primera pagina de la ventana; el historico
      // y las paginas siguientes salen siempre de la API.
      respaldo: () =>
        historico || pagina !== 1
          ? Promise.resolve(null)
          : resultadosDeLaInstantanea(liga || undefined),
    },
  )

  const items = useMemo(() => pagina_.datos?.items ?? [], [pagina_.datos])
  const conteo = useMemo(() => contarPorDia(items), [items])
  // En historico el filtro no aplica: son partidos de temporadas enteras y
  // casi ninguno cae en ayer/hoy/manana.
  const visibles = useMemo(
    () => (historico ? items : filtrarPorDia(items, dia)),
    [items, dia, historico],
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
          disputaran. {historico ? 'Mostrando todo el historico.' : 'Mostrando ayer y hoy.'}
        </p>
      </header>

      <div className="flex flex-wrap items-start gap-6">
        <div className="min-w-[16rem] flex-1">
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

        {!historico && <FiltroDeDia valor={dia} onCambio={setDia} conteo={conteo} />}

        <InterruptorHistorico
          id="historico-resultados"
          activo={historico}
          onCambio={(valor) => {
            setHistorico(valor)
            setDia(null)
            setPagina(1)
          }}
          ayuda="Por defecto se muestran solo los partidos de ayer y hoy. El historico completo tarda mas en cargar."
        />
      </div>

      {pagina_.cargando && <Cargando />}
      {pagina_.error && <ErrorCarga mensaje={pagina_.error} />}
      {pagina_.datos && visibles.length === 0 && (
        <SinDatos
          texto={
            historico
              ? 'Todavia no hay resultados cargados.'
              : 'No hay partidos finalizados entre ayer y hoy. Activa el historico para ver los anteriores.'
          }
        />
      )}

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {visibles.map((partido) => (
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
