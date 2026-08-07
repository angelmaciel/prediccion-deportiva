export function Cargando({ texto = 'Cargando…' }: { texto?: string }) {
  return (
    <p className="py-8 text-center text-sm text-pizarra-400" role="status" aria-live="polite">
      {texto}
    </p>
  )
}

export function ErrorCarga({ mensaje }: { mensaje: string }) {
  return (
    <p
      className="rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800"
      role="alert"
    >
      {mensaje}
    </p>
  )
}

export function SinDatos({ texto }: { texto: string }) {
  return <p className="py-8 text-center text-sm text-pizarra-400">{texto}</p>
}
