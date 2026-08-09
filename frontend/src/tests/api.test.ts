import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ErrorApi, api, reiniciarCacheDeLigas } from '../api'

function respuestaFalsa(cuerpo: unknown, estado = 200) {
  return {
    ok: estado >= 200 && estado < 300,
    status: estado,
    json: async () => cuerpo,
  } as Response
}

describe('cliente de la API', () => {
  let fetchSimulado: ReturnType<typeof vi.fn>

  beforeEach(() => {
    fetchSimulado = vi.fn()
    vi.stubGlobal('fetch', fetchSimulado)
    reiniciarCacheDeLigas()
  })

  it('pide las ligas una sola vez aunque varias pantallas las necesiten', async () => {
    fetchSimulado.mockResolvedValue(respuestaFalsa(['La Liga']))

    const [a, b] = await Promise.all([api.ligas(), api.ligas()])
    expect(a).toEqual(b)
    expect(fetchSimulado).toHaveBeenCalledTimes(1)

    await api.ligas()
    expect(fetchSimulado).toHaveBeenCalledTimes(1)
  })

  it('no cachea un fallo al pedir las ligas', async () => {
    fetchSimulado.mockResolvedValueOnce(respuestaFalsa({ detail: 'caida' }, 503))
    await expect(api.ligas()).rejects.toThrow('caida')

    fetchSimulado.mockResolvedValueOnce(respuestaFalsa(['La Liga']))
    await expect(api.ligas()).resolves.toEqual(['La Liga'])
  })

  it('envia las cookies de sesion en las llamadas que dependen del usuario', async () => {
    // La sesion vive en una cookie HttpOnly: sin `credentials: include` el
    // navegador no la manda y el usuario aparece siempre como anonimo.
    fetchSimulado.mockResolvedValue(respuestaFalsa({ id: 1 }))
    await api.yo()

    const [, opciones] = fetchSimulado.mock.calls[0]
    expect(opciones.credentials).toBe('include')
  })

  it('las lecturas publicas van sin cookie para que se puedan cachear', async () => {
    // Una respuesta atada a credenciales no la guarda ninguna cache compartida.
    // Estas son iguales para todos los visitantes, asi que mandar la cookie
    // anularia el Cache-Control que devuelve el backend.
    fetchSimulado.mockResolvedValue(respuestaFalsa([]))

    await api.proximosPartidos()
    await api.listarPartidos()
    await api.ligas()
    await api.resumenModelo()
    await api.detallePartido(1)
    await api.veredicto(1)
    await api.h2h(1)

    for (const [url, opciones] of fetchSimulado.mock.calls) {
      expect(opciones.credentials, `${url} no deberia mandar cookie`).toBe('omit')
    }
  })

  it('no adjunta ningun token en los headers', async () => {
    fetchSimulado.mockResolvedValue(respuestaFalsa([]))
    await api.ligas()

    const [, opciones] = fetchSimulado.mock.calls[0]
    const headers = JSON.stringify(opciones.headers).toLowerCase()
    expect(headers).not.toContain('authorization')
    expect(headers).not.toContain('bearer')
  })

  it('arma los parametros de consulta solo con valores presentes', async () => {
    fetchSimulado.mockResolvedValue(respuestaFalsa([]))
    await api.proximosPartidos(undefined, 7)

    const [url] = fetchSimulado.mock.calls[0]
    expect(url).toContain('dias=7')
    expect(url).not.toContain('liga=')
  })

  it('pide por defecto la ventana de ayer, hoy y manana', async () => {
    // El default acotado es lo que hace que las vistas abran rapido: si esto
    // se rompe, el backend vuelve a barrer temporadas enteras en cada visita.
    fetchSimulado.mockResolvedValue(respuestaFalsa([]))
    await api.proximosPartidos()

    expect(fetchSimulado.mock.calls[0][0]).toContain('dias=1')
  })

  it('omite el flag de historico cuando esta apagado', async () => {
    fetchSimulado.mockResolvedValue(respuestaFalsa({ items: [] }))
    await api.listarPartidos({ estado: 'finalizado' })
    expect(fetchSimulado.mock.calls[0][0]).not.toContain('historico')

    await api.listarPartidos({ estado: 'finalizado', historico: true })
    expect(fetchSimulado.mock.calls[1][0]).toContain('historico=true')
  })

  it('codifica los filtros para no romper la URL', async () => {
    fetchSimulado.mockResolvedValue(respuestaFalsa([]))
    await api.proximosPartidos('Primera Division de Paraguay')

    const [url] = fetchSimulado.mock.calls[0]
    expect(url).toContain('liga=Primera+Division+de+Paraguay')
  })

  it('propaga el mensaje del backend en los errores', async () => {
    fetchSimulado.mockResolvedValue(
      respuestaFalsa({ detail: 'Email o contrasena incorrectos' }, 401),
    )

    await expect(api.login('a@b.py', 'mala')).rejects.toThrow('Email o contrasena incorrectos')
  })

  it('expone el codigo de estado en el error', async () => {
    fetchSimulado.mockResolvedValue(respuestaFalsa({ detail: 'No encontrado' }, 404))

    await expect(api.detallePartido(1)).rejects.toMatchObject({
      name: 'ErrorApi',
      estado: 404,
    })
  })

  it('tolera respuestas de error sin cuerpo JSON', async () => {
    fetchSimulado.mockResolvedValue({
      ok: false,
      status: 502,
      json: async () => {
        throw new Error('no es JSON')
      },
    } as unknown as Response)

    await expect(api.ligas()).rejects.toThrow('Error 502')
  })

  it('el login manda el codigo TOTP solo si se proporciono', async () => {
    fetchSimulado.mockResolvedValue(respuestaFalsa({ id: 1 }))

    await api.login('a@b.py', 'Password123456')
    expect(JSON.parse(fetchSimulado.mock.calls[0][1].body)).not.toHaveProperty('codigo_totp')

    await api.login('a@b.py', 'Password123456', '123456')
    expect(JSON.parse(fetchSimulado.mock.calls[1][1].body)).toHaveProperty('codigo_totp', '123456')
  })

  it('ErrorApi es una instancia de Error', () => {
    const error = new ErrorApi(403, 'Sin permisos')
    expect(error).toBeInstanceOf(Error)
    expect(error.estado).toBe(403)
  })
})
