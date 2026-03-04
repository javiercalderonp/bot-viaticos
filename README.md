# Travel Expense AI Agent (MVP v1)

MVP para automatizar gestión de viáticos vía WhatsApp, con captura de boletas, extracción de datos, conversación para completar faltantes y almacenamiento en Google Sheets.

## Objetivo

Construir un agente de viáticos por WhatsApp que:

- Sea proactivo antes y durante el viaje.
- Reciba boletas por WhatsApp.
- Extraiga información con Google Document AI.
- Dialogue con el usuario cuando falten datos.
- Guarde gastos estructurados en Google Sheets.
- Soporte gastos compartidos básicos (50/50).
- Maneje estado de conversación.

Este proyecto busca un MVP funcional, profesional y simple.

## Principios del MVP

- Sin sobre-ingeniería.
- Sin microservicios.
- Sin base de datos SQL.
- Google Sheets actúa como base de datos.
- Identificación por número de WhatsApp (sin autenticación web).

## Stack Tecnológico

- Backend: Python
- Framework: FastAPI
- Canal: Twilio WhatsApp API
- OCR: Google Document AI
- Base de datos: Google Sheets
- Exchange rate: diccionario hardcoded
- Hosting: TBD
- LLM: opcional (recomendado para inferencia de merchant, país/moneda, clasificación automática de categoría y respuestas contextuales de chat)

## Alcance MVP v1

### Incluye

- Recepción de mensajes (texto e imagen) vía webhook de Twilio.
- Identificación de empleado por teléfono.
- Gestión de estado conversacional en Google Sheets.
- OCR (placeholder inicial, integración real después).
- Validación de campos obligatorios.
- Confirmación de resumen antes de persistir.
- Persistencia de gastos en hoja `Expenses`.
- Conversación para gastos compartidos (50/50) en flujo básico.

### No incluye aún

- Scheduler (recordatorios automáticos).
- Lógica OCR completa con Google Document AI.
- Panel web / autenticación.
- Aprobaciones complejas.
- Tipos de split avanzados (porcentaje, monto custom, múltiples personas).

## Flujo General del Producto

### 1. Proactividad (fase posterior)

Un scheduler debe ejecutar:

- Día -1 del viaje: mensaje introductorio.
- Cada día del viaje a las 19:00: recordatorio de boletas.
- Día +1 del viaje: mensaje de cierre.

Nota: este componente está definido pero **no se implementará en la primera iteración**.

### 2. Recepción de boleta

1. Empleado envía imagen por WhatsApp.
2. Webhook recibe evento Twilio.
3. Se valida firma Twilio.
4. Se identifica empleado por número.
5. Se actualiza conversación a `PROCESSING`.
6. Se envía imagen a OCR (placeholder inicial).
7. Se extraen campos.
8. Se intenta mejorar `merchant` (LLM si OCR viene vacío/genérico, con fallback OCR).
9. Se intenta inferir `country` y `currency` (LLM si está configurado, con fallback OCR/heurísticas).
10. Se intenta clasificar `category` automáticamente (LLM si está configurado, si no reglas locales).
11. Se validan faltantes.
12. Si faltan datos, pasa a `NEEDS_INFO`.
13. Si está completo, pasa a `CONFIRM_SUMMARY`.

### 3. Completar faltantes (slot filling)

Campos obligatorios para persistir un gasto:

- `merchant`
- `date`
- `total`
- `currency`
- `category`
- `country`
- `trip_id`

Si falta alguno:

- estado conversación = `NEEDS_INFO`
- el bot pregunta un campo a la vez usando opciones numeradas cuando aplica

### 4. Confirmación

Cuando están todos los campos:

- se envía resumen al usuario
- opciones: `Confirmar`, `Corregir`, `Cancelar`

Si confirma:

- calcular `total_clp` con tasa hardcoded
- guardar en `Expenses`
- `status` del gasto = `pending_approval`
- estado conversación = `DONE`

### 5. Gasto compartido (MVP básico)

Después de confirmar gasto:

1. Preguntar si fue compartido.
2. Si sí:
   - pedir teléfono del otro colaborador
   - dividir 50/50
   - crear dos filas en `Expenses` con `shared = true`

## Estados de Conversación (State Machine)

- `WAIT_RECEIPT`
- `PROCESSING`
- `NEEDS_INFO`
- `CONFIRM_SUMMARY`
- `DONE`

### Estado recomendado por tipo de evento

- Imagen nueva: `PROCESSING`
- OCR incompleto: `NEEDS_INFO`
- OCR completo: `CONFIRM_SUMMARY`
- Confirmación y guardado: `DONE`
- Después de cerrar flujo / próximo gasto: `WAIT_RECEIPT`

## Arquitectura Deseada (Monolito modular)

```text
app/
  main.py
  config.py

services/
  sheets_service.py
  whatsapp_service.py
  ocr_service.py
  travel_service.py
  expense_service.py
  conversation_service.py
  scheduler_service.py

utils/
  exchange_rate.py
  helpers.py
```

### Responsabilidades por módulo

- `app/main.py`: FastAPI, endpoints, wiring básico de servicios.
- `app/config.py`: configuración por variables de entorno.
- `services/sheets_service.py`: acceso a Google Sheets (lectura/escritura).
- `services/whatsapp_service.py`: validación Twilio y respuestas.
- `services/ocr_service.py`: integración con Google Document AI + heurísticas/fallback.
- `services/llm_service.py`: inferencia de merchant/país/moneda y clasificación semántica de categoría (OpenAI, opcional).
- `services/travel_service.py`: lógica de viajes activos y reglas de viaje.
- `services/expense_service.py`: validación/persistencia de gastos.
- `services/conversation_service.py`: state machine y slot filling.
- `services/scheduler_service.py`: recordatorios automáticos por viaje (MVP vía endpoint + cron/job externo).
- `utils/exchange_rate.py`: conversión de moneda a CLP.
- `utils/helpers.py`: helpers comunes (fechas, phone normalizer, timestamps).

## Google Sheets como Base de Datos

Spreadsheet: `Travel_Agent_MVP`

### Hoja `Employees`

| phone | name | rut | active |
|---|---|---|---|

### Hoja `Trips`

| trip_id | phone | destination | country | start_date | end_date | budget | status |
|---|---|---|---|---|---|---|---|

### Hoja `Expenses`

| expense_id | phone | trip_id | merchant | date | currency | total | total_clp | category | country | shared | status | receipt_drive_url | created_at |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|

### Hoja `Conversations`

| phone | state | current_step | context_json | updated_at |
|---|---|---|---|---|

### Notas de modelado (MVP)

- `phone` será la llave de identificación del usuario.
- `context_json` almacenará el estado conversacional y el borrador del gasto.
- No se usa Postgres ni almacenamiento adicional en esta fase.
- Se recomienda normalizar teléfonos a formato E.164.

## Inicialización de Google Sheets (headers + datos demo)

Se agregó un script para:

- asegurar que existan las 4 hojas (`Employees`, `Trips`, `Expenses`, `Conversations`)
- escribir los headers correctos en la fila 1
- limpiar filas (opcional)
- cargar datos demo (opcional)

### Script

- `scripts/seed_sheets.py`

### Requisitos

```bash
pip install gspread google-auth google-api-python-client
```

### Uso recomendado

```bash
python scripts/seed_sheets.py \
  --credentials ./biaticos-488419-1073823ba21a.json \
  --spreadsheet-id 1PgJc4460etPJxx1nSgtC4fGy0RGX85xVc55nm94plrk \
  --clear-data \
  --seed-demo
```

### Variables de entorno alternativas

El script también acepta:

- `GOOGLE_APPLICATION_CREDENTIALS`
- `GOOGLE_SHEETS_SPREADSHEET_ID`
- `DRIVE_RECEIPTS_FOLDER_ID` (opcional)

Ejemplo:

```bash
export GOOGLE_APPLICATION_CREDENTIALS=./biaticos-488419-1073823ba21a.json
export GOOGLE_SHEETS_SPREADSHEET_ID=1PgJc4460etPJxx1nSgtC4fGy0RGX85xVc55nm94plrk
python scripts/seed_sheets.py --clear-data --seed-demo
```

### Qué datos demo carga

- `Employees`: 2 empleados demo (incluye tu número por defecto)
- `Trips`: 1 viaje activo asociado al empleado principal
- `Expenses`: 1 gasto de ejemplo `pending_approval`
- `Conversations`: estados `WAIT_RECEIPT` demo

### Nota de seguridad

- No subas el JSON de credenciales de Google al repositorio.
- No subas tokens de Twilio ni `OPENAI_API_KEY` al repositorio.

## Inferencia de Merchant, País/Moneda y Clasificación de Categoría (LLM + fallback)

El flujo de gastos usa un enfoque híbrido:

- `OCR` (Document AI) sigue extrayendo datos estructurados (`merchant`, `date`, `total`, etc.) y entrega `ocr_text`.
- `LLM` (OpenAI, opcional) puede inferir/mejorar `merchant` cuando OCR devuelve un valor vacío o genérico (ej. `COMPROBANTE DE VENTA`).
- `LLM` (OpenAI, opcional) puede inferir `country` y `currency` desde `ocr_text` y pistas del recibo.
  - Prioriza evidencia de ubicación (`ciudad`, `dirección`, sucursal, identificadores fiscales) por sobre el nombre del comercio.
  - Ejemplo: si el merchant dice `MISTURA DEL PERU` pero la boleta muestra `Santiago`, debe inferir `Chile` y típicamente `CLP`.
- `LLM` (OpenAI, opcional) clasifica `category` en una de estas opciones:
  - `Meals`
  - `Transport`
  - `Lodging`
  - `Other`
- `LLM` (OpenAI, opcional) también responde preguntas generales del usuario sobre el flujo
  (ej.: "como se manda una boleta") usando contexto base del MVP.
- Si el LLM no está configurado o falla:
  - `merchant` se mantiene desde OCR / heurísticas OCR
  - `country` / `currency` se mantienen desde OCR / heurísticas OCR
  - `category` usa reglas locales por keywords del comercio
  - preguntas generales de chat vuelven al mensaje guía para enviar boleta

### Variables de entorno para habilitar LLM

```bash
EXPENSE_CATEGORY_LLM_ENABLED=true
CHAT_ASSISTANT_ENABLED=true
OPENAI_API_KEY=<tu_api_key>
OPENAI_MODEL=gpt-4o-mini
OPENAI_TIMEOUT_SECONDS=12
```

Opcional:

```bash
OPENAI_BASE_URL=https://api.openai.com/v1
```

### Qué hace el LLM y qué no

- Sí hace:
  - inferencia/mejora de `merchant` (fallback sobre OCR cuando viene genérico o vacío)
  - inferencia de `country` y `currency` (priorizando ciudad/dirección de la boleta)
  - clasificación de `category`
- No hace (por defecto): OCR/escaneo completo de boletas.

Esta separación reduce costo/latencia y evita errores en campos críticos como fecha y monto.

### Diagnóstico rápido del LLM (health + logs)

El endpoint `GET /health` expone señales útiles para confirmar que la configuración se cargó:

- `category_llm_flag`: si `EXPENSE_CATEGORY_LLM_ENABLED=true`
- `openai_api_key_present`: si existe `OPENAI_API_KEY`
- `category_llm_enabled`: si el clasificador LLM quedó realmente activo (flag + key)
- `chat_assistant_flag`: si `CHAT_ASSISTANT_ENABLED=true`
- `chat_assistant_enabled`: si el asistente de chat quedó realmente activo (flag + key)
- `openai_model`: modelo configurado

Logs útiles durante pruebas:

- `LLM merchant inference success ...`
- `Expense merchant inferred source=llm ...`
- `LLM country/currency inference success ...`
- `Expense country/currency inferred source=llm ...`
- `LLM category classification success ...`
- `Category classification source=llm|rules|none`
- `LLM ... failed: ...` (si hubo error de red/API/key)
- Agrega el archivo a `.gitignore` (o usa una ruta local fuera del repo).

## Flujo Técnico (Webhook)

### Entrada esperada desde Twilio

- `From` (número WhatsApp)
- `Body` (texto)
- `NumMedia`
- `MediaUrl0` (si existe imagen)
- firma Twilio (`X-Twilio-Signature`)

### Lógica del webhook (MVP)

1. Validar firma Twilio (con toggle para desarrollo local si es necesario).
2. Normalizar número de teléfono.
3. Buscar empleado activo en `Employees`.
4. Obtener conversación actual en `Conversations` (o inicializar).
5. Si `NumMedia > 0`:
   - actualizar estado a `PROCESSING`
   - llamar OCR placeholder
   - buscar viaje activo en `Trips`
   - validar campos obligatorios
   - transicionar a `NEEDS_INFO` o `CONFIRM_SUMMARY`
6. Si es texto:
   - procesar según `state` + `current_step`
   - actualizar conversación
   - guardar gasto si hay confirmación final
7. Responder mensaje al usuario (texto simple para MVP).

## Flujo Conversacional (MVP mínimo funcional)

### Caso A: Imagen con datos incompletos

1. Usuario envía boleta.
2. OCR detecta parcialmente.
3. Bot pregunta faltantes (ej. moneda, categoría, país).
4. Usuario responde.
5. Bot confirma resumen.
6. Usuario confirma.
7. Se guarda gasto.

### Caso B: Imagen con datos completos

1. Usuario envía boleta.
2. OCR detecta todo + viaje activo.
3. Bot envía resumen para confirmar.
4. Usuario confirma.
5. Se guarda gasto.

## Campos Obligatorios del Gasto

Campos mínimos para crear una fila en `Expenses`:

- `phone`
- `trip_id`
- `merchant`
- `date`
- `currency`
- `total`
- `category`
- `country`
- `status`

Campos calculados / derivados:

- `expense_id`
- `total_clp`
- `shared`
- `receipt_drive_url` (link del archivo en Google Drive; si falla, se guarda `MediaUrl0` temporal de Twilio)
- `created_at`

## Exchange Rate (Hardcoded)

Archivo objetivo: `utils/exchange_rate.py`

```python
RATES = {
    "USD": 950,
    "PEN": 260,
    "CNY": 130,
    "CLP": 1,
}

def convert_to_clp(amount, currency):
    return amount * RATES.get(currency, 1)
```

## Roadmap de Implementación (orden sugerido)

1. Base de proyecto (`FastAPI` + estructura de carpetas).
2. `README` + `tasks.md` (documentación viva).
3. `sheets_service` con operaciones base.
4. `conversation_service` (state machine mínima).
5. `webhook` Twilio (texto + imagen).
6. `ocr_service` placeholder.
7. `expense_service` + confirmación + persistencia.
8. Gasto compartido 50/50.
9. Integración real con Document AI.
10. Scheduler de recordatorios.

## Estado actual (implementado)

Base funcional mínima ya implementada:

- `FastAPI` con endpoint `GET /health`
- `POST /webhook` para Twilio WhatsApp (form-urlencoded)
- `sheets_service` con operaciones base:
  - `get_employee_by_phone`
  - `get_active_trip_by_phone`
  - `create_expense`
  - `get_conversation`
  - `update_conversation`
- `conversation_service` con state machine básica:
  - `WAIT_RECEIPT`
  - `PROCESSING`
  - `NEEDS_INFO`
  - `CONFIRM_SUMMARY`
  - `DONE`
  - respuestas contextuales de chat en `WAIT_RECEIPT`/`DONE` cuando el mensaje parece pregunta
- `ocr_service` con integración a Google Document AI + fallback conversacional ante error
- `expense_service` con validación de campos y guardado en `Expenses`
- `utils/exchange_rate.py` con conversión hardcoded a CLP
- Script `scripts/seed_sheets.py` para headers + datos demo
- `scheduler_service` MVP para recordatorios automáticos (09:00 / 20:00 hora local del viaje)

### Validación local realizada (2026-02-24)

Se validó el flujo mínimo funcional con Google Sheets real usando `curl` contra `POST /webhook`:

1. Envío de imagen (simulada) -> bot pregunta `category` (`NEEDS_INFO`)
2. Respuesta con opción -> bot muestra resumen (`CONFIRM_SUMMARY`)
3. Confirmación -> gasto guardado en `Expenses` con `status = pending_approval`

También se corrigieron problemas de matching/persistencia por formato de `phone` en Google Sheets y duplicados históricos en `Conversations`.

## Cómo ejecutar (local)

### 1. Instalar dependencias

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configurar variables de entorno

```bash
cp .env.example .env
```

Luego exporta variables desde tu shell (o usa tu gestor de entorno favorito):

```bash
export GOOGLE_APPLICATION_CREDENTIALS=./biaticos-488419-1073823ba21a.json
export GOOGLE_SHEETS_SPREADSHEET_ID=1PgJc4460etPJxx1nSgtC4fGy0RGX85xVc55nm94plrk
export TWILIO_VALIDATE_SIGNATURE=false
```

Nota:

- `TWILIO_VALIDATE_SIGNATURE=false` facilita pruebas locales.
- En producción debe ir en `true`.

### 3. Inicializar hojas y datos demo

```bash
python scripts/seed_sheets.py --clear-data --seed-demo
```

### 4. Levantar API

```bash
uvicorn app.main:app --reload --proxy-headers --forwarded-allow-ips='*'
```

Notas operativas para Twilio Sandbox + `ngrok`:

- Usar `--proxy-headers --forwarded-allow-ips='*'` ayuda a preservar la URL pública al validar firma de Twilio detrás de `ngrok`.
- Si cambias variables de entorno (por ejemplo `TWILIO_VALIDATE_SIGNATURE`), debes reiniciar `uvicorn` manualmente; `--reload` no recarga variables exportadas.
- Si cambia la URL pública de `ngrok`, actualiza la URL del webhook en Twilio Sandbox.

### 5. Probar endpoints

Healthcheck:

```bash
curl http://127.0.0.1:8000/health
```

Simular mensaje de texto (Twilio webhook):

```bash
curl -X POST http://127.0.0.1:8000/webhook \
  -d "From=whatsapp:+56974340422" \
  -d "Body=hola" \
  -d "NumMedia=0"
```

Simular mensaje con imagen (Twilio webhook):

```bash
curl -X POST http://127.0.0.1:8000/webhook \
  -d "From=whatsapp:+56974340422" \
  -d "Body=" \
  -d "NumMedia=1" \
  -d "MediaUrl0=https://example.com/receipt-usd-starbucks.jpg" \
  -d "MediaContentType0=image/jpeg"
```

El endpoint responde `TwiML` (`application/xml`) para que Twilio envíe el mensaje al usuario.

### 5.1. Ejecutar recordatorios automáticos (scheduler MVP)

Se implementó un scheduler MVP disparado por endpoint (pensado para cron/job externo):

- `POST /jobs/reminders/run`
- Evalúa viajes activos y envía:
  - mensaje inicial de inicio de viaje (una vez, al comienzo del viaje)
  - recordatorios a las `09:00` y `20:00` hora local del viaje
- La zona horaria se infiere por `destination` / `country` (con fallback a `DEFAULT_TIMEZONE`)
- Tiene idempotencia básica para no duplicar el mismo recordatorio por viaje/fecha/slot

Prueba sin enviar mensajes reales:

```bash
curl -X POST "http://127.0.0.1:8000/jobs/reminders/run?dry_run=true"
```

Si configuras `SCHEDULER_ENDPOINT_TOKEN`, envía el header:

```bash
curl -X POST "http://127.0.0.1:8000/jobs/reminders/run" \
  -H "X-Scheduler-Token: <tu_token>"
```

Para automatizarlo, configura un cron/job externo que invoque este endpoint cada `5-10` minutos.

#### Automatización con `cron` (macOS/Linux)

Se agregó el script:

- `scripts/run_scheduler_job.sh`
- `scripts/install_scheduler_cron.sh`

Este script:

- carga variables desde `.env` (o `ENV_FILE`)
- llama `POST /jobs/reminders/run`
- envía `X-Scheduler-Token` si existe `SCHEDULER_ENDPOINT_TOKEN`
- soporta `SCHEDULER_DRY_RUN=true`

Prueba manual:

```bash
bash scripts/run_scheduler_job.sh
```

Variables opcionales para el job:

- `SCHEDULER_URL` (default: `http://127.0.0.1:8000/jobs/reminders/run`)
- `SCHEDULER_TIMEOUT_SECONDS` (default: `20`)
- `SCHEDULER_DRY_RUN` (`true|false`, default: `false`)
- `LOG_DIR` (default: `./logs`)

Agregar al `crontab` (cada 5 minutos):

```bash
crontab -e
```

```cron
*/5 * * * * /usr/bin/curl --silent --show-error --fail --max-time 20 -X POST http://127.0.0.1:8000/jobs/reminders/run -H "X-Scheduler-Token: <tu_token>" >> /tmp/mvp_biaticos_scheduler_cron.log 2>&1
```

Instalación automática (idempotente):

```bash
bash scripts/install_scheduler_cron.sh
```

Opcional (frecuencia distinta):

```bash
CRON_EXPR="*/10 * * * *" bash scripts/install_scheduler_cron.sh
```

Opcional (log distinto):

```bash
CRON_LOG_FILE="/tmp/biaticos_scheduler.log" bash scripts/install_scheduler_cron.sh
```

Nota macOS:

- Si el repo está en `Desktop`, `cron` puede fallar con `Operation not permitted`.
- `install_scheduler_cron.sh` evita ese problema usando `curl` directo y log en `/tmp`.

Ver logs:

```bash
tail -f /tmp/mvp_biaticos_scheduler_cron.log
```

### 6. Prueba real con Twilio WhatsApp Sandbox (recomendado)

1. Exponer el backend local:

```bash
ngrok http 8000
```

2. Configurar en Twilio WhatsApp Sandbox:

- `When a message comes in` = `POST https://<tu-url-ngrok>/webhook`

3. Mantener inicialmente:

```bash
export TWILIO_VALIDATE_SIGNATURE=false
```

4. Probar desde WhatsApp real (foto de boleta).

5. Cuando ya esté conectado Twilio, activar seguridad:

```bash
export TWILIO_VALIDATE_SIGNATURE=true
```

Luego reinicia `uvicorn` y vuelve a probar. Si responde `403`, revisa que la URL de `ngrok` configurada en Twilio coincida exactamente con la actual.

## Convenciones de Documentación (obligatorio)

Para mantener trazabilidad del MVP:

- Toda decisión relevante se documenta en `README.md` o `tasks.md`.
- Toda tarea ejecutada debe marcarse en `tasks.md`.
- Toda sesión de trabajo debe agregar una entrada corta en la bitácora.
- Si cambia el flujo, actualizar primero documentación y luego código.

## Bitácora de Proyecto (Log)

### 2026-02-24

- Se consolidó la definición del MVP y arquitectura monolítica modular.
- Se documentó el flujo funcional mínimo (webhook -> conversación -> confirmación -> Google Sheets).
- Se definió la necesidad de `tasks.md` como plan operativo + bitácora de ejecución.
- Se agregó script `scripts/seed_sheets.py` para headers y datos demo de Google Sheets.
- Se implementó el scaffold backend MVP (FastAPI + webhook + servicios base + state machine mínima).
- Se validó localmente el flujo mínimo end-to-end con Google Sheets real.
- Se corrigieron bugs de normalización de teléfonos y consistencia de `Conversations`.

## Próximos Entregables Inmediatos

- Integrar validación real de firma Twilio en entorno de pruebas/productivo.
- Implementar flujo de gasto compartido 50/50.
- Configurar cron/job externo para invocar `POST /jobs/reminders/run` cada 5-10 minutos.
- Afinar mapeo de timezone (especialmente países con múltiples husos horarios, ej. USA).
