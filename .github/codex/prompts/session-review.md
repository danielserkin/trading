Revisa los artefactos de la sesión de trading ubicados bajo `session-artifacts/`.

Comprueba los tres slots seleccionados contra los candidatos, metadata y reporte. Evalúa solamente:

- que cada candidato tenga activo distinto, dirección, entrada, SL, TP, R/R, riesgo y vigencia;
- que el precio y la estructura no estén marcados como desactualizados o inválidos;
- que una oportunidad derivada no sea atribuida falsamente a un experto;
- que no exista ninguna instrucción para ejecutar órdenes automáticamente;
- que Telegram tenga un estado explícito.

No modifiques archivos, no ejecutes nuevamente la sesión y no publiques mensajes. Devuelve únicamente el objeto JSON solicitado por el schema. Si faltan datos, marca `needs_attention` y explica los problemas de forma breve en español.
