// Formateo para el locale es-PY.

const FORMATO_FECHA = new Intl.DateTimeFormat('es-PY', {
  weekday: 'short',
  day: '2-digit',
  month: 'short',
  hour: '2-digit',
  minute: '2-digit',
  timeZone: 'America/Asuncion',
})

const FORMATO_FECHA_CORTA = new Intl.DateTimeFormat('es-PY', {
  day: '2-digit',
  month: '2-digit',
  year: 'numeric',
  timeZone: 'America/Asuncion',
})

export function formatearFechaHora(iso: string): string {
  const fecha = new Date(iso)
  if (Number.isNaN(fecha.getTime())) return 'Fecha no disponible'
  return FORMATO_FECHA.format(fecha)
}

export function formatearFecha(iso: string | null): string {
  if (!iso) return '—'
  const fecha = new Date(iso)
  if (Number.isNaN(fecha.getTime())) return '—'
  return FORMATO_FECHA_CORTA.format(fecha)
}

export function porcentaje(valor: number | null | undefined, decimales = 1): string {
  if (valor === null || valor === undefined || Number.isNaN(valor)) return '—'
  return `${(valor * 100).toFixed(decimales)} %`
}

export const ETIQUETA_RESULTADO: Record<string, string> = {
  L: 'Gana local',
  E: 'Empate',
  V: 'Gana visitante',
}

export function etiquetaResultado(codigo: string | null): string {
  if (!codigo) return '—'
  return ETIQUETA_RESULTADO[codigo] ?? codigo
}

/**
 * Traduce la confianza del modelo a lenguaje llano.
 *
 * Deliberadamente evita palabras como "seguro" o "garantizado": las
 * probabilidades son estimaciones, y el texto no debe sugerir lo contrario.
 */
export function nivelDeConfianza(valor: number): string {
  if (valor >= 0.6) return 'Tendencia marcada'
  if (valor >= 0.45) return 'Tendencia leve'
  return 'Partido parejo'
}
