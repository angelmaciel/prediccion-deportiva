import { porcentaje } from '../formato'

interface Props {
  probLocal: number
  probEmpate: number
  probVisitante: number
  nombreLocal: string
  nombreVisitante: string
}

/**
 * Barra apilada con las tres probabilidades.
 *
 * Se muestran siempre las tres, no solo la mas alta: presentar un unico
 * resultado "el que va a pasar" daria una idea de certeza que el modelo no
 * tiene. El texto y los aria-label refuerzan que son estimaciones.
 */
export function BarraProbabilidades({
  probLocal,
  probEmpate,
  probVisitante,
  nombreLocal,
  nombreVisitante,
}: Props) {
  const segmentos = [
    { clave: 'L', valor: probLocal, color: 'bg-cancha-600', etiqueta: nombreLocal },
    { clave: 'E', valor: probEmpate, color: 'bg-pizarra-400', etiqueta: 'Empate' },
    { clave: 'V', valor: probVisitante, color: 'bg-sky-600', etiqueta: nombreVisitante },
  ]

  return (
    <div>
      <div
        className="flex h-3 w-full overflow-hidden rounded-full bg-pizarra-100"
        role="img"
        aria-label={
          `Probabilidades estimadas: ${nombreLocal} ${porcentaje(probLocal)}, ` +
          `empate ${porcentaje(probEmpate)}, ${nombreVisitante} ${porcentaje(probVisitante)}`
        }
      >
        {segmentos.map((s) => (
          <div
            key={s.clave}
            className={s.color}
            style={{ width: `${Math.max(0, Math.min(1, s.valor)) * 100}%` }}
          />
        ))}
      </div>
      <dl className="mt-2 grid grid-cols-3 gap-2 text-center text-xs">
        {segmentos.map((s) => (
          <div key={s.clave}>
            <dt className="truncate text-pizarra-600">{s.etiqueta}</dt>
            <dd className="font-semibold tabular-nums">{porcentaje(s.valor)}</dd>
          </div>
        ))}
      </dl>
    </div>
  )
}
