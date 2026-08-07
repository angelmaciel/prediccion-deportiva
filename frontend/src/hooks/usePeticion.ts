import { useCallback, useEffect, useState } from 'react'

interface Estado<T> {
  datos: T | null
  cargando: boolean
  error: string | null
}

/**
 * Hook minimo para peticiones de solo lectura.
 *
 * Guarda contra respuestas fuera de orden: si el usuario cambia el filtro
 * mientras una peticion esta en vuelo, la respuesta vieja se descarta en lugar
 * de pisar a la nueva.
 */
export function usePeticion<T>(peticion: () => Promise<T>, dependencias: unknown[] = []) {
  const [estado, setEstado] = useState<Estado<T>>({ datos: null, cargando: true, error: null })

  // eslint-disable-next-line react-hooks/exhaustive-deps
  const ejecutar = useCallback(peticion, dependencias)

  useEffect(() => {
    let vigente = true
    setEstado((previo) => ({ ...previo, cargando: true, error: null }))

    ejecutar()
      .then((datos) => {
        if (vigente) setEstado({ datos, cargando: false, error: null })
      })
      .catch((error: unknown) => {
        if (!vigente) return
        const mensaje =
          error instanceof Error ? error.message : 'No se pudo conectar con el servidor'
        setEstado({ datos: null, cargando: false, error: mensaje })
      })

    return () => {
      vigente = false
    }
  }, [ejecutar])

  return estado
}
