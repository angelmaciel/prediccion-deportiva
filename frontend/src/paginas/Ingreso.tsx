import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'

import { ErrorApi, api } from '../api'
import type { Usuario } from '../tipos'

interface Props {
  onSesion: (usuario: Usuario) => void
}

export default function Ingreso({ onSesion }: Props) {
  const [modo, setModo] = useState<'login' | 'registro'>('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [codigoTotp, setCodigoTotp] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [enviando, setEnviando] = useState(false)
  const navegar = useNavigate()

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
      <h1 className="text-2xl font-bold">
        {modo === 'login' ? 'Iniciar sesion' : 'Crear cuenta'}
      </h1>
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
