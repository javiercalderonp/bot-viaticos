# Tasks - Travel Expense AI Agent (MVP)

Documento operativo para ejecutar el MVP paso a paso.

Objetivo de este archivo:

- Definir tareas concretas y ordenadas.
- Marcar estado de avance.
- Registrar decisiones y resultados por sesión.
- Servir como fuente de verdad de ejecución junto al `README.md`.

## Reglas de uso (importante)

- Antes de implementar una funcionalidad, revisar `README.md`.
- Al iniciar una sesión, elegir las tareas a trabajar y marcarlas `in progress`.
- Al terminar, actualizar estado (`done` / `blocked`) y agregar log.
- Si cambia el alcance o flujo, actualizar `README.md` primero.

## Estados

- `[ ]` Pendiente
- `[-]` En progreso
- `[x]` Completada
- `[!]` Bloqueada

## Fase 0 - Documentación y alineación

- [x] Consolidar objetivo, alcance MVP y stack tecnológico
- [x] Documentar arquitectura deseada (monolito modular)
- [x] Documentar estructura de Google Sheets como DB
- [x] Documentar flujo técnico del webhook
- [x] Crear `tasks.md` con checklist y bitácora

## Fase 1 - Bootstrap del proyecto (FastAPI)

- [x] Crear estructura de carpetas `app/`, `services/`, `utils/`
- [x] Crear `app/main.py` con instancia FastAPI y endpoint healthcheck
- [x] Crear `app/config.py` con settings por variables de entorno
- [x] Definir archivo de dependencias (`requirements.txt` o equivalente)
- [x] Agregar `.env.example` con variables necesarias

## Fase 2 - Integración base de Google Sheets (simulación DB)

- [ ] Implementar `services/sheets_service.py`
- [x] Implementar `services/sheets_service.py`
- [x] Definir headers esperados por hoja (`Employees`, `Trips`, `Expenses`, `Conversations`)
- [x] Crear script `scripts/seed_sheets.py` para inicializar headers y poblar datos demo
- [x] Implementar `get_employee_by_phone(phone)`
- [x] Implementar `get_active_trip_by_phone(phone)`
- [x] Implementar `create_expense(expense_data)`
- [x] Implementar `update_conversation(phone, payload)`
- [x] Implementar `get_conversation(phone)` (recomendado para flujo)

## Fase 3 - Utilidades y placeholders

- [x] Crear `utils/exchange_rate.py` con `RATES` y `convert_to_clp`
- [x] Crear `utils/helpers.py` (phone normalization, timestamp, parse helpers)
- [x] Crear `services/ocr_service.py` placeholder (sin integración real aún)
- [x] Crear `services/whatsapp_service.py` base (respuesta texto / validación Twilio placeholder)

## Fase 4 - State machine conversacional (MVP mínimo)

- [x] Implementar estados `WAIT_RECEIPT`, `PROCESSING`, `NEEDS_INFO`, `CONFIRM_SUMMARY`, `DONE`
- [x] Definir estructura de `context_json` para draft de gasto
- [x] Implementar validación de campos obligatorios
- [x] Implementar slot filling (preguntar campo faltante)
- [x] Implementar confirmación (`Confirmar`, `Corregir`, `Cancelar`)
- [x] Persistir gasto confirmado en `Expenses`

## Fase 5 - Endpoint `/webhook` Twilio (flujo funcional mínimo)

- [x] Crear endpoint `POST /webhook`
- [x] Parsear payload de Twilio (`From`, `Body`, `NumMedia`, `MediaUrl0`)
- [x] Identificar empleado por teléfono
- [x] Manejar flujo imagen (OCR -> validación -> transición de estado)
- [x] Manejar flujo texto (leer estado -> avanzar step)
- [x] Responder texto adecuado al usuario

## Fase 5.1 - WhatsApp/Twilio producción (branding y perfil profesional)

- [ ] Migrar de Twilio WhatsApp Sandbox a WhatsApp Sender de producción
- [ ] Configurar/vincular cuenta de Meta Business (si aplica)
- [ ] Definir y aprobar `Display Name` del negocio en WhatsApp
- [ ] Configurar foto de perfil (logo) y datos de perfil de empresa
- [ ] Actualizar webhook del sender productivo y validar E2E
- [ ] Definir templates de WhatsApp para mensajes proactivos (recordatorios del scheduler)

## Fase 6 - Gasto compartido 50/50 (MVP)

- [ ] Preguntar si gasto fue compartido
- [ ] Pedir teléfono del otro colaborador
- [ ] Dividir monto 50/50
- [ ] Crear dos filas en `Expenses` con `shared = true`
- [ ] Validar caso colaborador no encontrado (mensaje de error / retry)

## Fase 7 - Integración real OCR (post-MVP mínimo)

- [x] Configurar cliente Google Document AI
- [x] Procesar imagen desde URL / descarga temporal
- [x] Mapear output OCR a campos `merchant/date/total/currency/country`
- [x] Manejar errores de OCR y fallback conversacional

## Fase 7.1 - Inferencia de merchant + clasificación automática (LLM híbrido)

- [x] Implementar clasificación de categoría con LLM (OpenAI) como opcional
- [x] Implementar inferencia de `merchant` con LLM cuando OCR venga vacío/genérico
- [x] Implementar inferencia de `country` y `currency` con LLM desde `ocr_text`
- [x] Priorizar ciudad/dirección de la boleta sobre el nombre del comercio para inferir país (ej. `MISTURA DEL PERU` + `Santiago` => `Chile`)
- [x] Mantener fallback a reglas locales si LLM no está configurado o falla
- [x] Integrar inferencia en flujo conversacional antes de preguntar `category`
- [x] Documentar variables de entorno y setup en `README.md` / `.env.example`

## Fase 7.2 - Chat contextual (LLM) para preguntas de usuario

- [x] Implementar respuesta contextual para preguntas generales del flujo (FAQ operativa)
- [x] Definir contexto base del MVP para evitar respuestas fuera de alcance
- [x] Activar/desactivar por variable `CHAT_ASSISTANT_ENABLED`
- [x] Integrar respuesta contextual en estados `WAIT_RECEIPT` y `DONE`
- [x] Mantener continuidad del slot filling en `NEEDS_INFO` después de responder la pregunta
- [x] Exponer diagnóstico en `GET /health` (`chat_assistant_flag`, `chat_assistant_enabled`)
- [x] Actualizar `README.md` y `.env.example` con configuración y comportamiento

## Fase 8 - Scheduler (posterior)

- [x] Definir estrategia: cron externo + endpoint interno `POST /jobs/reminders/run`
- [x] Configurar cron/job externo para invocar `POST /jobs/reminders/run` cada 5-10 minutos
- [x] Implementar recordatorio automático 09:00 local del viaje
- [x] Implementar recordatorio automático 20:00 local del viaje
- [x] Enviar mensaje inicial de inicio de viaje (presentación + instrucciones breves)
- [x] Adaptar horario según zona horaria del viaje (`country`/`destination`, con fallback)
- [x] Evitar envíos duplicados (idempotencia básica en `Conversations.context_json.scheduler`)

## Decisiones abiertas (por resolver)

- [x] Elegir formato de configuración (`pydantic-settings` vs env manual)
- [x] Definir librería Google Sheets (`gspread` recomendado)
- [x] Definir estrategia local para validar firma Twilio (toggle por env)
- [x] Definir formato de `expense_id` (UUID vs timestamp)
- [x] Definir criterio si un usuario tiene más de un viaje activo

## Checklist de sesión (usar siempre)

- [x] Revisé `README.md` antes de implementar
- [x] Actualicé `tasks.md` al iniciar
- [x] Actualicé `README.md` si hubo cambios de flujo/arquitectura
- [x] Agregué entrada en bitácora al cerrar sesión

## Bitácora de ejecución (logs)

### 2026-02-24 - Setup documental

- Estado: `done`
- Trabajo realizado:
  - Se reescribió `README.md` con arquitectura, alcance MVP, flujos y modelo en Google Sheets.
  - Se creó `tasks.md` con roadmap por fases, checklist operativo y decisiones abiertas.
- Próximo paso sugerido:
  - Iniciar Fase 1 (bootstrap FastAPI + estructura base).

### 2026-02-24 - Script de inicialización Google Sheets

- Estado: `done`
- Trabajo realizado:
  - Se agregó `scripts/seed_sheets.py` para asegurar hojas, escribir headers y cargar datos demo.
  - Se documentó el uso del script y el `Spreadsheet ID` en `README.md`.
- Bloqueos / riesgos:
  - Requiere compartir el spreadsheet con el `client_email` del Service Account.
  - Requiere instalar `gspread` y `google-auth`.
- Próximo paso sugerido:
  - Ejecutar script y validar que las 4 hojas queden con headers correctos.

### 2026-02-24 - Scaffold backend MVP (FastAPI + webhook)

- Estado: `done`
- Trabajo realizado:
  - Se creó estructura `app/`, `services/`, `utils/` y paquetes Python.
  - Se implementó `app/main.py` con `GET /health` y `POST /webhook`.
  - Se implementaron servicios base: `sheets`, `travel`, `ocr` placeholder, `expense`, `conversation`, `whatsapp`.
  - Se agregó `requirements.txt` y `.env.example`.
  - Se agregó `.gitignore` para excluir credenciales (`*.json` de service account local).
  - Se verificó sintaxis de módulos Python (`py_compile`).
- Bloqueos / riesgos:
  - No se probó end-to-end con Twilio ni Google Sheets en esta sesión.
  - `ocr_service` sigue en modo placeholder.
- Próximo paso sugerido:
  - Ejecutar `scripts/seed_sheets.py`, levantar FastAPI y probar `/webhook` localmente.

### 2026-02-24 - Fix de matching de teléfono en Google Sheets

- Estado: `done`
- Trabajo realizado:
  - Se reforzó normalización de teléfonos para soportar valores numéricos/float leídos desde Google Sheets.
  - Se cambió comparación de `phone` en `Employees`, `Trips` y `Conversations` a formato normalizado.
  - Se ajustó `scripts/seed_sheets.py` para escribir seeds en modo `RAW` y preservar el prefijo `+`.
- Bloqueos / riesgos:
  - Las filas ya cargadas pueden seguir viéndose como número en la hoja, pero el backend ahora debería resolverlo.
- Próximo paso sugerido:
  - Reintentar el webhook de imagen y validar transición de estado.

### 2026-02-24 - Fix upsert/get de Conversations + validación E2E local

- Estado: `done`
- Trabajo realizado:
  - Se corrigió `update_conversation` para actualizar la última fila coincidente por `phone` (evitando problemas con duplicados históricos).
  - Se corrigió `get_conversation` para seleccionar la conversación más reciente según `updated_at`.
  - Se validó flujo mínimo completo en local con `curl`:
    - imagen -> `NEEDS_INFO` (pregunta categoría)
    - respuesta categoría -> `CONFIRM_SUMMARY`
    - confirmación -> guardado en `Expenses` con `pending_approval`
- Bloqueos / riesgos:
  - OCR sigue en placeholder (datos simulados).
  - Aún no validado con Twilio/WhatsApp real.
- Próximo paso sugerido:
  - Integrar `ngrok` y configurar Twilio Sandbox para prueba real por WhatsApp.

### 2026-02-24 - Validación E2E real con Twilio Sandbox + WhatsApp

- Estado: `done`
- Trabajo realizado:
  - Se levantó FastAPI local y se validó `GET /health` con `sheets_enabled=true`.
  - Se instaló y configuró `ngrok` para exponer `http://localhost:8000`.
  - Se configuró el webhook del Twilio WhatsApp Sandbox apuntando a `POST https://<ngrok>/webhook`.
  - Se probó envío real desde WhatsApp con foto y el flujo respondió correctamente.
- Bloqueos / riesgos:
  - La URL de `ngrok` cambia entre sesiones y exige actualizar la URL del Sandbox.
  - Si se activa `TWILIO_VALIDATE_SIGNATURE=true` con URL distinta a la configurada en Twilio, el webhook responderá `403`.
- Próximo paso sugerido:
  - Activar validación de firma Twilio y revalidar una prueba real.
  - Luego avanzar a Fase 6 (gasto compartido 50/50) o Fase 7 (OCR real).

### 2026-02-24 - Fase 7 OCR real con Google Document AI

- Estado: `done`
- Trabajo realizado:
  - Se reemplazó el placeholder de `services/ocr_service.py` por integración real con Google Document AI usando `process_document`.
  - Se agregó descarga de imagen desde `MediaUrl0` (Twilio) con soporte de Basic Auth usando `TWILIO_ACCOUNT_SID` y `TWILIO_AUTH_TOKEN`.
  - Se implementó mapeo flexible de entidades OCR a `merchant`, `date`, `total`, `currency`, `country` con heurísticas de fallback.
  - Se agregó manejo de error de OCR en `POST /webhook` para continuar con slot filling manual.
  - Se actualizó `requirements.txt` y `.env.example` para habilitar la configuración de OCR real.
- Bloqueos / riesgos:
  - Falta validar E2E con un processor real de Document AI y boletas reales.
  - El mapeo de entidades puede requerir ajustes según el tipo exacto de processor (Invoice/Expense/Custom).
- Próximo paso sugerido:
  - Instalar dependencias (`google-cloud-documentai`) y probar con una boleta real por WhatsApp.
  - Ajustar aliases de entidades según el output real del processor configurado.

### 2026-02-25 - Clasificación automática de categoría con LLM (OpenAI) + fallback

- Estado: `done`
- Trabajo realizado:
  - Se agregó `services/llm_service.py` para clasificar `category` usando OpenAI (`Meals`, `Transport`, `Lodging`, `Other`).
  - Se integró la clasificación al `ExpenseService` con fallback a reglas locales por keywords.
  - Se conectó el servicio en `app/main.py` y se agregaron variables `OPENAI_*` / `EXPENSE_CATEGORY_LLM_ENABLED` en `app/config.py`.
  - Se actualizó `.env.example` y `README.md` con setup y recomendaciones de arquitectura híbrida (OCR + LLM).
- Bloqueos / riesgos:
  - Falta validación E2E con red real y una `OPENAI_API_KEY` válida.
  - El modelo por defecto (`gpt-4o-mini`) es configurable por env si se prefiere otro.
- Próximo paso sugerido:
  - Activar `EXPENSE_CATEGORY_LLM_ENABLED=true`, configurar `OPENAI_API_KEY` y probar con boletas reales.
  - Revisar/expandir prompts y ejemplos si aparecen errores de clasificación en comercios locales.

### 2026-02-26 - LLM para inferir merchant (fallback sobre OCR) + diagnóstico

- Estado: `done`
- Trabajo realizado:
  - Se extendió `services/llm_service.py` para inferir `merchant` desde `ocr_text` + pistas OCR.
  - Se integró en `ExpenseService` para reemplazar merchants genéricos (`COMPROBANTE DE VENTA`, `BOLETA`, etc.) cuando el LLM esté disponible.
  - Se mejoró OCR para filtrar merchants genéricos y adjuntar `ocr_text` al draft.
  - Se agregaron señales de diagnóstico en `GET /health` y logs de fuente (`llm`, `rules`, `none`) para merchant/categoría.
  - Se actualizó `README.md` con el flujo híbrido actualizado y guía de diagnóstico.
- Bloqueos / riesgos:
  - La calidad final depende del texto OCR extraído por Document AI; si el OCR viene muy ruidoso, GPT puede inferir mal.
  - Puede requerir ajustar prompts por país/formato de boleta.
- Próximo paso sugerido:
  - Probar 5-10 boletas reales y registrar casos donde `merchant` o `category` salgan incorrectos para refinar prompt/heurísticas.

### 2026-02-26 - LLM para inferir país/moneda + prioridad por ciudad/dirección

- Estado: `done`
- Trabajo realizado:
  - Se extendió `services/llm_service.py` para inferir `country` y `currency` desde `ocr_text` + pistas OCR.
  - Se integró en `ExpenseService` para enriquecer el draft antes de validar faltantes y antes de clasificar `category`.
  - Se reforzó el prompt para priorizar ciudad/dirección/sucursal de la boleta por sobre el nombre del comercio cuando hay conflicto.
  - Se agregó ejemplo explícito de conflicto (`MISTURA DEL PERU` + `Santiago` => `Chile` / `CLP`) en el prompt.
  - Se actualizó `README.md` con el flujo híbrido y logs de inferencia de país/moneda.
- Bloqueos / riesgos:
  - La precisión sigue dependiendo de que el OCR capture correctamente ciudad/dirección.
  - En países con múltiples monedas aceptadas en comercios, la boleta puede no reflejar moneda local típica.
- Próximo paso sugerido:
  - Probar boletas reales con nombres de comercio “ambiguos” (referencias a otros países) y ajustar prompt si aparecen falsos positivos.

## Plantilla de log (copiar por sesión)

```md
### YYYY-MM-DD - Título corto

- Estado: `done` | `partial` | `blocked`
- Trabajo realizado:
  - ...
- Bloqueos / riesgos:
  - ...
- Próximo paso sugerido:
  - ...
```

### 2026-02-26 - Scheduler MVP de recordatorios por timezone local

- Estado: `done`
- Trabajo realizado:
  - Se implementó `services/scheduler_service.py` con recordatorios automáticos por viaje activo a las `09:00` y `20:00` hora local del destino.
  - Se agregó resolución de zona horaria por `destination`/`country` (con fallback a `DEFAULT_TIMEZONE`).
  - Se agregó idempotencia básica persistida en `Conversations.context_json.scheduler.sent_reminders`.
  - Se expuso `POST /jobs/reminders/run` (soporta `dry_run` y token opcional por header `X-Scheduler-Token`).
  - Se habilitó envío saliente WhatsApp por Twilio desde `WhatsAppService`.
- Bloqueos / riesgos:
  - Falta configurar el cron/job externo para ejecutar el endpoint automáticamente.
  - La inferencia de timezone por país puede ser imprecisa en países con múltiples husos horarios (ej. USA).
- Próximo paso sugerido:
  - Configurar un cron cada 5-10 minutos y validar `dry_run` + envío real con 1 viaje demo.

### 2026-02-26 - Validación local scheduler (dry_run + envío real Twilio)

- Estado: `done`
- Trabajo realizado:
  - Se validó `GET /health` con configuración de scheduler cargada por `.env`.
  - Se probó `POST /jobs/reminders/run?dry_run=true` con timezone local del viaje (`Lima`) y respuesta `due=false` fuera de ventana horaria.
  - Se ajustó temporalmente `.env` para prueba local (`SCHEDULER_MORNING_HOUR_LOCAL=15`, `SCHEDULER_REMINDER_WINDOW_MINUTES=60`) y se validó `due=true`.
  - Se ejecutó `POST /jobs/reminders/run` (real) con `X-Scheduler-Token` y Twilio respondió `status=queued`.
  - Se restauró `.env` a horario operativo (`09:00` / `20:00`, ventana `10` min) y se mejoró copy de recordatorios (tono más cercano + emoji).
  - Se agregó mensaje inicial de inicio de viaje (presentación del agente + instrucciones breves) con envío único e idempotente.
- Bloqueos / riesgos:
  - Falta automatizar la ejecución con cron/job externo (actualmente trigger manual por `curl`).
  - La idempotencia quedó implementada, pero conviene validarla explícitamente con una segunda ejecución inmediata en la misma ventana.
- Próximo paso sugerido:
  - Configurar cron/job externo y hacer una prueba de idempotencia (`skipped_already_sent`) en ventana activa.

### 2026-02-27 - Automatización scheduler con cron externo (cada 5 min)

- Estado: `done`
- Trabajo realizado:
  - Se agregó `scripts/run_scheduler_job.sh` para invocar `POST /jobs/reminders/run` con soporte de `.env`, token y `dry_run`.
  - Se agregó `scripts/install_scheduler_cron.sh` para instalar/actualizar el `crontab` de forma idempotente.
  - Se ajustó instalación para usar `curl` directo + log en `/tmp` y evitar error `Operation not permitted` de `cron` en repos dentro de `Desktop` (macOS).
  - Se documentó en `README.md` la ejecución manual, variables opcionales y línea exacta de `crontab` (cada 5 minutos).
  - Se agregaron variables opcionales del job en `.env.example` (`SCHEDULER_URL`, `SCHEDULER_TIMEOUT_SECONDS`, `SCHEDULER_DRY_RUN`, `LOG_DIR`).
- Bloqueos / riesgos:
  - El cron depende de que la API esté levantada y accesible en la URL configurada.
  - Si `SCHEDULER_ENDPOINT_TOKEN` cambia y no se actualiza en el entorno del cron, responderá `401`.
- Próximo paso sugerido:
  - Validar ejecución en ventana activa con `tail -f /tmp/mvp_biaticos_scheduler_cron.log` y revisar idempotencia (`skipped_already_sent`).

### 2026-02-27 - Chat contextual con LLM (FAQ operativa en WhatsApp)

- Estado: `done`
- Trabajo realizado:
  - Se agregó respuesta contextual para preguntas de usuario en el flujo conversacional (ej. "como se manda una boleta").
  - Se incorporó un contexto base del MVP para acotar respuestas del modelo a capacidades reales del sistema.
  - Se agregó configuración por env `CHAT_ASSISTANT_ENABLED` y diagnóstico en `GET /health`.
  - Se mantuvo el comportamiento de negocio del flujo de boletas y slot filling sin regresiones de estado.
  - Se actualizó documentación en `README.md` y `.env.example`.
- Bloqueos / riesgos:
  - Si `OPENAI_API_KEY` no está configurada o falla la red/API, el asistente contextual se desactiva en runtime y cae al mensaje guía.
  - El contexto base está hardcodeado; si cambia el producto, conviene mantenerlo sincronizado.
- Próximo paso sugerido:
  - Extraer el contexto base a archivo/config editable para ajustar copy sin tocar código.
