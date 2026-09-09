# Estrategia paralela: carry mensual

Estado: habilitada solo para prueba demo. No reemplaza la sesión intradía.

## Regla operativa fija

- Evalúa 15 pares FX una vez por mes.
- Usa tasas OECD publicadas por FRED con 45 días de retraso para evitar usar información futura.
- Descarta una moneda si su serie lleva más de 180 días sin actualizarse.
- Exige al menos 1 punto porcentual de diferencia entre las dos monedas.
- Elige un solo par: el de mayor diferencial; compra la moneda de tasa más alta y vende la de tasa más baja.
- La señal se calcula al cierre del primer día hábil y la entrada solo se habilita el segundo día hábil del mes.
- Entrada a mercado, stop a 1.5 ATR diario, objetivo 1R y salida máxima a los 20 días hábiles.
- Riesgo demo objetivo: USD 50, correspondiente al perfil x10 solicitado. El lote cambia según la distancia al stop.
- Antes de abrir hay que confirmar en FBS bid/ask, spread, especificación del contrato y swap long/short.
- Nunca se crean tres cards: la extensión a tres posiciones no superó la validación con suficiente robustez.

El botón `Carry mensual` puede pulsarse cualquier día. Fuera de la ventana correcta devuelve `NO TRADE` y la fecha aproximada de la próxima revisión. Esto evita fabricar una entrada tardía que no fue la probada históricamente.

## Gestión

La card usa el mismo control `Administrar trade` del resto del panel. El monitor conserva SL y TP originales, no cierra el viernes ni reacciona al ruido intradía, y solicita cierre al cumplir 20 días hábiles. El sistema informa; nunca ejecuta una orden en FBS.

## Evidencia que justificó la prueba demo

En la validación cronológica reservada obtuvo 37 operaciones, 24 positivas, +10.73R, profit factor 1.88 y drawdown máximo de 3.03R. Con costes duplicados mantuvo +10.39R. Es evidencia para forward test demo, no garantía de rentabilidad futura.
