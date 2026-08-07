import { describe, expect, it } from 'vitest'

import { etiquetaResultado, formatearFecha, nivelDeConfianza, porcentaje } from '../formato'

describe('porcentaje', () => {
  it('formatea con el sufijo de porcentaje', () => {
    expect(porcentaje(0.4567)).toBe('45.7 %')
    expect(porcentaje(1)).toBe('100.0 %')
    expect(porcentaje(0)).toBe('0.0 %')
  })

  it('respeta la cantidad de decimales pedida', () => {
    expect(porcentaje(0.4567, 0)).toBe('46 %')
    expect(porcentaje(0.4567, 2)).toBe('45.67 %')
  })

  it('devuelve un guion cuando no hay dato', () => {
    expect(porcentaje(null)).toBe('—')
    expect(porcentaje(undefined)).toBe('—')
    expect(porcentaje(NaN)).toBe('—')
  })
})

describe('etiquetaResultado', () => {
  it('traduce los codigos del backend', () => {
    expect(etiquetaResultado('L')).toBe('Gana local')
    expect(etiquetaResultado('E')).toBe('Empate')
    expect(etiquetaResultado('V')).toBe('Gana visitante')
  })

  it('tolera valores nulos o desconocidos', () => {
    expect(etiquetaResultado(null)).toBe('—')
    expect(etiquetaResultado('X')).toBe('X')
  })
})

describe('formatearFecha', () => {
  it('devuelve un guion con entradas invalidas', () => {
    expect(formatearFecha(null)).toBe('—')
    expect(formatearFecha('no-es-una-fecha')).toBe('—')
  })

  it('formatea una fecha ISO', () => {
    expect(formatearFecha('2026-08-15T14:00:00Z')).toMatch(/2026/)
  })
})

describe('nivelDeConfianza', () => {
  it('describe la confianza sin prometer certeza', () => {
    // Ninguna etiqueta debe sugerir que el resultado esta asegurado.
    const etiquetas = [0.9, 0.5, 0.34].map(nivelDeConfianza)
    for (const etiqueta of etiquetas) {
      expect(etiqueta.toLowerCase()).not.toMatch(/seguro|garantiz|certez/)
    }
  })

  it('escala segun la probabilidad maxima', () => {
    expect(nivelDeConfianza(0.75)).toBe('Tendencia marcada')
    expect(nivelDeConfianza(0.5)).toBe('Tendencia leve')
    expect(nivelDeConfianza(0.34)).toBe('Partido parejo')
  })
})
