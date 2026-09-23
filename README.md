# job-hunter-agent

Pipeline automatizado de búsqueda de empleo. Todos los días scrapea ofertas de [GetOnBoard](https://www.getonbrd.com), las filtra por tu stack, las puntúa contra tu CV usando DeepSeek, y te manda por Telegram solo las que matchean ≥80% junto con un borrador de mensaje de contacto listo para usar.

## Cómo funciona

```
GetOnBoard (scraper) -> filtro por stack -> DeepSeek (% match + borrador) -> Telegram (solo >=80%, top 3)
```

- **`sources/getonbrd.py`** — scrapea listados de programación de GetOnBoard, filtra por keywords de tu `cv.json`.
- **`matcher.py`** — le manda tu CV + la descripción de cada oferta a DeepSeek, pide `match_pct`, `reasoning` y un `draft_message`.
- **`notifier.py`** — arma el digest y lo manda por Telegram (solo si hay algo ≥80% match).
- **`dedup.py`** — guarda en `data/seen_jobs.json` qué ofertas ya se procesaron, para no repetirlas.
- **`main.py`** — orquesta todo el flujo. Se corre una vez por día vía GitHub Actions (`.github/workflows/daily.yml`, 08:00 UTC).
- **`parse_cv.py`** — script aparte (se corre a mano, una sola vez o cuando actualices tu CV) que lee un PDF y arma `cv.json` automáticamente vía DeepSeek.

## Setup

### 1. Instalar dependencias

```bash
pip install -r requirements.txt
```

### 2. Variables de entorno

Copiá `.env.example` a `.env` y completá:

| Variable | De dónde sale |
|---|---|
| `DEEPSEEK_API_KEY` | [platform.deepseek.com](https://platform.deepseek.com) → API keys |
| `TELEGRAM_BOT_TOKEN` | Hablá con [@BotFather](https://t.me/BotFather) en Telegram → `/newbot` |
| `TELEGRAM_CHAT_ID` | Mandale un mensaje a tu bot, después visitá `https://api.telegram.org/bot<TOKEN>/getUpdates` y buscá `"chat":{"id": ...}` |

`main.py` carga `.env` automáticamente (vía `python-dotenv`).

### 3. Tu CV

Subí tu CV en PDF y corré:

```bash
python parse_cv.py ruta/a/tu_cv.pdf
```

Esto lee el PDF, le pide a DeepSeek que lo estructure, y escribe `cv.json` (con backup del anterior en `cv.json.bak`). `cv.json` está gitignoreado — queda solo en tu máquina, nunca se sube al repo (tiene tu nombre y datos personales). El repo solo versiona `cv.example.json` como plantilla.

Si preferís, también podés editar `cv.json` a mano siguiendo el formato de `cv.example.json`.

### 4. Correr una vez a mano

```bash
python main.py
```

## Correr automático (GitHub Actions)

El workflow en `.github/workflows/daily.yml` corre todos los días a las 08:00 UTC. Para activarlo:

1. Pusheá este repo a GitHub.
2. En **Settings → Secrets and variables → Actions**, agregá `DEEPSEEK_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`.
3. El workflow commitea `data/seen_jobs.json` de vuelta al repo después de cada corrida, así el estado persiste entre ejecuciones.

**Ojo si el repo es o va a ser público:** `data/seen_jobs.json` va a acumular en el historial de git qué ofertas fuiste viendo día a día. No es información muy sensible (son slugs de ofertas públicas), pero si te molesta, considerá un repo privado para este proyecto.

## Tests

```bash
pytest -v
```

## Alcance actual (v1)

- Una sola fuente: GetOnBoard. Agregar otro portal es escribir un nuevo módulo en `sources/` con la misma interfaz (`parse_listings(html, keywords) -> list[JobListing]` separado de la parte de red).
- El matching es solo verificación: compara tu CV fijo contra cada oferta. No genera un CV adaptado por vacante.
- Notificación solo por Telegram.
