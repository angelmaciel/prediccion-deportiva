import { useEffect, useState, type FormEvent } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'

import { ErrorApi, api } from '../api'
import type { Proveedores, Usuario } from '../tipos'

interface Props {
  onSesion: (usuario: Usuario) => void
}

// El backend vuelve del rodeo por Google con ?error=<motivo>; se traduce aca
// para no mostrarle al usuario una palabra suelta en la URL.
const ERRORES_GOOGLE: Record<string, string> = {
  cancelado: 'Cancelaste el ingreso con Google.',
  expirado: 'El intento tardo demasiado. Proba de nuevo.',
  fallo: 'Google no pudo confirmar tu identidad. Proba de nuevo o usa el formulario.',
  inactiva: 'Esa cuenta esta desactivada.',
  '2fa': 'Esa cuenta tiene 2FA activado: ingresa con el formulario para poder poner el codigo.',
}

export default function Ingreso({ onSesion }: Props) {
  const [modo, setModo] = useState<'login' | 'registro'>('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [codigoTotp, setCodigoTotp] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [enviando, setEnviando] = useState(false)
  const [proveedores, setProveedores] = useState<Proveedores | null>(null)
  const [parametros] = useSearchParams()
  const navegar = useNavigate()

  useEffect(() => {
    // Si el backend no tiene credenciales de Google, no se ofrece el boton.
    api
      .proveedores()
      .then(setProveedores)
      .catch(() => setProveedores({ google: false }))
  }, [])

  useEffect(() => {
    const motivo = parametros.get('error')
    if (motivo) setError(ERRORES_GOOGLE[motivo] ?? 'No se pudo ingresar con Google.')
  }, [parametros])

  async function enviar(evento: FormEvent) {
    evento.preventDefault()
    setError(null)
    setEnviando(true)
    try {
      const usuario =
        modo === 'login'
          ? await api.login(email, password, codigoTotp || undefined)
          : await api.registro(email, password)

      if (modo === 'registro') {
        // El registro no abre sesion: hay que loguearse explicitamente.
        setModo('login')
        setPassword('')
        setError(null)
        return
      }
      onSesion(usuario)
      navegar('/')
    } catch (e) {
      // El backend responde mensajes genericos a proposito (no revela si el
      // email existe); se muestran tal cual, sin adornarlos.
      setError(e instanceof ErrorApi ? e.message : 'No se pudo conectar con el servidor')
    } finally {
      setEnviando(false)
    }
  }

  return (
    <div className="mx-auto max-w-md">
      <h1 className="text-2xl font-bold">{modo === 'login' ? 'Iniciar sesion' : 'Crear cuenta'}</h1>
      <p className="mt-1 text-sm text-pizarra-600">
        La cuenta no es necesaria para ver predicciones ni el historial de aciertos: todo eso es
        publico.
      </p>

      <form onSubmit={enviar} className="mt-6 space-y-4" noValidate>
        <div>
          <label htmlFor="email" className="mb-1 block text-sm font-medium">
            Email
          </label>
          <input
            id="email"
            type="email"
            className="campo"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoComplete="email"
            required
          />
        </div>

        <div>
          <label htmlFor="password" className="mb-1 block text-sm font-medium">
            Contrasena
          </label>
          <input
            id="password"
            type="password"
            className="campo"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete={modo === 'login' ? 'current-password' : 'new-password'}
            required
          />
          {modo === 'registro' && (
            <p className="mt-1 text-xs text-pizarra-600">
              Minimo 12 caracteres, con mayuscula, minuscula y numero.
            </p>
          )}
        </div>

        {modo === 'login' && (
          <div>
            <label htmlFor="totp" className="mb-1 block text-sm font-medium">
              Codigo de verificacion <span className="text-pizarra-400">(si tenes 2FA)</span>
            </label>
            <input
              id="totp"
              type="text"
              inputMode="numeric"
              pattern="\d{6}"
              maxLength={6}
              className="campo"
              value={codigoTotp}
              onChange={(e) => setCodigoTotp(e.target.value.replace(/\D/g, ''))}
              autoComplete="one-time-code"
            />
          </div>
        )}

        {error && (
          <p className="rounded-lg bg-rose-50 p-3 text-sm text-rose-800" role="alert">
            {error}
          </p>
        )}

        <button type="submit" className="boton w-full" disabled={enviando}>
          {enviando ? 'Enviando…' : modo === 'login' ? 'Ingresar' : 'Crear cuenta'}
        </button>
      </form>

      {proveedores?.google && (
        <>
          <div className="my-6 flex items-center gap-3" aria-hidden="true">
            <span className="h-px flex-1 bg-pizarra-200" />
            <span className="text-xs uppercase tracking-wide text-pizarra-400">o</span>
            <span className="h-px flex-1 bg-pizarra-200" />
          </div>

          <button
            type="button"
            onClick={() => api.irAGoogle()}
            className="flex w-full items-center justify-center gap-3 rounded-lg border border-pizarra-300 bg-white px-4 py-2.5 text-sm font-medium text-pizarra-700 transition hover:bg-pizarra-50"
          >
            <svg className="h-5 w-5" viewBox="0 0 24 24" aria-hidden="true">
              <path
                fill="#4285F4"
                d="M23.52 12.27c0-.79-.07-1.54-.2-2.27H12v4.51h6.47a5.53 5.53 0 0 1-2.4 3.63v3h3.87c2.27-2.09 3.58-5.17 3.58-8.87Z"
              />
              <path
                fill="#34A853"
                d="M12 24c3.24 0 5.96-1.08 7.94-2.91l-3.87-3c-1.08.72-2.45 1.15-4.07 1.15-3.13 0-5.78-2.11-6.73-4.95H1.28v3.09A12 12 0 0 0 12 24Z"
              />
              <path
                fill="#FBBC05"
                d="M5.27 14.29a7.2 7.2 0 0 1 0-4.58V6.62H1.28a12 12 0 0 0 0 10.76l3.99-3.09Z"
              />
              <path
                fill="#EA4335"
                d="M12 4.75c1.77 0 3.35.61 4.6 1.8l3.43-3.43C17.95 1.19 15.24 0 12 0A12 12 0 0 0 1.28 6.62l3.99 3.09C6.22 6.87 8.87 4.75 12 4.75Z"
              />
            </svg>
            Continuar con Google
          </button>

          <p className="mt-2 text-xs text-pizarra-500">
            Google nos comparte solo tu email verificado. No recibimos tu contrasena.
          </p>
        </>
      )}

      <button
        type="button"
        className="mt-4 text-sm text-cancha-700 underline"
        onClick={() => {
          setModo(modo === 'login' ? 'registro' : 'login')
          setError(null)
        }}
      >
        {modo === 'login' ? 'No tengo cuenta' : 'Ya tengo cuenta'}
      </button>
    </div>
  )
}
