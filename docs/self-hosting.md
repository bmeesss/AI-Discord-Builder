# Self-hosting

AI Discord Builder is volledig self-hostable. De standaardinstallatie draait
met een lokale PostgreSQL-database in Docker — er is geen cloud-database en
geen Supabase-account nodig. Supabase blijft als optionele backend bestaan.

## Requirements

- Docker met de Compose-plugin (`docker compose version`);
- een Discord-application met bot-token
  ([Discord Developer Portal](https://discord.com/developers/applications)).
- Alleen voor cloud AI: een API-key van Groq of OpenAI.
- Alleen voor local AI: voldoende hardware voor het gekozen Ollama-model.

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

De standaardwaarden werken direct (`DATABASE_BACKEND=postgres`, database
`discord_builder` met gebruiker/wachtwoord `discord_builder`). **Wijzig
`POSTGRES_PASSWORD` (en pas `DATABASE_URL` overeenkomstig aan) zodra de
installatie voor meer dan lokaal testen wordt gebruikt.**

Starten:

```bash
docker compose up -d
```

Dit start:

1. `db` — PostgreSQL 16 (named volume `postgres_data`, healthcheck via
   `pg_isready`);
2. `bot` — wacht tot `db` gezond is, initialiseert de pool en draait de
   migraties (`DB_MIGRATE_ON_STARTUP=true`), en start daarna pas de bot.

Controleer:

```bash
docker compose ps
docker compose logs -f bot
```

Verwachte logregels: `Applied database migrations: ...` (alleen bij de eerste
start), `PostgreSQL backend ready`, `Logged in as ...`.

## .env setup

Belangrijkste database-instellingen:

| Variabele | Standaard | Betekenis |
| --- | --- | --- |
| `DATABASE_BACKEND` | `postgres` | `postgres` (self-hosting) of `supabase` (cloud) |
| `DATABASE_URL` | `postgresql://discord_builder:discord_builder@db:5432/discord_builder` | PostgreSQL DSN |
| `DB_POOL_MIN_SIZE` | `1` | minimale poolgrootte |
| `DB_POOL_MAX_SIZE` | `10` | maximale poolgrootte |
| `DB_MIGRATE_ON_STARTUP` | `true` | migraties automatisch uitvoeren bij bot-start |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | `discord_builder` | credentials van de Compose-database |

Regels:

- `postgres` vereist nooit Supabase-variabelen;
- `supabase` vereist nooit `DATABASE_URL`;
- ontbreekt een vereiste variabele, dan faalt de config vroeg met een
  duidelijke fout (de bot start nooit “half”);
- bestaande installaties die alleen `SUPABASE_URL`/`SUPABASE_KEY` hebben,
  kiezen automatisch de Supabase-backend (niets breekt) — zet
  `DATABASE_BACKEND=supabase` expliciet om dit vast te leggen;
- wanneer de bot buiten Docker draait: verander de host in `DATABASE_URL`
  van `db` naar `localhost` (of je eigen PostgreSQL-host).

Bij `DATABASE_BACKEND=supabase` start `docker compose up -d` ook de lokale
`db`-container mee (via `depends_on`); die blijft dan ongebruikt. Alleen de
bot bijwerken/starten zonder db kan met `docker compose up -d --no-deps bot`.
Het verwijderen van de `db`-service uit een eigen kopie van `compose.yaml`
kan uiteraard ook.

## Database en migraties

Migraties staan in `database/postgres/migrations/` en draaien versie-gestuurd
via de tabel `schema_migrations` (met SHA-256-checksum per migratie). Ze
worden hooguit één keer uitgevoerd; een gewijzigde al-toegepaste migratie
leidt tot een harde fout. Elke migratie draait in een eigen transactie.

Handmatig beheer (bijv. met `DB_MIGRATE_ON_STARTUP=false`):

```bash
# Binnen Docker
docker compose exec bot python -m database migrate
docker compose exec bot python -m database status

# Op de host (Python + dependencies geïnstalleerd)
python -m database migrate
python -m database status
```

`status` toont backend, DSN (gemaskeerd), connectie en applied/pending
migraties; exit-code is `1` zolang er migraties pending zijn.

Tabellen: `actions` (rollback-history), `conversations`,
`conversation_summaries`, `memories`, `memory_embeddings`,
`server_analysis`, `feedback`, `templates`, `prompt_versions` en
`schema_migrations`. De Supabase-backend gebruikt dezelfde tabelnamen; het
Supabase-SQL staat in `database/migrations/`.

### Wat de opslaglaag níet doet

De database bepaalt nooit of een Discord-actie is toegestaan. Autorisatie
blijft volledig bij de Discord permission/security/executor-laag; opslag
bewaart alleen state en history. Elke repository-methode filtert server-side
op `guild_id` (guild isolation).

## Local AI (optioneel)

Zonder local AI start je gewoon `docker compose up -d`; er draait dan geen
Ollama. Met local AI gebruik je de overlay:

```bash
docker compose \
  -f compose.yaml \
  -f compose.local-ai.yaml \
  up -d
```

Dan draaien: PostgreSQL, bot, Ollama en een eenmalige model-pull
(`ollama-model`). Ollama is alleen nodig bij `AI_PROVIDER=ollama`. Zie
[docs/local-ai.md](local-ai.md) voor modelkeuze en troubleshooting.

## Cloud AI

Werkt ongewijzigd met elke backend:

```env
AI_PROVIDER=groq      # of openai
GROQ_API_KEY=...      # of OPENAI_API_KEY=...
```

## Backups

De enige state buiten Discord staat in PostgreSQL. Eenvoudige backup:

```bash
# Backup naar een SQL-bestand op de host
docker compose exec -T db \
  pg_dump -U discord_builder discord_builder > backup-$(date +%F).sql

# Terugzetten (bot mag draaien; tabellen worden overschreven waar nodig)
cat backup-2026-09-14.sql | docker compose exec -T db \
  psql -U discord_builder discord_builder
```

Bewaar backups buiten de host (bijv. versleuteld in je eigen opslag). Behandel
conversations, memories en history als gevoelige data.

`OLLAMA`-modellen zitten in het volume `ollama_models` en hoeven niet
geback-upt te worden — ze zijn opnieuw te downloaden met `ollama pull`.

## Upgrade procedure

```bash
git pull
docker compose build bot
docker compose up -d
docker compose logs -f bot
```

- Nieuwe migraties draaien automatisch bij de bot-start
  (`DB_MIGRATE_ON_STARTUP=true`), of handmatig met
  `docker compose exec bot python -m database migrate` vóór `up -d`.
- Controleer `docker compose exec bot python -m database status` na een
  upgrade; `pending migrations: none` is gezond.
- Migraties zijn additief en niet-destructief; een downgrade is geen
  aangeboden feature (restore een backup als je echt terug moet).

## Troubleshooting

| Symptoom | Oorzaak / oplossing |
| --- | --- |
| `Database initialization failed ... Could not connect` | `db` is niet gezond of `DATABASE_URL` klopt niet. Check `docker compose ps` en `docker compose logs db`. |
| `Missing required environment variables: DATABASE_URL` | Backend is (default) `postgres` zonder DSN. Zet `DATABASE_URL` of kies `DATABASE_BACKEND=supabase` met Supabase-keys. |
| `Database schema is not up to date (pending: ...)` | Handmatige migraties vereist: `docker compose exec bot python -m database migrate`. |
| `checksum ... already applied` | Een al-toegepaste migratie is lokaal gewijzigd. Wijzig nooit toegepaste migraties; voeg een nieuwe toe. Herstel desnoods de originele file uit git. |
| `/readyz` geeft 503 met `components.database.ok=false` | Database onbereikbaar; bot blijft draaien maar is niet ready. Los de db-connectie op. |
| Bot start niet, `Failed to load Discord extensions` | Controleer `docker compose logs bot` voor de echte fout. |
| Rollback zegt “No history found” | Er is geen opgeslagen history (nieuwe db) of de database was onbereikbaar tijdens het opslaan. |
| Data “weg” na recreate | Alleen als het volume is verwijderd. `docker compose down -v` verwijdert volumes; gebruik `down` zonder `-v`. |

## Health endpoints

- `GET /healthz` — process draait (altijd 200 zolang het proces leeft);
- `GET /readyz` — 200 wanneer Discord én alle vereiste componenten (database,
  migraties) ready zijn, anders 503 met een componenten-overzicht.

In Docker zijn deze alleen op de host bereikbaar via
`http://127.0.0.1:8080/...` (loopback binding).

## Data-persistentie

- `postgres_data` (named volume) overleeft `docker compose restart`,
  `docker compose down` en image-rebuilds;
- `ollama_models` doet hetzelfde voor modellen;
- verwijderen van volumes (`down -v` of `docker volume rm`) wist data
  definitief.

### Persistentie verifiëren (handmatige test)

```bash
# 1. Schrijf data: voer /ask uit in Discord en bevestig een plan,
#    zodat actions/conversations worden opgeslagen.

# 2. Bot-container verwijderen en opnieuw starten
docker compose up -d --force-recreate bot

# 3. Data aanwezig?
docker compose exec db \
  psql -U discord_builder discord_builder \
  -c 'select count(*) as actions from actions;'

# 4. Database-container herstarten (volume-test)
docker compose restart db
docker compose exec db \
  psql -U discord_builder discord_builder \
  -c 'select count(*) as actions from actions;'

# 5. Rollback gebruikt de opgeslagen history: /rollback amount:1
```

Verwachting: de `count` blijft na elke stap gelijk. In CI wordt dit als
automatische integratietest uitgevoerd tegen een echte PostgreSQL
(`.github/workflows/ci.yml`, job `postgres-integration`).
