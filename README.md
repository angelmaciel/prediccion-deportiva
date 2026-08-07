# Predicción Deportiva

Aplicación web de **análisis y predicción de resultados de fútbol** para las ligas europeas top y
la Primera División de Paraguay. Calcula probabilidades de victoria local / empate / victoria
visitante con un modelo de machine learning y publica el historial completo de aciertos del modelo,
medido de forma honesta.

> **Aviso.** Las probabilidades son estimaciones estadísticas calculadas sobre datos históricos, no
> garantías de resultado. Este es un proyecto analítico: no gestiona dinero, no intermedia apuestas
> y no contiene enlaces a casas de apuestas.

---

## Índice

- [Qué hace](#qué-hace)
- [Capturas](#capturas)
- [Stack técnico](#stack-técnico)
- [Arquitectura](#arquitectura)
- [Cómo levantarlo](#cómo-levantarlo)
- [Comandos disponibles](#comandos-disponibles)
- [Decisiones de diseño](#decisiones-de-diseño)
- [Seguridad](#seguridad)
- [Tests](#tests)
- [Despliegue en Render](#despliegue-en-render)
- [Auditoría de dependencias](#auditoría-de-dependencias)

---

## Qué hace

1. **Ingesta cacheada.** Un job programado sincroniza resultados y calendario 1–2 veces al día
   desde football-data.org y API-Football, y guarda todo en PostgreSQL. El frontend nunca llama a
   las APIs externas.
2. **Features sin fuga de información.** Forma reciente, head-to-head, días de descanso, promedios
   de goles y un ranking Elo propio, calculados en una única pasada cronológica.
3. **Predicción.** Regresión logística multinomial para el 1X2 y un Poisson bivariado para el
   marcador exacto.
4. **Transparencia.** Sección pública con accuracy real **por jornada**, comparada contra la línea
   base de "siempre gana el local", más el historial de todas las versiones del modelo.

---

## Capturas

> Las capturas todavía no están incluidas en el repositorio. Para generarlas: levantar el proyecto
> con datos de demo (ver [Cómo levantarlo](#cómo-levantarlo)) y guardar las imágenes en `docs/`
> con estos nombres, que ya están referenciados acá abajo.

| Vista | Archivo esperado |
| --- | --- |
| Próximos partidos con probabilidades | `docs/proximos.png` |
| Historial de aciertos por jornada | `docs/transparencia.png` |
| Flujo completo | `docs/demo.gif` |

---

## Stack técnico

| Capa | Tecnología |
| --- | --- |
| Backend | Python 3.12+ · FastAPI · Pydantic v2 |
| Base de datos | PostgreSQL 16 · SQLAlchemy 2 · Alembic |
| ML | scikit-learn (regresión logística / Random Forest) · Poisson bivariado propio |
| Scheduler | APScheduler embebido o cron job de Render |
| Frontend | React 19 · Vite · TypeScript · Tailwind CSS |
| Infra | Docker Compose (local) · Render (producción) |
| Tests | Pytest (backend) · Vitest + Testing Library (frontend) |
| Calidad | Ruff + Black · ESLint · pip-audit / npm audit |

---

## Arquitectura

```
                    ┌──────────────────────┐
   football-data ──▶│                      │
                    │  Job de sincronización│──▶ PostgreSQL ◀──┐
   API-Football  ──▶│  (1–2 veces al día)  │    (caché propia) │
                    └──────────────────────┘                    │
                                                                │
                    ┌──────────────────────┐                    │
                    │ Reentrenamiento      │────────────────────┤
                    │ semanal + backtest   │  artefactos .joblib│
                    └──────────────────────┘                    │
                                                                │
   Navegador ──▶ React SPA ──▶ FastAPI ────────────────────────┘
                 (cookie       (rate limit, CORS, roles,
                  HttpOnly)     headers de seguridad)
```

Estructura del repositorio:

```
backend/
  app/
    core/         config, cifrado AES-256, argon2/TOTP, rate limit, middlewares
    db/           engine, sesión, base declarativa
    modelos/      SQLAlchemy: usuarios, fútbol, predicción, auditoría
    ml/           elo, features, modelo, poisson, validación walk-forward
    servicios/    ingesta (clientes + cuota), entrenamiento, predicciones, métricas
    api/rutas/    auth, partidos, transparencia, admin
    main.py       app FastAPI, middlewares, manejadores de error
    scheduler.py  jobs programados
  alembic/        migraciones
  tests/          201 tests
  manage.py       CLI de administración
frontend/
  src/
    componentes/  tarjetas, barras de probabilidad, avisos
    paginas/      próximos, resultados, transparencia, ingreso
    api.ts        cliente HTTP (cookies, sin tokens en localStorage)
    tests/        tests de Vitest
```

---

## Cómo levantarlo

### Opción A — Docker Compose (recomendada)

```bash
cp .env.example .env
# Generar los secretos y pegarlos en .env:
python -c "import secrets; print('SECRET_KEY=' + secrets.token_urlsafe(48))"
python -c "import base64,os; print('CLAVE_CIFRADO_DATOS=' + base64.urlsafe_b64encode(os.urandom(32)).decode())"
python -c "import secrets; print('CLAVE_INDICE_CIEGO=' + secrets.token_urlsafe(48))"

docker compose up --build
```

- API: <http://localhost:8000> · documentación interactiva en <http://localhost:8000/docs>
- Frontend: <http://localhost:5173>

Las migraciones se aplican solas al arrancar el backend.

### Opción B — Local sin Docker

```bash
# Base de datos
docker compose up -d db

# Backend
cd backend
python -m venv venv && source venv/bin/activate   # en Windows: venv\Scripts\activate
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload

# Frontend (otra terminal)
cd frontend
npm install
npm run dev
```

### Cargar datos

**Con claves de API** (`FOOTBALL_DATA_TOKEN` y/o `API_FOOTBALL_KEY` en `.env`):

```bash
cd backend
python manage.py sincronizar   # trae partidos reales
python manage.py entrenar      # entrena y valida walk-forward
python manage.py backtest      # llena el historial de aciertos
python manage.py predecir      # predice los próximos partidos
```

**Sin claves de API**, para probar el pipeline completo con datos simulados:

```bash
cd backend
python manage.py demo          # genera 3 temporadas simuladas
python manage.py entrenar
python manage.py backtest
python manage.py predecir
```

> Los números que produce `demo` salen de una liga simulada, no de partidos reales. Sirven para
> verificar que el pipeline funciona, no para evaluar la calidad del modelo.

### Crear un usuario admin

```bash
cd backend
python manage.py crear-admin --email admin@ejemplo.py
```

---

## Comandos disponibles

| Comando | Qué hace |
| --- | --- |
| `python manage.py crear-admin` | Crea o promueve un usuario con rol admin |
| `python manage.py sincronizar` | Trae partidos de las APIs externas (respeta la cuota) |
| `python manage.py entrenar` | Reentrena, valida walk-forward y activa la versión nueva |
| `python manage.py predecir` | Predice los partidos programados |
| `python manage.py backtest` | Predice el histórico walk-forward y recalcula métricas |
| `python manage.py metricas` | Recalcula el historial de aciertos por jornada |
| `python manage.py demo` | Carga un histórico simulado |

Los mismos jobs están disponibles como endpoints en `/admin/*` (requieren rol admin).

---

## Decisiones de diseño

### Por qué walk-forward y no un split aleatorio

Los partidos son una serie temporal. Un `train_test_split` aleatorio entrena con partidos de mayo
y evalúa con partidos de marzo — usa el futuro para predecir el pasado. El accuracy que sale de ahí
es ficticio y no se sostiene en producción.

La validación de este proyecto avanza por cortes temporales: se entrena con `[0, corte)` y se
evalúa con `[corte, corte + paso)`, y el corte avanza pliegue a pliegue sin volver atrás. Es
exactamente lo que hace el sistema en producción.

Esto se extiende al historial público: las predicciones de partidos viejos **no** se generan con el
modelo actual (que ya vio esos resultados al entrenar), sino con el mismo protocolo walk-forward
—`manage.py backtest`. Un test de control negativo verifica que sobre datos de ruido puro el
accuracy no supere el azar; si empieza a fallar, es señal de fuga de información.

### Por qué Poisson bivariado para el marcador

Los goles de un partido se aproximan bien con un proceso de conteo de tasa baja. Dos Poisson
independientes subestiman sistemáticamente los empates, porque ignoran que los partidos abiertos
producen goles de ambos lados y los trabados de ninguno. El término común `λ₃` del Poisson
bivariado captura esa covarianza; se estima directamente de la covarianza empírica, que en este
modelo *es* `λ₃`.

Las fuerzas de ataque y defensa se estiman por razones sobre el promedio de la liga en vez de por
máxima verosimilitud: es estable con pocos datos y no depende de que un optimizador converja en
producción.

### Por qué regresión logística como baseline

Devuelve probabilidades razonablemente calibradas, que es lo que consume la sección de
transparencia — un Brier score bajo importa más acá que un accuracy alto. Además es barata de
reentrenar cada semana y sus coeficientes son interpretables. Random Forest queda disponible
(`--algoritmo random_forest`) para comparar.

Se usa `class_weight="balanced"` porque el empate es la clase minoritaria y sin eso casi nunca
aparece como escenario más probable.

### Por qué Elo propio

Un único número que resume la fuerza de un equipo y se actualiza partido a partido, sin depender de
un proveedor externo. La variante implementada incorpora la ventaja de localía como puntos extra
(~65) y amplifica el ajuste según la diferencia de goles, para que una goleada mueva más el rating
que un 1-0 sufrido.

### Por qué caché agresiva en base propia

API-Football regala 100 requests/día y football-data.org 10/minuto. Si el frontend consultara en
vivo, una decena de visitantes agotaría la cuota y la cuenta quedaría bloqueada. Toda la ingesta
pasa por el job programado, cada request se contabiliza en `consumo_cuota`, y el cliente verifica
el presupuesto restante *antes* de salir a la red.

### Por qué cookie de sesión y no JWT en localStorage

Un token en `localStorage` es legible por cualquier JavaScript que corra en la página; un XSS lo
roba entero. La cookie `HttpOnly` no es accesible desde JS, y `SameSite=Strict` corta el vector
principal de CSRF. La sesión se valida contra la base en cada request, así que revocar una sesión o
desactivar un usuario surte efecto inmediato — cosa que un JWT autocontenido no permite.

### Por qué el email va cifrado con índice ciego

El email es dato personal. Se guarda cifrado con AES-256-GCM, pero eso solo no permitiría buscar
por email al hacer login. La solución es un **índice ciego**: un HMAC-SHA256 con clave del email
normalizado, determinista (permite `WHERE email_indice = ?`) pero no reversible. Sin la clave, un
atacante con la base no puede ni leer los emails ni confirmar si uno dado está registrado.

---

## Seguridad

| Área | Implementación |
| --- | --- |
| Contraseñas | argon2id (64 MiB, t=3, p=2), rehash automático al cambiar parámetros |
| Sesiones | Cookie `HttpOnly` + `SameSite=Strict` + `Secure` en producción; la base guarda solo el SHA-256 del token |
| Enumeración de usuarios | Mensaje genérico en login; hash señuelo para igualar tiempos de respuesta |
| Fuerza bruta | Rate limit de 5 intentos/15 min por IP + bloqueo temporal de cuenta a los 10 fallos |
| 2FA | TOTP opcional (`pyotp`), con secreto cifrado en base |
| Datos personales | AES-256-GCM a nivel de columna + índice ciego HMAC para búsqueda |
| Autorización | `Depends(requerir_admin)` a nivel de router completo, no endpoint por endpoint |
| Validación | Pydantic con `extra="forbid"`: un campo no esperado es 422, no se ignora en silencio |
| SQL Injection | Solo queries parametrizadas vía ORM; nunca concatenación de strings |
| XSS | Escapado por defecto de React; no se usa `dangerouslySetInnerHTML` en ningún lado |
| CSRF | `SameSite=Strict` + verificación de header `Origin`/`Referer` en métodos mutantes |
| CORS | Lista blanca explícita de dominios; la config rechaza el comodín `*` al arrancar |
| Headers | CSP, `X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy`, HSTS en producción |
| Rate limit general | Toda la API, no solo el login: protege el sistema y la cuota de las APIs externas |
| Auditoría | `logs_acceso` registra logins, accesos admin y fallos — nunca contraseñas, tokens ni códigos TOTP |
| Secretos | Todo por variables de entorno; la app **se niega a arrancar** en producción si detecta valores de ejemplo, `DEBUG=true` o `COOKIE_SEGURA=false` |
| Contenedor | El backend corre como usuario sin privilegios, no como root |

---

## Tests

```bash
# Backend — 201 tests
cd backend
pytest -q
pytest --cov=app --cov-report=term-missing

# Frontend
cd frontend
npm test
```

Cobertura por área:

- **Autorización por rol** — cada endpoint admin probado como anónimo (401), usuario común (403) y
  admin (200); revocación de sesión, expiración, desactivación de usuario y promoción de rol en
  caliente.
- **Validación de inputs** — entradas inválidas, campos extra, contraseñas débiles, parámetros
  fuera de rango, intento de inyección SQL, escalada de privilegios vía body.
- **Cálculo de features** — Elo (suma cero, monotonía, multiplicador por goleada), ventanas
  móviles, head-to-head simétrico, días de descanso, y el test clave: **ausencia de fuga de
  información**.
- **Regresión del pipeline** — de punta a punta contra la base: entrenar → predecir → publicar
  métricas; probabilidades que suman 1, reproducibilidad, orden de clases L/E/V, idempotencia del
  backtest, control negativo sobre datos sin señal.
- **Ingesta** — parseo de ambas APIs, upsert idempotente, mapeo de estados, control de cuota.

---

## Despliegue en Render

El repositorio incluye `render.yaml` (Blueprint). Desde el dashboard de Render:

1. **New → Blueprint** y apuntar al repositorio. Render crea la base, la API, el frontend estático
   y el cron job.
2. Cargar a mano los secretos marcados `sync: false`:
   - `CLAVE_CIFRADO_DATOS` — 32 bytes en base64:
     `python -c "import base64,os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"`
   - `FOOTBALL_DATA_TOKEN` y `API_FOOTBALL_KEY`
3. Ajustar `ORIGENES_PERMITIDOS` (backend) y `VITE_API_URL` (frontend) a las URLs reales que
   asigne Render.
4. Crear el admin desde la Shell del servicio: `cd backend && python manage.py crear-admin`.

Notas del plan gratuito:

- El servicio web se duerme por inactividad, así que el APScheduler embebido no correría de forma
  confiable. Por eso `SCHEDULER_ACTIVO=false` y la sincronización va por **cron job** de Render.
- Render provee HTTPS automáticamente; `COOKIE_SEGURA=true` y HSTS quedan activos.
- Los artefactos `.joblib` viven en el disco efímero del servicio: se regeneran en cada
  reentrenamiento. Las métricas y predicciones, que son lo que se muestra, están en la base.

---

## Auditoría de dependencias

```bash
# Backend
cd backend
pip install pip-audit
pip-audit -r requirements.txt

# Frontend
cd frontend
npm audit
npm audit fix        # solo si no rompe versiones mayores
```

Calidad de código:

```bash
cd backend && ruff check . && black --check .
cd frontend && npm run lint
```

---

## Licencia

Proyecto de portfolio. Los datos provienen de football-data.org y API-Football, sujetos a sus
respectivos términos de uso.
