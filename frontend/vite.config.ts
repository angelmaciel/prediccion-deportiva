import react from '@vitejs/plugin-react'
// `defineConfig` de vitest/config es el que acepta la clave `test`.
import { defineConfig } from 'vitest/config'

// Este archivo corre en Node, pero el tsconfig del proyecto es el del navegador
// y no incluye @types/node. Se declara lo unico que se usa en vez de sumar una
// dependencia entera de tipos.
declare const process: { env: Record<string, string | undefined> }

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // El bind mount de Windows hacia el contenedor no propaga eventos inotify:
    // sin polling, Vite nunca se entera de que un archivo cambio y sigue
    // sirviendo el modulo viejo desde su cache, aunque el archivo en disco ya
    // este actualizado. Se paga un poco de CPU a cambio de que recargar el
    // navegador muestre lo que uno acaba de escribir.
    watch: { usePolling: true, interval: 300 },
    // El puerto publicado en el host puede no ser el 5173 (ver PUERTO_FRONTEND
    // en docker-compose); sin esto el websocket de HMR apunta al puerto
    // equivocado y el navegador no recibe las actualizaciones en caliente.
    hmr: { clientPort: Number(process.env.PUERTO_FRONTEND ?? 5173) },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/tests/setup.ts'],
    css: false,
  },
})
