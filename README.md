# job-hunter-agent

Pipeline automatizado de búsqueda de empleo. Todos los días scrapea ofertas de [GetOnBoard](https://www.getonbrd.com) y [Computrabajo](https://cl.computrabajo.com), las filtra por tu stack, un filtro barato (Jev/TypeSafe) decide si vale la pena mirarlas en detalle, y solo esas pocas pasan a DeepSeek para el análisis rico (% match + borrador). Te manda por Telegram solo las que matchean ≥80% junto con un borrador de mensaje de contacto listo para usar. Todo el historial de matches queda en Supabase, navegable desde un dashboard web con tracking de status/notas por postulación.

## Estructura del repo

```
pipeline/    -> el cron diario (Python), corre en GitHub Actions
dashboard/   -> app Next.js de solo-lectura+tracking, deployada en Vercel
supabase/    -> migraciones SQL del schema/RLS (aplicadas vía Supabase MCP, versionadas acá)
```

## Cómo funciona el pipeline

```
GetOnBoard + Computrabajo (scrapers) -> filtro por stack -> Jev (¿vale la pena? barato, corre en el 100%) -> DeepSeek (% match + borrador, solo en las que Jev aprobó) -> Supabase (historial) -> Telegram (solo >=80%, top 3)
```

- **`pipeline/sources/getonbrd.py`** — scrapea listados de programación de GetOnBoard, filtra por keywords de tu `cv.json`. Descripción viene en el mismo listado.
- **`pipeline/sources/computrabajo.py`** — scrapea la categoría "desarrollador" de Computrabajo Chile. El listado no trae descripción, así que primero filtra por título (barato) y recién para las que matchean hace un segundo request a la página de detalle.
- **`pipeline/main.py`** combina ambas fuentes: si una se cae, sigue con la otra — solo aborta si **las dos** fallan a la vez.
- **`pipeline/judge.py`** — filtro barato: le manda tu CV + la oferta a Jev (TypeSafe AI), pide sí/no. Corre sobre el 100% de las ofertas nuevas.
- **`pipeline/matcher.py`** — solo para las ofertas que Jev aprobó: le manda tu CV + la descripción a DeepSeek, pide `match_pct`, `reasoning` y un `draft_message`.
- **`pipeline/notifier.py`** — arma el digest y lo manda por Telegram (solo si hay algo ≥80% match).
- **`pipeline/db.py`** — persiste cada oferta procesada (aprobada o no) en Supabase (`listings` table), y usa esa tabla para dedup en vez de un archivo local.
- **`pipeline/main.py`** — orquesta todo el flujo. Se corre una vez por día vía GitHub Actions (`.github/workflows/daily.yml`, 08:00 UTC).
- **`pipeline/parse_cv.py`** — script aparte (se corre a mano) que lee un PDF y arma `cv.json` automáticamente vía DeepSeek.

## Dashboard

App Next.js en `dashboard/`, con login vía Supabase Auth y RLS (cada usuario solo ve sus propias filas). Muestra el historial completo de `listings`, con:

- Status por oferta (nuevo/aplicado/en proceso/rechazado/descartado) y notas propias, editables desde la tabla.
- `/stats` — totales, tasa de aprobación del filtro Jev, % match promedio, desglose por fuente y por status (agregado server-side vía funciones SQL, no trayendo todas las filas al cliente).
- Búsqueda de texto libre y filtro por rango de fechas.

**Deployado en:** `https://job-hunter-agent-dashboard.vercel.app`

**Ojo:** el proyecto de Vercel no está conectado al repo de GitHub (un bug de scope en la integración Vercel de este entorno lo impidió). Cada cambio a `dashboard/` necesita un redeploy manual con `create_deployment` (ver el ledger en `.superpowers/sdd/` si seguís usando ese flujo, o reconectar el proyecto a GitHub desde el dashboard de Vercel una vez que el scope esté arreglado).

### Setup del dashboard

```bash
cd dashboard
npm install
```

Variables de entorno (`dashboard/.env.local`):

| Variable | De dónde sale |
|---|---|
| `NEXT_PUBLIC_SUPABASE_URL` | Supabase → Project Settings → API |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Supabase → Project Settings → API (publishable/anon key, no el `service_role`) |

```bash
npm run dev    # local
npm run build  # verificar que compila antes de deployar
```

## Setup del pipeline

### 1. Instalar dependencias

```bash
cd pipeline
pip install -r requirements.txt
```

### 2. Variables de entorno

Copiá `pipeline/.env.example` a `pipeline/.env` y completá:

| Variable | De dónde sale |
|---|---|
| `DEEPSEEK_API_KEY` | [platform.deepseek.com](https://platform.deepseek.com) → API keys |
| `TELEGRAM_BOT_TOKEN` | Hablá con [@BotFather](https://t.me/BotFather) en Telegram → `/newbot` |
| `TELEGRAM_CHAT_ID` | Mandale un mensaje a tu bot, después visitá `https://api.telegram.org/bot<TOKEN>/getUpdates` y buscá `"chat":{"id": ...}` |
| `JEV_API_KEY` | [typesafe.ai](https://typesafe.ai) — filtro barato que decide qué ofertas vale la pena mandarle a DeepSeek |
| `SUPABASE_URL` | Supabase → Project Settings → API |
| `SUPABASE_SERVICE_ROLE_KEY` | Supabase → Project Settings → API (¡nunca la expongas client-side, solo la usa el pipeline server-side!) |
| `BACKFILL_USER_ID` | UUID del usuario de Supabase Auth dueño de las filas que inserta el pipeline |
| `MATCH_THRESHOLD` | Opcional, % mínimo de match para recibir la oferta por Telegram. Default: `80` |

`main.py` carga `.env` automáticamente (vía `python-dotenv`).

### 3. Tu CV

```bash
python parse_cv.py ruta/a/tu_cv.pdf
```

Esto lee el PDF, le pide a DeepSeek que lo estructure, y escribe `cv.json` (gitignoreado — nunca se sube, tiene tus datos personales). El repo solo versiona `cv.example.json` como plantilla.

### 4. Correr una vez a mano

```bash
python main.py
```

## Correr automático (GitHub Actions)

El workflow en `.github/workflows/daily.yml` corre todos los días a las 08:00 UTC, con `working-directory: pipeline`. Para activarlo:

1. Pusheá este repo a GitHub.
2. En **Settings → Environments**, creá un environment llamado `env`.
3. Dentro de ese environment, agregá los secrets: `DEEPSEEK_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `JEV_API_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `BACKFILL_USER_ID`, `CV_JSON` (contenido completo de tu `cv.json`, como texto).
4. (Opcional) En **Settings → Secrets and variables → Actions → Variables**, agregá `MATCH_THRESHOLD` si querés un umbral distinto al 80% default.
5. Si cualquier paso del job falla, el último step (`if: failure()`) te manda un Telegram de alerta con el link al log del run.

El estado de dedup vive en Supabase, no en el repo — el workflow ya no commitea nada de vuelta a git.

## Tests

```bash
cd pipeline
pytest -v
```

El dashboard no tiene test suite automatizado (se verifica manualmente contra Supabase real con Playwright).

## Base de datos

El schema y las policies de RLS están versionados en `supabase/migrations/` (aplicados vía Supabase MCP). Si necesitás recrear el proyecto o revisar qué cambió, esos archivos son la fuente de verdad — no la UI de Supabase.

## Alcance actual

- 2 fuentes: GetOnBoard y Computrabajo. Agregar otro portal es escribir un nuevo módulo en `pipeline/sources/` con la misma interfaz (`fetch_listings(keywords) -> list[JobListing]`) y agregarlo a `SOURCE_FETCHERS` en `main.py`.
- Computrabajo solo trae 1 página de resultados por corrida; no pagina todavía.
- El matching es solo verificación: compara tu CV fijo contra cada oferta. No genera un CV adaptado por vacante.
- Single-user: un solo `cv.json` y un solo `BACKFILL_USER_ID` para todo el pipeline. Multi-usuario (subida de CV propia, preferencias, suscripción) es la próxima etapa planeada, no implementada.
- El pipeline nunca postula automáticamente — solo genera el borrador de mensaje (`draft_message`). Enviar la postulación siempre es manual.
