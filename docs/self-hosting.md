# Self-hosting (zonder database)

AI-Discord-Builder is volledig self-hostbaar en **databasevrij**: de bot
draait als één container/proces en slaat persistente gegevens op in lokale
JSON-bestanden. Er is geen PostgreSQL, Supabase, SQLite of andere
databasedienst — en dus ook geen database-kosten, migraties of
verbindingsbeheer.

## Requirements

- Docker met de Compose-plugin (`docker compose version`), of Python 3.11+;
- een Discord-application met bot-token
  ([Discord Developer Portal](https://discord.com/developers/applications));
- alleen voor cloud AI: een API-key van de gekozen provider (Groq, Google
  Gemini, Mistral, OpenRouter, DeepSeek, Anthropic, xAI, Together AI,
  Perplexity of OpenAI);
- alleen voor local AI: voldoende hardware voor het gekozen Ollama-model.

Liever gehost zonder eigen server? Zie **[render.md](render.md)** voor het
gratis deployen op Render Free (met UptimeRobot-monitoring).

## Installatie (Docker)

```bash
git clone https://github.com/bmeesss/AI-Discord-Builder.git
cd AI-Discord-Builder
cp .env.example .env
```

Vul in `.env` minimaal in:

```env
DISCORD_TOKEN=...
AI_PROVIDER=groq
GROQ_API_KEY=...
```

Starten:

```bash
docker compose up -d
```

Dit start één container (`bot`) — meer niet. De JSON-opslag staat in
`/app/data` op het named volume `bot_data` en overleeft `docker compose
restart`, `docker compose down` en image-rebuilds.

Controleer:

```bash
docker compose ps
docker compose logs -f bot
```

Verwachte logregels: `JSON storage ready (data dir: ...)`, `Logged in as ...`.

## Lokale JSON-opslag

Alle persistente gegevens staan in platte JSON-bestanden in `DATA_DIR`
(standaard `data/`, in Docker `/app/data`):

| Bestand | Inhoud | Begrenzing |
| --- | --- | --- |
| `actions.json` | rollback-history per guild | laatste 200 acties per guild |
| `conversations.json` | conversatie-log (AI-context) | laatste 50 per guild |
| `memories.json` | voorkeuren per guild/user | laatste 50 per guild |
| `analysis.json` | server-analyse-snapshots | laatste 10 per guild |
| `templates.json` | optioneel, door jou aangemaakt | — |

Gedrag:

- **Atomisch schrijven** (tijdelijk bestand + `os.replace`): een crash kan
  nooit een half bestand achterlaten.
- **Corruptie-tolerantie**: een beschadigd bestand wordt verplaatst naar
  `<naam>.corrupt` en de bot start met een leeg bestand door (waarschuwing in
  de log). Je kunt het `.corrupt`-bestand handmatig herstellen.
- **Guild-isolatie**: gegevens van de ene Discord-server zijn nooit zichtbaar
  voor de andere.
- **Geen SQL, geen migraties**: er is geen schema; de bestanden zijn gewoon
  leesbaar met elke teksteditor.

Optionele templates aanmaken (`data/templates.json`):

```json
[
  {
    "name": "SMP Starter",
    "description": "Minecraft survival server",
    "category": "gaming",
    "tags": ["minecraft"],
    "recommended_for": ["gaming communities"]
  }
]
```

Templates met `tags` die in het verzoek passen worden als eerste voorgesteld;
`"enabled": false` verbergt een template.

## Tijdelijke bestandssystemen (belangrijk)

Niet elke host bewaart lokale bestanden:

- **Render Free** (en andere free tiers): bestanden gaan **verloren** bij
  herstart, redeploy én slaapstand. Rollback-history en conversatie-logs
  beginnen dan opnieuw. Zie [render.md](render.md).
- **Eigen server / VPS / Docker-volume**: bestanden blijven bewaard zolang je
  het volume niet verwijdert.

De bot werkt in beide gevallen volledig; alleen de opgeslagen history/context
kan bij een herstart leeg zijn.

## .env setup

### Complete configuratietabel

Alleen `DISCORD_TOKEN` en de key van de gekozen AI-provider zijn verplicht;
de rest heeft werkende standaarden.

| Variabele | Standaard | Verplicht? | Betekenis |
| --- | --- | --- | --- |
| `DISCORD_TOKEN` | — | ja | Discord bot-token |
| `AI_PROVIDER` | `groq` | ja | `groq`, `openai`, `gemini`, `mistral`, `openrouter`, `deepseek`, `anthropic`, `xai`, `together`, `perplexity` of `ollama` |
| `GROQ_API_KEY` | — | bij `groq` | Groq API-key |
| `GROQ_MODEL` | `llama-3.3-70b-versatile` | nee | Groq modelnaam |
| `OPENAI_API_KEY` | — | bij `openai` | OpenAI API-key |
| `OPENAI_MODEL` | `gpt-4o-mini` | nee | OpenAI modelnaam |
| `OPENAI_BASE_URL` | — | nee | optioneel OpenAI-compatible endpoint (uit) |
| `GEMINI_API_KEY` / `GEMINI_MODEL` | `gemini-4-hydrogen` | bij `gemini` | Google Gemini key en modelnaam |
| `MISTRAL_API_KEY` / `MISTRAL_MODEL` | `mistral-small-latest` | bij `mistral` | Mistral key en modelnaam |
| `OPENROUTER_API_KEY` / `OPENROUTER_MODEL` | `openrouter/free` | bij `openrouter` | OpenRouter key en modelnaam |
| `DEEPSEEK_API_KEY` / `DEEPSEEK_MODEL` | `deepseek-flash` | bij `deepseek` | DeepSeek key en modelnaam |
| `ANTHROPIC_API_KEY` / `ANTHROPIC_MODEL` | `claude-haiku-4-5` | bij `anthropic` | Anthropic (Claude) key en modelnaam |
| `XAI_API_KEY` / `XAI_MODEL` | `grok-4.3` | bij `xai` | xAI (Grok) key en modelnaam |
| `TOGETHER_API_KEY` / `TOGETHER_MODEL` | `meta-llama/Llama-3.3-70B-Instruct-Turbo` | bij `together` | Together AI key en modelnaam |
| `PERPLEXITY_API_KEY` / `PERPLEXITY_MODEL` | `sonar` | bij `perplexity` | Perplexity key en modelnaam |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | bij `ollama` | Ollama endpoint (Compose-overlay: `http://ollama:11434`) |
| `OLLAMA_MODEL` | `qwen3:4b` | bij `ollama` | lokaal model |
| `OLLAMA_HOST_PORT` | `11434` | nee | host-poort voor de Ollama-container (alleen Compose) |
| `LOCAL_AI_MODEL` | = `OLLAMA_MODEL` | nee | alias voor het lokale model |
| `LOCAL_AI_AUTO_SETUP` | `false` | nee | setup-CLI mag installeren (altijd interactief bevestigen) |
| `LOCAL_AI_AUTO_SELECT_MODEL` | `true` | nee | modeladvies op basis van hardware |
| `AI_REQUEST_TIMEOUT_SECONDS` | `60` | nee | timeout per AI-request |
| `DATA_DIR` | `data` | nee | map voor de JSON-bestanden (Docker: `/app/data`) |
| `REQUIRE_ADMIN` | `true` | nee | alleen Administrators mogen `/ask` gebruiken |
| `MAX_ACTIONS_PER_PLAN` | `40` | nee | veiligheidslimiet per AI-plan |
| `MAX_AI_RETRIES` | `2` | nee | self-correction pogingen |
| `CONFIRMATION_TIMEOUT` | `120` | nee | levensduur bevestigingsknoppen (seconden) |
| `APP_ENV` | `production` | nee | deployment-context |
| `WEB_HOST` | `0.0.0.0` | nee | bind-adres health-endpoints |
| `WEB_PORT` | `8080` | nee | poort health-endpoints (heeft voorrang op `PORT`) |
| `PORT` | `10000` (Render) | nee | platform-poort; automatisch gebruikt wanneer `WEB_PORT` niet is gezet (Render zet dit zelf) |
| `LOG_LEVEL` | `INFO` | nee | logniveau |
| `LOG_FILE_PATH` | `logs/actions.log` | nee | logbestand |

Er zijn bewust **geen** database-variabelen meer: `DATABASE_URL`,
`DATABASE_BACKEND`, `SUPABASE_*` en `POSTGRES_*` worden niet meer gebruikt.
Staan ze nog in een oude `.env`, dan worden ze simpelweg genegeerd.

Regels:

- ontbreekt een vereiste variabele, dan faalt de config vroeg met een
  duidelijke fout (de bot start nooit “half”);
- de bot start niet voordat `DATA_DIR` beschrijfbaar is;
- wanneer de bot buiten Docker draait: `DATA_DIR=data` (relatief aan de
  werkmap) is de standaard.

## Backups

De enige state buiten Discord staat in de JSON-bestanden. Een backup is een
gewone bestandskopie:

```bash
# Docker
docker compose cp bot:/app/data ./backup-data-$(date +%F)

# Host
cp -r data ./backup-data-$(date +%F)
```

Terugzetten = de bestanden weer in `DATA_DIR` leggen en de bot herstarten.
Behandel conversations, memories en history als gevoelige data.

## Upgrade procedure

```bash
git pull
docker compose build bot
docker compose up -d
docker compose logs -f bot
```

Er zijn geen migraties; nieuwe versies lezen dezelfde JSON-bestanden. Het
bestandsformaat is achterwaarts compatibel (nieuwe sleutels zijn optioneel).

## Troubleshooting

| Symptoom | Oorzaak / oplossing |
| --- | --- |
| `Local storage initialization failed ... not usable` | `DATA_DIR` bestaat niet en kan niet worden aangemaakt, of is niet beschrijfbaar. Zet `DATA_DIR` op een beschrijfbare pad. |
| `Missing required environment variables: GROQ_API_KEY` | `AI_PROVIDER=groq` maar de key ontbreekt. Vul de key of kies een andere provider. |
| `/readyz` geeft 503 met `discord: starting` | De bot is nog niet ingelogd of de login faalt; check `DISCORD_TOKEN` en de logs. |
| `/readyz` geeft 503 met `components.storage: unhealthy` | De JSON-map is niet beschrijfbaar (bijv. volle schijf of verwijderd volume). |
| Waarschuwing `Corrupt JSON file ... .corrupt` | Een bestand was beschadigd en is apart gezet. De bot draait door met een lege historie voor dat onderdeel. |
| `/rollback` zegt “No history found” | Er is geen opgeslagen history (nieuwe installatie, of bestanden verloren gegaan op een tijdelijk bestandssysteem). |
| Bot start niet, `Failed to load Discord extensions` | Controleer `docker compose logs bot` voor de echte fout. |
| Data “weg” na herstart op Render Free | Verwacht gedrag: Render Free heeft een tijdelijk bestandssysteem (zie render.md). |
| Data “weg” na `docker compose down -v` | `-v` verwijdert ook het volume `bot_data`; gebruik `down` zonder `-v`. |

## Health endpoints

- `GET /healthz` — process draait (altijd 200 zolang het proces leeft);
- `GET /readyz` — 200 wanneer Discord én de lokale opslag ready zijn, anders
  503. De response toont alleen statussen per component (`ok`/`unhealthy`) —
  nooit tokens of andere interne details (die staan in de logs).

In Docker zijn deze alleen op de host bereikbaar via
`http://127.0.0.1:${WEB_PORT:-8080}/...` (loopback binding). Op een host met
publieke URL (bijv. Render) monitor je `/readyz` met
[UptimeRobot](https://uptimerobot.com) — zie [render.md](render.md).

## Restart-gedrag

- **bot herstart**: JSON-bestanden blijven staan (volume) en worden opnieuw
  gelezen; de history is intact;
- **`DATA_DIR` weggehaald/overschrijfbaar niet meer**: de bot start niet en
  stopt met een duidelijke fout;
- **corrupt bestand bij startup**: wordt apart gezet (`.corrupt`), de bot
  start door met een lege historie voor dat onderdeel.

## `down` versus `down -v`

```bash
docker compose down      # container/netwerk weg; volume blijft (data blijft)
docker compose down -v   # verwijdert OOK bot_data en ollama_models (data weg)
```

Gebruik `down -v` alleen als je bewust alle opgeslagen history, memories en
conversations wilt verwijderen.

## Local AI (optioneel)

Zonder local AI start je gewoon `docker compose up -d`; er draait dan geen
Ollama. Met local AI gebruik je de overlay:

```bash
docker compose \
  -f compose.yaml \
  -f compose.local-ai.yaml \
  up -d
```

Dan draaien: de bot, Ollama en een eenmalige model-pull (`ollama-model`).
Ollama is alleen nodig bij `AI_PROVIDER=ollama`. Zie
[docs/local-ai.md](local-ai.md) voor modelkeuze en troubleshooting.

## Cloud AI

Werkt met elke opslagvorm (de opslag is sowieso databasevrij):

```env
AI_PROVIDER=groq      # of openai, gemini, mistral, openrouter, deepseek,
                      # anthropic, xai, together, perplexity
GROQ_API_KEY=...      # of de key van de gekozen provider
```

Zie de tabel hierboven voor alle providers, key-variabelen en
standaardmodellen.
