/**
 * Interruptor para salir de la ventana de ayer/hoy/manana.
 *
 * Las vistas publicas cargan por defecto solo los partidos de la fecha, que es
 * lo que hace que abran rapido. Consultar el historico completo obliga al
 * backend a recorrer temporadas enteras, asi que se paga solo cuando alguien
 * lo pide explicitamente.
 */
export function InterruptorHistorico({
  id,
  activo,
  onCambio,
  etiqueta = 'Ver historico completo',
  ayuda = 'Por defecto se muestran solo los partidos de ayer, hoy y manana.',
}: {
  id: string
  activo: boolean
  onCambio: (activo: boolean) => void
  etiqueta?: string
  ayuda?: string
}) {
  return (
    <div>
      <label htmlFor={id} className="flex items-center gap-2 text-sm font-medium">
        <input
          id={id}
          type="checkbox"
          className="h-4 w-4 rounded border-pizarra-300 text-cancha-600 focus:ring-cancha-500"
          checked={activo}
          onChange={(e) => onCambio(e.target.checked)}
        />
        {etiqueta}
      </label>
      <p className="mt-1 text-xs text-pizarra-400">{ayuda}</p>
    </div>
  )
}
