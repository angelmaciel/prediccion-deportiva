// Analisis en prosa del partido, escrito por un modelo de lenguaje.
//
// Solo lee lo que ya se genero. Escribirlo cuesta dinero por token, asi que se
// dispara desde el panel de admin o el job, nunca al abrir una tarjeta.

import { useEffect, useState } from 'react'

import { api } from '../api'
import { formatearFecha } from '../formato'
import type { Narrativa, Partido } from '../tipos'

/** Los bloques del analisis vienen numerados; se resaltan como encabezados. */
const ENCABEZADO = /^\s*\d\.\s+[A-ZÁÉÍÓÚÑ0-9 ,()/-]+$/

function Cuerpo({ texto }: { texto: string }) {
  return (
    <div className="mt-3 space-y-2 text-xs leading-relaxed text-pizarra-700">
      {texto
        .split('\n')
        .map((linea) => linea.trim())
        .filter(Boolean)
        .map((linea, i) =>
          ENCABEZADO.test(linea) ? (
            <h4 key={i} className="pt-2 text-xs font-semibold text-pizarra-800">
              {linea}
            </h4>
          ) : (
            <p key={i}>{linea}</p>
          ),
        )}
    </div>
  )
}

export function VistaNarrativa({ partido }: { partido: Partido }) {
  const [datos, setDatos] = useState<Narrativa | null>(null)
  const [estado, setEstado] = useState<'cargando' | 'listo' | 'sin-generar'>('cargando')

  useEffect(() => {
    let vigente = true
    api
      .narrativa(partido.id)
      .then((r) => {
        if (!vigente) return
        setDatos(r)
        setEstado('listo')
      })
      .catch(() => vigente && setEstado('sin-generar'))
    return () => {
      vigente = false
    }
  }, [partido.id])

  if (estado === 'cargando') {
    return <p className="mt-3 text-xs text-pizarra-400">Cargando analisis…</p>
  }
  if (estado === 'sin-generar' || !datos) {
    return (
      <p className="mt-3 text-xs text-pizarra-500">
        Todavia no se escribio el analisis de este partido. Se genera desde el panel de
        administracion, porque cada uno tiene un costo por token.
      </p>
    )
  }

  return (
    <div className="mt-3">
      <Cuerpo texto={datos.texto} />

      {datos.fuentes.length > 0 && (
        <section className="mt-4">
          <h4 className="text-xs font-semibold text-pizarra-700">Fuentes consultadas</h4>
          <ul className="mt-1 space-y-0.5">
            {datos.fuentes.map((url) => (
              <li key={url}>
                <a
                  href={url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-[11px] text-cancha-700 underline"
                >
                  {url}
                </a>
              </li>
            ))}
          </ul>
        </section>
      )}

      <p className="mt-4 text-[11px] text-pizarra-400">
        {datos.aviso} Escrito con {datos.modelo} el {formatearFecha(datos.creado_en)}.
      </p>
    </div>
  )
}
