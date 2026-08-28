# Trading Control: puesta en marcha

## Qué queda desplegado

- **GitHub Pages** sirve la interfaz estática de `site/`.
- **Cloudflare Worker** protege el panel con un PIN, inicia workflows y dispara el seguimiento cada 15 minutos.
- **GitHub Actions** ejecuta la sesión existente, la revisión no interactiva de Codex y el monitor determinista.
- La rama `runtime-data` conserva cards, eventos y seguimientos para que continúen aunque se cierre el navegador.

No hay un servidor propio ni órdenes automáticas en FBS. El monitor consulta proxies públicos, recomienda una acción y la publica en Telegram; la ejecución y confirmación siguen siendo manuales.

## Secretos que hay que crear en GitHub

Ruta: **Settings → Secrets and variables → Actions → New repository secret**.

| Secreto | Uso |
| --- | --- |
| `OPENAI_API_KEY` | Revisión no interactiva con Codex. |
| `TELEGRAM_API_ID` | Lectura de canales con la sesión existente de Telegram. |
| `TELEGRAM_API_HASH` | Lectura de canales con la sesión existente de Telegram. |
| `TELEGRAM_SESSION_GZIP_B64` | Sesión `telegram-fbs.session` comprimida y codificada para respetar el límite de GitHub Secrets. |
| `TELEGRAM_BOT_TOKEN` | Publicación de la sesión y del seguimiento. Debe ser un token nuevo y rotado. |
| `TELEGRAM_TARGET_CHAT_ID` | Canal privado de destino. |
| `CLOUDFLARE_API_TOKEN` | Despliegue del Worker; permiso de edición de Workers Scripts. |
| `CLOUDFLARE_ACCOUNT_ID` | Cuenta donde se desplegará el Worker. |
| `WORKER_GITHUB_TOKEN` | Token fine-grained limitado a este repositorio, con **Contents: Read and write**. |
| `APP_PIN` | Clave larga para entrar al panel; usar al menos 16 caracteres. |
| `APP_SESSION_SECRET` | Clave aleatoria usada para firmar sesiones temporales del navegador. |

Generación local recomendada:

```bash
openssl rand -hex 32
gzip -9c telegram-fbs.session | base64 -w0
```

Cada salida se carga directamente en su secreto correspondiente. No debe copiarse a archivos versionados ni a mensajes.

## Ajustes únicos del repositorio

1. En **Settings → Actions → General → Workflow permissions**, habilitar **Read and write permissions**.
2. En **Settings → Pages → Build and deployment**, seleccionar **GitHub Actions**.
3. Ejecutar manualmente **Initialize dashboard state** una vez si la rama `runtime-data` todavía no existe.
4. Ejecutar **Deploy control Worker** y copiar la URL `https://...workers.dev` resultante.
5. Abrir GitHub Pages, pulsar el engranaje e ingresar esa URL y `APP_PIN`.

Desde ese momento, **Nueva sesión** dispara el flujo sin aprobaciones interactivas. Al activar **Administrar trade**, GitHub recibe una evaluación inmediata y Cloudflare sigue enviando ticks a los minutos `07`, `22`, `37` y `52` de cada hora. Puede existir una pequeña demora de cola en GitHub Actions.

## Seguridad y límites

- El Worker no recibe las credenciales de Telegram ni la clave de OpenAI; esos secretos existen sólo en GitHub Actions.
- Codex corre con `gpt-5.6-terra` y esfuerzo `medium`, en un job separado y de sólo lectura. No recibe los secretos de publicación de Telegram.
- El monitor no usa IA, no se conecta a la cuenta FBS y nunca cambia ni cierra órdenes.
- Binance/Yahoo son proxies públicos. Todo cambio recomendado debe confirmarse contra Bid/Ask, spread y niveles reales en FBS.
- Si el repositorio es público, la rama `runtime-data` también lo es. No se guarda el número de cuenta ni el ticket FBS, pero los activos y niveles pueden ser visibles en GitHub. Para privacidad total, el repositorio debe ser privado o el estado debe migrarse posteriormente a un almacén privado.

## Operación normal

1. Pulsar **Nueva sesión**.
2. Seguir el log hasta que aparezcan las tres cards o un slot `NO TRADE`.
3. Copiar entrada, SL, TP y tamaño; ejecutar manualmente en FBS.
4. Activar **Administrar trade**, confirmar los niveles realmente colocados y mantener el navegador cerrado si se desea: el seguimiento continúa en servidor.
5. Usar `⏹` para detener cada seguimiento. Las recomendaciones de cierre no lo detienen solas; sólo el usuario lo desactiva.
