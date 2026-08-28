# Arquitectura visual de Trading Control

Esta documentación describe lo que está desplegado actualmente. El sistema genera recomendaciones y seguimiento, pero **nunca ejecuta ni modifica órdenes en FBS**.

## Vista general

```mermaid
flowchart LR
    U["👤 Usuario<br/>Navegador"]

    subgraph PUBLIC["🌐 Capa pública"]
        P["🎨 GitHub Pages<br/>HTML · CSS · JavaScript"]
        W["🛡️ Cloudflare Worker<br/>Autenticación · API · Cron"]
    end

    subgraph GITHUB["⚙️ GitHub"]
        A["▶️ GitHub Actions<br/>Sesión y monitor"]
        R["🗃️ Rama runtime-data<br/>Cards · logs · decisiones"]
        S["🔐 GitHub Actions Secrets"]
    end

    subgraph EXTERNAL["🔌 Servicios externos"]
        O["🤖 OpenAI Codex<br/>Revisión de sesión"]
        TIN["📥 Telegram<br/>Canales de señales"]
        TOUT["📲 Telegram Bot<br/>Resultados y seguimiento"]
        M["📊 Datos públicos<br/>Yahoo Finance · Binance"]
        F["📱 FBS<br/>Ejecución manual"]
    end

    U -->|"abre la web"| P
    P -->|"PIN por HTTPS"| W
    W -->|"token temporal 12 h"| P
    P -->|"consultar estado / iniciar sesión / activar monitor"| W
    W -->|"GitHub API"| R
    W -->|"repository_dispatch"| A
    S -.->|"secretos por job"| A
    A --> TIN
    A --> M
    A --> O
    A --> TOUT
    A -->|"actualiza estado"| R
    U -->|"copia niveles y opera"| F

    classDef person fill:#0e7490,color:#fff,stroke:#67e8f9;
    classDef public fill:#0f766e,color:#fff,stroke:#5eead4;
    classDef github fill:#312e81,color:#fff,stroke:#a5b4fc;
    classDef external fill:#713f12,color:#fff,stroke:#fcd34d;
    class U person;
    class P,W public;
    class A,R,S github;
    class O,TIN,TOUT,M,F external;
```

### Responsabilidad de cada componente

| Componente | Qué hace | Qué no hace |
| --- | --- | --- |
| GitHub Pages | Presenta el panel, cards, log y controles. Guarda localmente la URL del Worker y el token temporal. | No contiene secretos ni ejecuta análisis. |
| Cloudflare Worker | Valida el PIN, firma sesiones de 12 horas, lee/escribe el estado y dispara workflows. Ejecuta el cron cada 15 minutos. | No recibe claves de OpenAI o Telegram y no analiza el mercado. |
| GitHub Actions | Ejecuta la sesión de trading, Codex, el monitor determinista y la publicación a Telegram. | No mantiene un servidor encendido. Cada ejecución es aislada. |
| Rama `runtime-data` | Conserva cards, eventos, monitores y decisiones entre ejecuciones. | No guarda API keys, el PIN ni sesiones de Telegram. |
| FBS | Es donde el usuario confirma precios y opera manualmente. | La web no se conecta a la cuenta ni toca órdenes. |

## Recorrido de una nueva sesión

```mermaid
sequenceDiagram
    autonumber
    actor U as 👤 Usuario
    participant P as 🎨 GitHub Pages
    participant W as 🛡️ Worker
    participant G as ⚙️ GitHub Actions
    participant T as 📥 Telegram / mercado
    participant C as 🤖 Codex
    participant R as 🗃️ runtime-data
    participant B as 📲 Bot Telegram

    U->>P: Pulsa Nueva sesión
    P->>W: POST /sessions + token temporal
    W->>R: Estado = queued
    W->>G: repository_dispatch new_session
    W-->>P: Sesión en cola
    G->>R: Estado = running
    G->>T: Lee señales y datos públicos
    T-->>G: Candidatos y velas
    G->>B: Envía oportunidades
    G->>C: Revisión read-only de las 3 cards
    C-->>G: Revisión estructurada
    G->>R: Cards + log + revisión
    loop Cada 8 segundos mientras la web está abierta
        P->>W: GET /state
        W->>R: Lee estado
        R-->>W: JSON actual
        W-->>P: Cards y eventos
    end
```

Si Codex no está disponible, se publican igualmente los resultados deterministas del analizador; la sesión no queda bloqueada.

## Recorrido del seguimiento de un trade

```mermaid
sequenceDiagram
    autonumber
    actor U as 👤 Usuario
    participant P as 🎨 GitHub Pages
    participant W as 🛡️ Worker + cron
    participant R as 🗃️ runtime-data
    participant G as ⚙️ Monitor Action
    participant M as 📊 Yahoo / Binance
    participant B as 📲 Bot Telegram

    U->>P: Activa Administrar trade
    P->>W: PUT /monitors/{id}
    W->>R: Guarda niveles y enabled = true
    W->>G: Evaluación inmediata
    G->>M: Solicita M15, H1 y H4 cerradas
    M-->>G: Datos públicos proxy
    G->>G: Aplica reglas sin IA
    G->>R: Guarda acción, razones e historial
    G->>B: Envía recomendación

    loop Minutos 07, 22, 37 y 52 de cada hora
        W->>R: ¿Hay monitores activos?
        alt Hay al menos uno
            W->>G: repository_dispatch monitor_tick
            G->>M: Actualiza datos
            G->>R: Persiste decisiones
            G->>B: Notifica cuando corresponde
        else Ninguno activo
            W-->>W: No dispara workflow
        end
    end

    U->>P: Desactiva seguimiento
    P->>W: PUT enabled = false
    W->>R: Estado = paused
```

La primera evaluación comienza al activar el switch. El cron posterior está alineado a minutos fijos, por lo que la primera espera puede ser menor de 15 minutos. El monitor puede decidir `MANTENER`, `MOVER_SL`, `AJUSTAR_TP`, `CERRAR_TODO` o `EVIDENCIA_INSUFICIENTE`. Toda acción debe confirmarse en FBS.

## Dónde vive y se usa cada secreto

```mermaid
flowchart TB
    subgraph GS["🔐 GitHub Actions Secrets"]
        CF["CLOUDFLARE_API_TOKEN<br/>CLOUDFLARE_ACCOUNT_ID"]
        WA["WORKER_GITHUB_TOKEN<br/>APP_PIN<br/>APP_SESSION_SECRET"]
        OA["OPENAI_API_KEY"]
        TR["TELEGRAM_API_ID<br/>TELEGRAM_API_HASH<br/>TELEGRAM_SESSION_GZIP_B64"]
        TB["TELEGRAM_BOT_TOKEN<br/>TELEGRAM_TARGET_CHAT_ID"]
    end

    D["🚀 Workflow deploy-worker"]
    CW["🛡️ Secretos de ejecución del Worker<br/>GH_TOKEN · APP_PIN · APP_SESSION_SECRET"]
    NS["📈 Job run_session"]
    CR["🤖 Job codex_review"]
    MO["📡 Workflow monitor"]
    CFAPI["☁️ API de Cloudflare"]
    GHAPI["🐙 API de GitHub"]
    OAPI["🤖 API de OpenAI"]
    TAPI["✈️ API de Telegram"]

    CF --> D --> CFAPI
    WA --> D --> CW
    CW --> GHAPI
    OA --> CR --> OAPI
    TR --> NS --> TAPI
    TB --> NS
    TB --> MO
    NS --> TAPI
    MO --> TAPI

    classDef secret fill:#7f1d1d,color:#fff,stroke:#fca5a5;
    classDef runtime fill:#164e63,color:#fff,stroke:#67e8f9;
    class CF,WA,OA,TR,TB secret;
    class D,CW,NS,CR,MO,CFAPI,GHAPI,OAPI,TAPI runtime;
```

| Nombre | Se guarda en | Se entrega a | Uso exacto | ¿Llega al navegador? |
| --- | --- | --- | --- | --- |
| `APP_PIN` | GitHub Actions Secrets y, tras desplegar, Cloudflare Worker Secrets | Worker | Comparar el PIN enviado por el usuario. | El usuario lo escribe; no se guarda en la web. |
| `APP_SESSION_SECRET` | GitHub Actions Secrets y Cloudflare Worker Secrets | Worker | Firmar y validar tokens temporales de 12 horas. | No. |
| `WORKER_GITHUB_TOKEN` | GitHub Actions Secrets; se copia como `GH_TOKEN` a Cloudflare | Worker | Leer/escribir `runtime-data` y disparar workflows mediante GitHub API. | No. |
| `CLOUDFLARE_API_TOKEN` | GitHub Actions Secrets | Workflow `deploy-worker` | Publicar el Worker y sincronizar sus secretos. | No. |
| `CLOUDFLARE_ACCOUNT_ID` | GitHub Actions Secrets | Workflow `deploy-worker` | Elegir la cuenta Cloudflare de destino. | No. |
| `OPENAI_API_KEY` | GitHub Actions Secrets | Job `codex_review` | Ejecutar `gpt-5.6-terra` con esfuerzo `medium`. | No. |
| `TELEGRAM_API_ID` | GitHub Actions Secrets | Job `run_session` | Autenticar el cliente que lee canales de señales. | No. |
| `TELEGRAM_API_HASH` | GitHub Actions Secrets | Job `run_session` | Completar la autenticación del cliente lector. | No. |
| `TELEGRAM_SESSION_GZIP_B64` | GitHub Actions Secrets | Job `run_session` | Reconstruir temporalmente `telegram-fbs.session`; se elimina con el runner. | No. |
| `TELEGRAM_BOT_TOKEN` | GitHub Actions Secrets | Job `run_session` y workflow `monitor` | Publicar oportunidades y decisiones de seguimiento. | No. |
| `TELEGRAM_TARGET_CHAT_ID` | GitHub Actions Secrets | Job `run_session` y workflow `monitor` | Definir el chat o canal receptor. | No. |

`GITHUB_TOKEN` es distinto de `WORKER_GITHUB_TOKEN`: GitHub crea el primero automáticamente para cada job y lo limita mediante `permissions`. Se usa para actualizar `runtime-data` desde Actions y desaparece al terminar el job. El segundo debe existir fuera de Actions porque el Worker necesita llamar a GitHub mientras no hay ningún job ejecutándose.

## Variables públicas y de ejecución

Estas variables no son credenciales y pueden aparecer en configuración o logs.

| Variable | Valor actual o procedencia | Uso |
| --- | --- | --- |
| `TRADING_API_BASE` | `https://trading-control.daniel-serkin.workers.dev` | URL pública que GitHub Pages usa para llamar al Worker. |
| `DATA_BRANCH` | `runtime-data` | Rama donde el Worker lee y escribe el estado. |
| `ALLOWED_ORIGIN` | `*` | Orígenes aceptados por CORS. El PIN y el token temporal siguen protegiendo la API. |
| `GH_OWNER` | Se inyecta desde `github.repository_owner` | Propietario usado por el Worker al construir las rutas de GitHub API. |
| `GH_REPO` | Se inyecta desde el nombre del repositorio | Repositorio usado por el Worker. |
| `GITHUB_REPOSITORY` | GitHub la crea automáticamente | Identifica `owner/repo` dentro de los scripts de Actions. |
| `RUNTIME_BRANCH` | Opcional; por defecto `runtime-data` | Permite cambiar la rama de estado en los scripts. |
| `SESSION_DATE` | Fecha UTC de cada ejecución | Ubicación temporal de los artefactos de sesión. |

## Límites de confianza

```mermaid
flowchart LR
    B["🌍 Navegador<br/>entorno no confiable"]
    W["🛡️ Worker<br/>valida PIN y token"]
    A["🔐 GitHub Actions<br/>secretos por job"]
    E["🔌 APIs externas"]

    B -->|"HTTPS + token temporal"| W
    W -->|"token GitHub limitado"| A
    A -->|"credencial mínima necesaria"| E

    N1["Nunca incrustar secretos<br/>en site/"] -.-> B
    N2["Nunca devolver secretos<br/>en respuestas o logs"] -.-> W
    N3["Cada job recibe solo<br/>los secretos que utiliza"] -.-> A

    classDef boundary fill:#111827,color:#fff,stroke:#22d3ee;
    classDef warning fill:#78350f,color:#fff,stroke:#fbbf24;
    class B,W,A,E boundary;
    class N1,N2,N3 warning;
```

La rama `runtime-data` no contiene secretos, pero en un repositorio público sí permite ver símbolos, niveles y decisiones. Para ocultar también esa información habría que volver privado el repositorio o migrar el estado a almacenamiento privado.

## Despliegue

```mermaid
flowchart LR
    C["📝 Push a main"]
    P{"¿Cambió site/?"}
    W{"¿Cambió worker/?"}
    PA["GitHub Actions<br/>pages.yml"]
    WA["GitHub Actions<br/>deploy-worker.yml"]
    GP["🎨 GitHub Pages"]
    CW["🛡️ Cloudflare Worker<br/>+ cron"]

    C --> P
    C --> W
    P -->|Sí| PA --> GP
    W -->|Sí| WA --> CW
```

- Panel: <https://danielserkin.github.io/trading/>
- API del Worker: <https://trading-control.daniel-serkin.workers.dev>
- Salud del Worker: <https://trading-control.daniel-serkin.workers.dev/health>
