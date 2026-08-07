import { useEffect, useState } from 'react'
import { NavLink, Route, Routes } from 'react-router-dom'

import { api } from './api'
import Ingreso from './paginas/Ingreso'
import Proximos from './paginas/Proximos'
import Resultados from './paginas/Resultados'
import Transparencia from './paginas/Transparencia'
import type { Usuario } from './tipos'

const ENLACES = [
  { a: '/', texto: 'Proximos partidos' },
  { a: '/resultados', texto: 'Resultados' },
  { a: '/transparencia', texto: 'Historial de aciertos' },
]

export default function App() {
  const [usuario, setUsuario] = useState<Usuario | null>(null)

  useEffect(() => {
    // Si hay cookie de sesion valida, el backend devuelve el usuario.
    // Un 401 aca es lo normal para un visitante anonimo, no un error.
    api
      .yo()
      .then(setUsuario)
      .catch(() => setUsuario(null))
  }, [])

  async function cerrarSesion() {
    try {
      await api.logout()
    } finally {
      setUsuario(null)
    }
  }

  return (
    <div className="min-h-screen">
      <header className="border-b border-pizarra-200 bg-white">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-4 px-4 py-3">
          <span className="text-lg font-bold text-cancha-700">Prediccion Deportiva</span>

          <nav className="flex flex-1 flex-wrap gap-1" aria-label="Navegacion principal">
            {ENLACES.map((enlace) => (
              <NavLink
                key={enlace.a}
                to={enlace.a}
                end={enlace.a === '/'}
                className={({ isActive }) =>
                  `rounded-lg px-3 py-1.5 text-sm font-medium transition ${
                    isActive
                      ? 'bg-cancha-50 text-cancha-700'
                      : 'text-pizarra-600 hover:bg-pizarra-100'
                  }`
                }
              >
                {enlace.texto}
              </NavLink>
            ))}
          </nav>

          {usuario ? (
            <div className="flex items-center gap-3 text-sm">
              <span className="hidden text-pizarra-600 sm:inline">{usuario.email}</span>
              {usuario.rol === 'admin' && (
                <span className="etiqueta bg-cancha-50 text-cancha-700">admin</span>
              )}
              <button onClick={cerrarSesion} className="text-pizarra-600 underline">
                Salir
              </button>
            </div>
          ) : (
            <NavLink to="/ingreso" className="text-sm text-cancha-700 underline">
              Ingresar
            </NavLink>
          )}
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-4 py-8">
        <Routes>
          <Route path="/" element={<Proximos />} />
          <Route path="/resultados" element={<Resultados />} />
          <Route path="/transparencia" element={<Transparencia />} />
          <Route path="/ingreso" element={<Ingreso onSesion={setUsuario} />} />
        </Routes>
      </main>

      <footer className="border-t border-pizarra-200 bg-white">
        <div className="mx-auto max-w-6xl space-y-2 px-4 py-6 text-xs text-pizarra-600">
          <p>
            Proyecto de analisis estadistico de futbol. Las predicciones son estimaciones basadas
            en datos historicos y <strong>no son garantias de resultado</strong>.
          </p>
          <p>
            No se gestionan apuestas ni pagos, y no hay enlaces a casas de apuestas. Datos de
            football-data.org y API-Football.
          </p>
        </div>
      </footer>
    </div>
  )
}
