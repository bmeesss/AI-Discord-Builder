# AI-Discord-Builder

AI-Discord-Builder is een AI-gestuurde Discord bot waarmee bevoegde gebruikers
servers kunnen bouwen en beheren via natuurlijke taal (`/ask <vraag>`). De AI
maakt een JSON-plan; de bestaande validatie, bevestigingsknoppen,
security-checks en executor bepalen daarna of Discord-wijzigingen mogen worden
uitgevoerd.

Ondersteunde AI-providers:

- Groq (cloud);
- OpenAI (cloud);
- Ollama (optionele lokale AI).

Ondersteunde opslag-backends (conversations, memories, rollback-history):

- PostgreSQL — **standaard voor self-hosting**, lokaal via Docker;
- Supabase — optionele cloud-backend.

Local AI is optioneel. Cloud-only installaties starten geen Ollama en downloaden
geen lokale modellen.

## Installatie met Docker

De repository bevat een eenvoudige container-baseline. Python is dan niet nodig
op de host.

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

Start de bot:

```bash
docker compose up -d
docker compose logs -f bot
```

Dit start PostgreSQL (`db`) en de bot. De bot wacht tot PostgreSQL gezond is,
draait daarna automatisch de datamigraties en start pas dan. Er is **geen
Supabase-account of cloud-database nodig**. Data overleeft restarts via het
named volume `postgres_data`.

De standaard Compose-configuratie voegt geen Ollama toe. Wil je Supabase
gebruiken in plaats van de lokale PostgreSQL, zet dan
`DATABASE_BACKEND=supabase` met `SUPABASE_URL` en `SUPABASE_KEY` in `.env`.
Zie [docs/self-hosting.md](docs/self-hosting.md) voor migraties, backups,
upgrades en troubleshooting.

Health endpoints:

- `http://127.0.0.1:8080/healthz` — process liveness;
- `http://127.0.0.1:8080/readyz` — readiness: Discord runtime **én** database
  (bereikbaar + migraties uitgevoerd), anders HTTP 503.

## Database en self-hosting

De applicatiecode praat uitsluitend met provider-neutrale storage-interfaces
(`database/interfaces.py`); de storage factory kiest de backend via
`DATABASE_BACKEND`:

- `postgres` (default): async PostgreSQL (asyncpg) met connection pooling en
  versie-gestuurde migraties in `database/postgres/migrations/`;
- `supabase`: de bestaande Supabase-adapter, ongewijzigd beschikbaar.

Bestaande installaties die alleen `SUPABASE_URL`/`SUPABASE_KEY` hebben,
blijven automatisch Supabase gebruiken tot `DATABASE_BACKEND` expliciet wordt
gezet.

Migrations handmatig beheren:

```bash
# Docker
docker compose exec bot python -m database migrate
docker compose exec bot python -m database status

# Host
python -m database migrate
python -m database status
```

Migreren van Supabase naar PostgreSQL (optioneel, additief):

```bash
python -m database export-supabase
python -m database verify-export <export-path>
python -m database import-postgres <export-path> --dry-run
python -m database import-postgres <export-path> --yes
```

De bot controleert bij startup of de database bereikbaar is en het schema
up-to-date is; bij een fout stopt de startup direct met een duidelijke
melding in plaats van later willekeurig te crashen.

De opslaglaag slaat alleen state/history op en bepaalt **nooit** of een
Discord-actie is toegestaan — autorisatie blijft bij de
permission/executor-laag. Repository-methodes filteren server-side op
`guild_id`.

## Migrating from Supabase

Draai je nog op Supabase en wil je naar de lokale PostgreSQL? Gebruik de
ingebouwde migratietool (`python -m database`). De tool is additief: er wordt
niets uit Supabase verwijderd, bestaande PostgreSQL-data blijft staan en de
actieve backend wordt nooit automatisch omgezet.

```bash
# 1. Stop writes: zet de bot uit zodat er niets meer wordt weggeschreven.
docker compose stop bot

# 2. Export Supabase (alleen SUPABASE_URL/SUPABASE_KEY nodig, gepagineerd).
DATABASE_BACKEND=supabase python -m database export-supabase

# 3. Verify export (read-only: syntax, aantallen, relaties, secrets).
python -m database verify-export backups/supabase-export-20260915-120000

# 4. Backup PostgreSQL — verplicht vóór de import.
docker compose exec -T db \
  pg_dump -U discord_builder --clean --if-exists discord_builder \
  > backup-voor-import-$(date +%F).sql

# 5. Dry-run import: rapporteert per tabel, schrijft niets.
DATABASE_BACKEND=postgres python -m database import-postgres \
  backups/supabase-export-20260915-120000 --dry-run

# 6. Import (interactieve bevestiging, of --yes voor automation).
DATABASE_BACKEND=postgres python -m database import-postgres \
  backups/supabase-export-20260915-120000 --yes

# 7. Controleer daarna de gerapporteerde aantallen (verification pass),
# 8. zet DATABASE_BACKEND=postgres in .env, 9. herstart de bot,
# 10. controleer /readyz en 11. test /ask en /rollback amount:1.
```

De export bestaat uit `manifest.json` plus één `.jsonl`-file per tabel
(`actions`, `conversations`, `memories`, `memory_embeddings`,
`conversation_summaries`, `server_analysis`, `feedback`, `templates`,
`prompt_versions`) met checksums in het manifest. De import is idempotent:
dezelfde export opnieuw importeren levert `inserted: 0, skipped: <n>,
errors: 0` op. `actions.id` is in PostgreSQL een identity-kolom en wordt
opnieuw gegenereerd; inhoud en chronologie (en dus rollback) blijven behouden.
Exportbestanden bevatten nooit secrets — de scan blokkeert de export als dat
wel zo is. Volledige details, conflictstrategie per tabel en troubleshooting
staan in [docs/self-hosting.md](docs/self-hosting.md#migrating-from-supabase).

De CI-stappen voor deze tests (unit- en PostgreSQL-integratietests) staan in
[docs/ci-migration-tests.patch](docs/ci-migration-tests.patch). Pas die toe met
`git apply docs/ci-migration-tests.patch` als `.github/workflows/ci.yml` nog
niet is bijgewerkt.

## Cloud AI configureren

### Groq

```env
AI_PROVIDER=groq
GROQ_API_KEY=...
GROQ_MODEL=llama-3.3-70b-versatile
```

### OpenAI

```env
AI_PROVIDER=openai
OPENAI_API_KEY=...
OPENAI_MODEL=gpt-4o-mini
```

Alleen de key van de gekozen provider is nodig. API keys worden niet door de
setup-tool gevraagd, geprint of in configuratiebestanden geschreven.

## Local AI met Ollama

Local AI gebruikt Ollama via HTTP. De AI-provider maakt alleen een plan; hij
krijgt geen directe toegang tot Discord API-acties. De bestaande
`ai.validation`, confirmation flow, permissions, executor en rollback blijven
actief.

Voorbeeld voor een host-installatie:

```env
AI_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen3:4b
LOCAL_AI_MODEL=qwen3:4b
LOCAL_AI_AUTO_SETUP=false
LOCAL_AI_AUTO_SELECT_MODEL=true
```

Inspecteer eerst zonder wijzigingen:

```bash
python -m setup detect
```

Start daarna de interactieve setup:

```bash
python -m setup setup
```

De setup kan, na expliciete toestemming:

- OS en architectuur detecteren;
- CPU, RAM en vrije diskruimte rapporteren;
- Docker en een GPU-tool detecteren wanneer betrouwbaar beschikbaar;
- Ollama detecteren;
- Ollama starten wanneer het al geïnstalleerd is;
- Ollama op Linux, Windows of macOS installeren wanneer een ondersteunde
  installer beschikbaar is;
- een gekozen model downloaden;
- een model-smoketest uitvoeren;
- alleen local-AI-instellingen naar `.env` schrijven.

De setup-tool installeert of downloadt niets in `detect`-modus. De bot zelf
installeert nooit software bij startup.

Zie [docs/local-ai.md](docs/local-ai.md) voor Docker, modelkeuze en
troubleshooting.

## Local AI in Docker

Gebruik de extra Compose-overlay expliciet:

```bash
docker compose \
  -f compose.yaml \
  -f compose.local-ai.yaml \
  up -d
```

Dit voegt de Ollama-container alleen in deze modus toe. Modellen worden niet in
de bot-image geplaatst maar in het named volume `ollama_models` opgeslagen. De
one-shot `ollama-model` service voert bij de eerste start `ollama pull` uit.
Handmatig pullen kan ook:

```bash
docker compose \
  -f compose.yaml \
  -f compose.local-ai.yaml \
  exec ollama ollama pull qwen3:4b
```

Test de lokale provider met:

```bash
docker compose \
  -f compose.yaml \
  -f compose.local-ai.yaml \
  exec bot python -m setup test
```

De bot gebruikt intern `http://ollama:11434`; een host-gebaseerde setup-tool
gebruikt `http://localhost:11434`. Het model blijft behouden bij een container
recreate zolang `ollama_models` niet wordt verwijderd.

## Discord bot configureren

1. Maak een application aan via
   [Discord Developer Portal](https://discord.com/developers/applications).
2. Maak/reset de Bot Token en plaats deze in `.env` als `DISCORD_TOKEN`.
3. Zet voor de mention-handler de privileged **Message Content Intent** aan.
4. Zet **Server Members Intent** aan wanneer member-cache/permissiegedrag dat
   vereist.
5. Nodig de bot uit met de scopes `bot` en `applications.commands`.
6. Geef minimaal de permissions die de gekozen actions nodig hebben, zoals
   `Manage Channels`, `Manage Roles` en `Send Messages`.

Standaard mogen alleen leden met `Administrator` de builder gebruiken:

```env
REQUIRE_ADMIN=true
```

## Gebruik

```text
/ask Maak een Minecraft SMP Discord server
/ask maak een kanaal genaamd support
/ask verwijder kanaal test
/ask verplaats kanaal general naar community
/ask maak een moderator rol
```

De bot toont eerst een plan met Confirm/Cancel. Pas na bevestiging worden
acties uitgevoerd. High-risk en critical plannen vragen een extra bevestiging.

Beschikbare commando's:

- `/ask` — maak of wijzig een serverplan;
- mention de bot — dezelfde planning-flow;
- `/rollback amount:<n>` — draai recente opgeslagen actions terug wanneer de
  persistence-adapter beschikbaar is.

## Lokale development en tests

```bash
python -m venv .venv
# Linux/macOS
source .venv/bin/activate
# Windows: .venv\\Scripts\\activate
pip install -r requirements-dev.txt
python -m unittest discover -v
pytest -q
```

De normale tests gebruiken mocks en hebben geen Ollama-server of database
nodig. De echte integration tests zijn opt-in:

```bash
# Ollama
RUN_OLLAMA_TESTS=1 python -m unittest \
  tests.integration.test_ollama_integration

# PostgreSQL (bijv. tegen de Compose-database)
RUN_POSTGRES_TESTS=1 \
DATABASE_URL=postgresql://discord_builder:discord_builder@localhost:5432/discord_builder \
  python -m unittest tests.integration.test_postgres_integration
```

## Beveiligingsgrenzen

- Discord-token en provider-keys staan alleen in environment/configuration.
- AI-providers kunnen geen Discord API-acties uitvoeren.
- AI-output wordt gevalideerd voordat de executor wordt aangeroepen.
- Local AI omzeilt geen permission- of confirmation-checks.
- Commit nooit `.env`, API keys of Ollama-modelbestanden.
- Behandel lokaal opgeslagen prompts, memory en action history als gevoelige
  data.

## Huidige grenzen

- Ollama-installatie is best-effort en OS-afhankelijk; controleer altijd de
  voorgestelde actie.
- Hardwaredetectie kan geen prestaties garanderen.
- Modelkwaliteit en JSON-betrouwbaarheid kunnen per lokaal model verschillen.
- Rollback-history heeft geen eigen statuskolom: alleen succesvol uitgevoerde
  acties worden opgeslagen, en `rollback` kijkt naar de laatste N acties
  (oudste eerst). Deze bestaande semantiek is bewust behouden.
- De opslaglaag kent geen per-guild settings-tabel; guild-specifieke bot-
  instellingen leven nu in environment/config (gedocumenteerd, geen redesign).
- Een publiek webdashboard is nog niet geïmplementeerd.
- De Supabase → PostgreSQL migratietool exporteert en importeert data, maar synchroniseert niet: hij is bedoeld voor een eenmalige overstap en is niet transactioneel consistent met een Supabase-project dat ondertussen door blijft schrijven (stop writes vóór de export).
