# Plan provisional: monitor determinista de trades activos

Estado: propuesta para evaluar; no implementada.

## Respuesta corta

Sí, se puede construir un monitor que cada 15 minutos lea las posiciones abiertas de FBS, obtenga velas de varias temporalidades, aplique reglas deterministas y envíe por Telegram una recomendación como `MANTENER`, `MOVER_SL`, `AJUSTAR_TP`, `CIERRE_PARCIAL` o `CERRAR_TODO`.

La IA puede ayudar a diseñar, probar y mejorar el sistema, pero no es necesaria durante cada ejecución. El punto difícil no es el análisis matemático sino obtener datos fiables del broker y mantener una sesión autenticada. Por eso se propone separar la captura de datos, el motor de reglas y la notificación.

El sistema será inicialmente de solo lectura: no cerrará trades ni modificará SL/TP. Cualquier acción se ejecutará manualmente en FBS.

## Recomendación principal

Usar esta prioridad para adquirir datos:

1. **Puente MT5/MT4 de solo lectura**, preferiblemente un Expert Advisor o proceso junto al terminal que publique posiciones y velas. Es la opción más estable y precisa.
2. **WebTrader con Playwright**, si el portal expone posiciones y velas de forma accesible y estable. El usuario inicia sesión manualmente; el monitor solo navega y lee.
3. **Datos públicos como respaldo**, exclusivamente para estructura de mercado. La cotización ejecutable, el P/L, SL, TP y volumen siempre deben venir de FBS.

No conviene basar un sistema sin IA únicamente en screenshots. Un gráfico puede estar dibujado en `canvas`, y convertir sus píxeles en OHLC y estructura de forma fiable exigiría visión/OCR o procesamiento muy frágil. Si WebTrader no entrega velas en el DOM o en una interfaz estable, el puente MT5 debe ser la fuente de candles.

## Arquitectura propuesta

```text
FBS WebTrader o puente MT5 (solo lectura)
                 |
                 v
      Snapshot estructurado por ticket
                 |
                 v
       Enriquecimiento M15/H1/H4
        + señal original/historial
                 |
                 v
        Motor determinista de reglas
                 |
          +------+------+
          |             |
          v             v
       SQLite       Telegram
     auditoría     acción sugerida
```

### 1. Capturador del broker

Debe producir un snapshot JSON por ejecución con:

- ticket, símbolo, dirección y volumen;
- entrada y hora de apertura;
- Bid/Ask ejecutable según dirección;
- beneficio visible, swap y comisión cuando estén disponibles;
- SL y TP actuales;
- estado de mercado y timestamp del broker;
- candles cerradas M15, H1 y H4, o un error explícito si faltan;
- procedencia exacta de cada campo: `fbs_dom`, `mt5_bridge` o `market_proxy`.

Para un BUY se usa Bid como precio aproximado de cierre; para un SELL se usa Ask.

### 2. Navegador en Codespaces

El prototipo puede usar Chromium y Playwright en modo visible:

- Chromium corre dentro del Codespace.
- Una interfaz noVNC se publica mediante un puerto **privado** del Codespace.
- El usuario abre esa interfaz, inicia sesión manualmente en FBS y completa 2FA/CAPTCHA.
- Playwright reutiliza un perfil persistente local, ignorado por Git.
- El monitor se limita mediante una allowlist al dominio oficial de FBS/WebTrader.
- Los selectores permitidos solo abren posiciones, símbolos, gráficos y temporalidades.
- Se bloquean explícitamente `New Order`, `Modify`, `Close`, cambios de volumen, SL, TP, depósitos y retiros.

El perfil del navegador no debe contener contraseñas en archivos de configuración ni entrar al repositorio. Cookies y datos de sesión deben guardarse en un directorio privado con permisos restrictivos y una entrada específica en `.gitignore`.

Antes de depender del navegador hay que hacer un spike con una cuenta demo para confirmar:

- si la tabla de posiciones puede leerse por DOM;
- si Bid/Ask, SL, TP y P/L tienen selectores estables;
- si los candles están disponibles como datos y no solo como píxeles;
- si cambiar M15/H1/H4 mantiene selectores deterministas;
- cuánto dura la sesión y cómo se detecta un logout;
- si la automatización está permitida por los términos aplicables del servicio.

No se usará una API o WebSocket privado no documentado sin revisar antes estabilidad, autorización y términos.

### 3. Enriquecimiento e historial

El historial local es útil pero no obligatorio para el primer MVP.

Primero se intentará enlazar el ticket con:

- `sessions/*/telegram-fbs-candidates.json`;
- `sessions/*/session-report.md`;
- `sessions/idea-ledger.json`.

El enlace debe usar símbolo, dirección, entrada, hora e idea ID cuando exista. De allí se recuperan SL/TP originales, R inicial, temporalidad, tesis y vencimiento. Si no hay coincidencia, el monitor analiza la posición actual sin inventar una tesis original y marca `unmatched`.

SQLite conservará cada snapshot y decisión para medir MFE, MAE, tiempo sin progreso, cambios de SL/TP, alertas ya enviadas y resultado posterior.

### 4. Motor de análisis sin IA

El motor trabajará únicamente con valores estructurados y candles cerradas. Debe calcular:

- edad exacta del trade;
- P/L en dinero, pips y R;
- progreso hacia TP;
- riesgo restante hasta SL y recompensa restante hasta TP;
- MFE y retroceso desde MFE;
- spread actual frente a su mediana reciente;
- ATR y distancia de SL/TP en ATR;
- swings confirmados y secuencia HH/HL o LH/LL;
- ruptura, retesteo, fallo de ruptura y cierre de vela contra la tesis;
- pendiente y alineación de M15/H1/H4;
- proximidad a rollover, cierre semanal y noticias configuradas;
- tiempo sin nuevos máximos/mínimos favorables.

La clasificación inicial reutilizará la política de `active-trade-manager`, pero cada regla tendrá parámetros configurables y evidencia auditable.

Ejemplos de reglas candidatas, todavía sujetas a backtest:

- `MANTENER`: estructura y tesis intactas, spread normal y recompensa restante adecuada.
- `MOVER_SL`: avance significativo más swing cerrado que permita reducir riesgo sin meter el stop dentro del ruido normal.
- `AJUSTAR_TP`: obstáculo estructural nuevo o tiempo restante insuficiente; el TP solo puede acercarse.
- `CIERRE_PARCIAL`: beneficio significativo, riesgo claro de reversión y volumen compatible con el paso de lote verificado.
- `CERRAR_TODO`: invalidación confirmada, expiración, deterioro fuerte de expectativa, noticia/rollover prohibido o cierre semanal cercano.
- `EVIDENCIA_INSUFICIENTE`: datos del broker desactualizados, sesión cerrada, velas incompletas o campos críticos ausentes.

Restricciones duras:

- nunca ampliar el riesgo;
- nunca alejar el TP para perseguir precio;
- nunca promediar pérdidas ni sugerir reentrada desde este monitor;
- nunca decidir con una candle aún abierta como única confirmación;
- no reaccionar al spread anormal como si fuera movimiento real del subyacente;
- si una recomendación no cambia, no repetirla cada 15 minutos salvo recordatorio crítico;
- toda recomendación debe indicar ticket, acción, nivel exacto, razones, confianza y edad de los datos.

Los umbrales definitivos no deben elegirse por intuición. Se calibrarán con replay de operaciones y se validarán fuera de muestra antes de usar una cuenta real.

### 5. Programador y estado

Un runner ejecutará el ciclo alineado a cierres de M15:

1. comprobar sesión y frescura;
2. capturar posiciones y candles;
3. enlazar señal original e historial;
4. ejecutar reglas;
5. validar que la acción no aumente riesgo;
6. persistir snapshot y decisión;
7. publicar Telegram solo si corresponde.

Debe incluir lock para impedir ejecuciones solapadas, timeout por etapa, un solo retry para fallos transitorios, circuit breaker tras fallos repetidos y heartbeat separado. Un logout, selector roto o quote viejo produce alerta operativa, nunca una recomendación inventada.

Durante desarrollo puede ejecutarse con un bucle supervisado. En despliegue conviene un servicio `systemd` con timer o un contenedor reiniciable; cron también sirve, pero ofrece menos supervisión.

### 6. Telegram

Se reutilizará `.env.telegram` y el publicador existente cuando sea compatible. Habrá tres clases de mensaje:

- `ACCIÓN`: cambió la acción o el nivel recomendado;
- `RIESGO`: news, rollover, cierre semanal, spread o sesión degradada;
- `SISTEMA`: login vencido, datos viejos o monitor caído.

El mensaje será idempotente por `ticket + action + levels + candle_close`, evitando spam.

## Codespaces: alcance real

Codespaces sirve bien para desarrollar y probar el monitor, y podría usarse durante una sesión supervisada. No es el host ideal para vigilancia permanente:

- se detiene por inactividad; el valor predeterminado es 30 minutos y la configuración personal admite hasta 240 minutos;
- cuando el Codespace se detiene, todos sus procesos se detienen;
- mantenerlo activo consume cómputo;
- una reconstrucción elimina cambios fuera de `/workspaces`;
- el login del navegador puede expirar o requerir intervención.

Para sesiones de trading de hasta cuatro horas, se puede iniciar manualmente el Codespace, abrir el navegador privado, hacer login y arrancar el monitor. Para cobertura continua o nocturna, desplegar el mismo código en un VPS pequeño o junto a MT5 es más fiable.

No se diseñará un mecanismo artificial para evitar el timeout de Codespaces. El despliegue deberá respetar su ciclo de vida y costos.

## Fases de implementación

### Fase 0 — Spike técnico en demo

- Crear navegador aislado con Playwright y noVNC.
- Login exclusivamente manual.
- Leer una tabla de posiciones y cambiar M15/H1/H4 sin tocar controles de trading.
- Guardar un snapshot de prueba sin secretos.
- Determinar si WebTrader entrega candles estructuradas.

Criterio de salida: captura repetible de todos los campos críticos durante al menos una hora y cero clics sobre controles mutables.

### Fase 1 — MVP de solo lectura

- Implementar esquema de snapshots y SQLite.
- Calcular edad, pips, R, progreso, spread y estructura básica.
- Implementar `MANTENER`, `MOVER_SL`, `CERRAR_TODO` y `EVIDENCIA_INSUFICIENTE`.
- Ejecutar manualmente y publicar Telegram en modo demo.

Criterio de salida: decisiones reproducibles para snapshots conocidos y tests que rechacen cualquier cambio que aumente riesgo.

### Fase 2 — Scheduler y resiliencia

- Ejecutar cada cierre M15.
- Añadir locks, heartbeat, deduplicación, recuperación de sesión y alertas técnicas.
- Incorporar señal original e historial local.

Criterio de salida: una sesión demo completa sin intervención salvo login y sin alertas duplicadas.

### Fase 3 — Calibración

- Reproducir operaciones históricas sin mirar resultados futuros.
- Comparar reglas contra mantener SL/TP originales.
- Medir expectativa, drawdown, beneficio protegido, salidas prematuras y falsos cierres.
- Congelar configuración versionada.

Criterio de salida: métricas aceptables definidas antes del ensayo y evaluación fuera de muestra.

### Fase 4 — Piloto real, aún informativo

- Desplegar en VPS o entorno estable.
- Mantener toda acción manual en FBS.
- Auditar snapshots y recomendaciones diariamente.
- Añadir `AJUSTAR_TP` y `CIERRE_PARCIAL` solo después de verificar paso mínimo de lote y comportamiento del broker.

No se contempla ejecución automática de órdenes en este plan.

## Estructura tentativa del repositorio

```text
active-trade-monitor/
  config.example.yaml
  browser/
    launch.py
    fbs_reader.py
    selectors.yaml
  broker/
    models.py
    mt5_bridge_reader.py
  analysis/
    indicators.py
    structure.py
    policy_engine.py
  storage/
    repository.py
  notify/
    telegram.py
  monitor.py
  tests/
```

Los nombres son provisionales. Antes de crear módulos nuevos se revisará qué código de `active-trade-manager` y `trading-session` puede reutilizarse.

## Decisiones pendientes antes de implementar

1. Confirmar si la cuenta y WebTrader son MT4 o MT5.
2. Elegir el origen preferido: puente MT5 o Playwright WebTrader.
3. Definir si el primer piloto corre solo durante sesiones manuales de hasta cuatro horas o requiere VPS desde el comienzo.
4. Acordar una cuenta demo para la Fase 0.
5. Confirmar que el alcance seguirá siendo recomendación y Telegram, sin ejecución automática.
6. Definir instrumentos y temporalidades iniciales; propuesta: forex en M15/H1/H4.
7. Definir una fuente permitida para calendario económico si se incorpora al MVP.

## Referencias de diseño

- FBS ofrece WebTrader en navegador y temporalidades/indicadores: <https://fbs.com/trading/metatrader-4/mt4-web>
- FBS describe MT5 y Expert Advisors: <https://fbs.com/trading/metatrader-5>
- GitHub documenta el ciclo de vida y parada de Codespaces: <https://docs.github.com/en/codespaces/about-codespaces/understanding-the-codespace-lifecycle>
- GitHub documenta un máximo personal de cuatro horas para el idle timeout: <https://docs.github.com/en/codespaces/setting-your-user-preferences/setting-your-timeout-period-for-github-codespaces>
- OpenAI recomienda Playwright/Selenium, navegador aislado, allowlists y supervisión humana para flujos autenticados o de alto impacto: <https://developers.openai.com/api/docs/guides/tools-computer-use>
