import type { Dia } from '../dias'
import { DIAS } from '../dias'

/**
 * Selector de ayer / hoy / manana.
 *
 * No dispara peticiones: los tres dias ya vinieron en la misma respuesta, asi
 * que cambiar de dia es filtrar un array. Por eso los botones muestran el
 * conteo — el dato ya esta y esconderlo obligaria a probar dia por dia.
 */
export function FiltroDeDia({
  valor,
  onCambio,
  conteo,
}: {
  valor: Dia | null
  onCambio: (dia: Dia | null) => void
  conteo: Record<Dia, number>
}) {
  const opciones: { clave: Dia | null; etiqueta: string; cantidad: number | null }[] = [
    { clave: null, etiqueta: 'Todos', cantidad: null },
    ...DIAS.map((dia) => ({
      clave: dia.clave,
      etiqueta: dia.etiqueta,
      cantidad: conteo[dia.clave],
    })),
  ]

  return (
    <div role="group" aria-label="Filtrar por dia" className="flex flex-wrap gap-1">
      {opciones.map((opcion) => {
        const activo = valor === opcion.clave
        const vacio = opcion.cantidad === 0
        return (
          <button
            key={opcion.etiqueta}
            type="button"
            aria-pressed={activo}
            // Un dia sin partidos se deshabilita en vez de ocultarse: que "Ayer"
            // aparezca y desaparezca de la barra segun el dia mueve los demas
            // botones de lugar y se termina haciendo clic en el equivocado.
            disabled={vacio}
            onClick={() => onCambio(opcion.clave)}
            className={`rounded-lg px-3 py-1.5 text-sm font-medium transition ${
              activo
                ? 'bg-cancha-600 text-white'
                : 'bg-white text-pizarra-600 hover:bg-pizarra-100 disabled:opacity-40 disabled:hover:bg-white'
            }`}
          >
            {opcion.etiqueta}
            {opcion.cantidad !== null && (
              <span className={`ml-1.5 tabular-nums ${activo ? 'opacity-80' : 'text-pizarra-400'}`}>
                {opcion.cantidad}
              </span>
            )}
          </button>
        )
      })}
    </div>
  )
}
