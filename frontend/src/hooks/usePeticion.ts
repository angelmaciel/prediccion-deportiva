import { useCallback, useEffect, useState } from 'react'

interface Estado<T> {
  datos: T | null
  cargando: boolean
  error: string | null
  /** Lo que se ve salio del respaldo y todavia puede cambiar cuando llegue la API. */
  provisional: boolean
}

interface Opciones<T> {
  /**
   * Fuente rapida que se consulta en paralelo con la principal. Devuelve null
   * cuando no tiene nada util que aportar.
   */
  respaldo?: () => Promise<T | null>
}

/**
 * Hook minimo para peticiones de solo lectura.
 *
 * Guarda contra respuestas fuera de orden: si el usuario cambia el filtro
 * mientras una peticion esta en vuelo, la respuesta vieja se descarta en lugar
 * de pisar a la nueva.
 *
 * Con `respaldo`, las dos fuentes arrancan a la vez y gana la que llegue
 * primero, con una regla: la principal siempre puede pisar al respaldo, pero el
 * respaldo nunca pisa a la principal. Asi la pantalla se dibuja con la copia
 * del CDN mientras el backend despierta, y se corrige sola cuando contesta.
 */
export function usePeticion<T>(
  peticion: () => Promise<T>,
  dependencias: unknown[] = [],
  opciones: Opciones<T> = {},
) {
  const [estado, setEstado] = useState<Estado<T>>({
    datos: null,
    cargando: true,
    error: null,
    provisional: false,
  })

  const { respaldo } = opciones
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const ejecutar = useCallback(peticion, dependencias)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const ejecutarRespaldo = useCallback(() => respaldo?.() ?? Promise.resolve(null), dependencias)

  useEffect(() => {
    let vigente = true
    let llegoLaPrincipal = false
    setEstado({ datos: null, cargando: true, error: null, provisional: false })

    ejecutarRespaldo()
      .then((datos) => {
        if (!vigente || llegoLaPrincipal || datos === null) return
        setEstado({ datos, cargando: false, error: null, provisional: true })
      })
      .catch(() => {
        // El respaldo es un extra: si falla, se sigue esperando a la principal.
      })

    ejecutar()
      .then((datos) => {
        if (!vigente) return
        llegoLaPrincipal = true
        setEstado({ datos, cargando: false, error: null, provisional: false })
      })
      .catch((error: unknown) => {
        if (!vigente) return
        llegoLaPrincipal = true
        const mensaje =
          error instanceof Error ? error.message : 'No se pudo conectar con el servidor'
        // Con datos del respaldo en pantalla, un fallo de la API no borra lo que
        // el usuario ya esta leyendo: se queda lo provisional y no se muestra
        // un error sobre una pantalla que en realidad tiene contenido.
        setEstado((previo) =>
          previo.provisional && previo.datos !== null
            ? previo
            : { datos: null, cargando: false, error: mensaje, provisional: false },
        )
      })

    return () => {
      vigente = false
    }
  }, [ejecutar, ejecutarRespaldo])

  return estado
}
