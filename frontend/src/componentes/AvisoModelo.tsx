/**
 * Aviso permanente sobre la naturaleza de las predicciones.
 *
 * Requisito de producto: el proyecto es analitico. No se usa lenguaje que
 * sugiera certeza ni que incentive apostar dinero, y no hay enlaces a casas de
 * apuestas en ninguna parte de la aplicacion.
 */
export function AvisoModelo({ compacto = false }: { compacto?: boolean }) {
  if (compacto) {
    return (
      <p className="text-xs text-pizarra-600">
        Estimaciones estadisticas sobre datos historicos. No son garantias de resultado.
      </p>
    )
  }

  return (
    <aside
      className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900"
      role="note"
    >
      <p className="font-semibold">Como leer estos numeros</p>
      <p className="mt-1">
        Las probabilidades que se muestran son <strong>estimaciones estadisticas</strong> calculadas
        a partir de datos historicos. No son garantias ni pronosticos certeros: un partido con
        70&nbsp;% estimado para el local igual se pierde muchas veces.
      </p>
      <p className="mt-2">
        Este es un proyecto de analisis de datos. No gestiona dinero, no intermedia apuestas y no
        redirige a casas de apuestas.
      </p>
    </aside>
  )
}
