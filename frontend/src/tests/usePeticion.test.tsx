import { act, renderHook, waitFor } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { usePeticion } from '../hooks/usePeticion'

/** Promesa que se resuelve o rechaza cuando el test lo decide. */
function diferida<T>() {
  let resolver!: (valor: T) => void
  let rechazar!: (error: unknown) => void
  const promesa = new Promise<T>((si, no) => {
    resolver = si
    rechazar = no
  })
  return { promesa, resolver, rechazar }
}

describe('usePeticion con respaldo', () => {
  it('pinta el respaldo mientras la principal no llega', async () => {
    const principal = diferida<string>()
    const { result } = renderHook(() =>
      usePeticion(() => principal.promesa, [], { respaldo: async () => 'del CDN' }),
    )

    await waitFor(() => expect(result.current.datos).toBe('del CDN'))
    expect(result.current.provisional).toBe(true)
    expect(result.current.cargando).toBe(false)
  })

  it('la principal pisa al respaldo cuando responde', async () => {
    const principal = diferida<string>()
    const { result } = renderHook(() =>
      usePeticion(() => principal.promesa, [], { respaldo: async () => 'del CDN' }),
    )

    await waitFor(() => expect(result.current.datos).toBe('del CDN'))
    principal.resolver('de la API')

    await waitFor(() => expect(result.current.datos).toBe('de la API'))
    expect(result.current.provisional).toBe(false)
  })

  it('un respaldo que llega tarde no pisa a la principal', async () => {
    // Sin la guarda, el backend contesta rapido y medio segundo despues la
    // copia del CDN reemplazaria los datos frescos por los viejos.
    const respaldo = diferida<string | null>()
    const { result } = renderHook(() =>
      usePeticion(async () => 'de la API', [], { respaldo: () => respaldo.promesa }),
    )

    await waitFor(() => expect(result.current.datos).toBe('de la API'))
    respaldo.resolver('del CDN')

    await act(async () => {
      await new Promise((listo) => setTimeout(listo, 10))
    })
    expect(result.current.datos).toBe('de la API')
    expect(result.current.provisional).toBe(false)
  })

  it('si la API falla se conserva lo que el usuario esta leyendo', async () => {
    const principal = diferida<string>()
    const { result } = renderHook(() =>
      usePeticion(() => principal.promesa, [], { respaldo: async () => 'del CDN' }),
    )

    await waitFor(() => expect(result.current.datos).toBe('del CDN'))
    principal.rechazar(new Error('502'))

    await act(async () => {
      await new Promise((listo) => setTimeout(listo, 10))
    })
    expect(result.current.datos).toBe('del CDN')
    expect(result.current.error).toBeNull()
  })

  it('sin respaldo, un fallo de la API sigue siendo un error visible', async () => {
    const { result } = renderHook(() =>
      usePeticion(async () => {
        throw new Error('502')
      }, []),
    )

    await waitFor(() => expect(result.current.error).toBe('502'))
    expect(result.current.datos).toBeNull()
  })

  it('un respaldo vacio no cambia nada', async () => {
    const principal = diferida<string>()
    const { result } = renderHook(() =>
      usePeticion(() => principal.promesa, [], { respaldo: async () => null }),
    )

    await act(async () => {
      await new Promise((listo) => setTimeout(listo, 10))
    })
    expect(result.current.cargando).toBe(true)
    expect(result.current.datos).toBeNull()
  })
})
