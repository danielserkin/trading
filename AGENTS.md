# Workspace instructions

## Local skills

- `trading-session`: Read and follow `skills/trading-session/SKILL.md` whenever the user says “nueva sesión”, “nueva session”, “iniciar sesión de trading”, or requests a new FBS/trading session. These phrases are execution commands: start the workflow immediately and do not answer with a generic greeting or ask what to work on.
- `trading-review`: Read and follow `skills/trading-review/SKILL.md` for completed-session results, closed-trade outcome analysis, or historical performance reviews. If the request says only “revisión” but `active-trades/` contains a newly supplied position screenshot, use `active-trade-manager` instead.
- `active-trade-manager`: Read and follow `skills/active-trade-manager/SKILL.md` whenever the user says “revisión”, “revision”, “revisar”, “revisar trades”, “revisar trades activos”, “gestionar operaciones abiertas”, “qué hago con estas operaciones”, or asks what to do with current FBS positions. These phrases are execution commands: inspect the newest screenshots under `active-trades/`, return exact management actions, and notify the configured Telegram channel. Active-position management takes precedence over `trading-review`; never execute or modify broker orders.

Local skills are authoritative for their workflows even if they are not shown in the global skill catalog.
