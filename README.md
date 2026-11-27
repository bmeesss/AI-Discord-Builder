# AI-Discord-Builder

AI-Discord-Builder is een AI-gestuurde Discord bot waarmee bevoegde gebruikers
servers kunnen bouwen en beheren via natuurlijke taal (`/ask <vraag>`). De AI
maakt een JSON-plan; de bestaande validatie, bevestigingsknoppen,
security-checks en executor bepalen daarna of Discord-wijzigingen mogen worden
uitgevoerd.

De bot is **volledig databasevrij en gratis te draaien**:

- **geen** PostgreSQL, Supabase, SQLite of andere (betaalde) databasedienst;
- **geen** databasecontainer, migraties of verbindingen bij het opstarten;
- persistente gegevens (rollback-history, conversatie-log) staan in lokale
  JSON-bestanden in `DATA_DIR` (standaard `data/`);
- draait op **Render Free (€0/maand)** met **UptimeRobot Free** als monitor —
  of gewoon lokaal/via Docker.

Ondersteunde AI-providers:

- Groq (cloud);
- OpenAI (cloud);
- Ollama (optionele lokale AI).

## Snel starten (Docker)

```bash
git clone https://github.com/bmeesss/AI-Discord-Builder.git
cd AI-Discord-Builder
cp .env.example .env
```

Vul in `.env` **alleen** in:

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

Dat is alles: één container, geen database. De JSON-opslag staat op het named
volume `bot_data` en overleeft container-restarts en image-rebuilds.

Health endpoints:

- `http://127.0.0.1:8080/healthz` — process liveness;
- `http://127.0.0.1:8080/readyz` — readiness: Discord runtime **én** lokale
  opslag, anders HTTP 503. Dit endpoint toont alleen statussen, nooit tokens,
  keys of andere interne details.

## Deployen op Render Free (€0/maand)

De repository bevat een [`render.yaml`](render.yaml)-blueprint die precies
één **Free** web service deployt — geen databases, geen betaalde resources.

In het kort:

1. Fork deze repository naar je eigen GitHub-account.
2. Render Dashboard → **New → Blueprint** → selecteer de repository.
3. Vul éénmalig de gevraagde geheimen in (`DISCORD_TOKEN`, `GROQ_API_KEY` of
   `OPENAI_API_KEY`, `AI_PROVIDER`).
4. Zet [UptimeRobot Free](https://uptimerobot.com) op
   `https://<servicenaam>.onrender.com/readyz` (HTTP-check, elke 5 minuten).

> **Belangrijk — hoe Render Free écht werkt.** Een Free web service valt na
> 15 minuten zonder **inkomend** verkeer automatisch in slaap. De
> Discord-Gateway-verbinding is een *uitgaande* verbinding en houdt de service
> dus **niet** actief. In de praktijk houdt de UptimeRobot-check (elke 5
> minuten een HTTP-request) de service wakker; valt die monitoring langer dan
> 15 minuten uit, dan slaapt de service in en is de bot offline tot de
> volgende check hem weer wekt (~1 minuut opstarttijd). Ook zijn bestanden op
> Render Free **tijdelijk**: JSON-geschiedenis gaat verloren bij elke herstart,
> redeploy of slaapstand. Lees [docs/render.md](docs/render.md) voor de
> volledige uitleg, beperkingen en alternatieven.

De volledige beginner-vriendelijke gids staat in **[docs/render.md](docs/render.md)**.

## Opslag zonder database (JSON)

De applicatiecode praat uitsluitend met provider-neutrale storage-interfaces
(`storage/interfaces.py`); de backend is een lokale JSON-file store
(`storage/json_store.py`). Geen SQL, geen verbindingen, geen migraties.

| Bestand in `DATA_DIR` | Inhoud | Bewaard |
| --- | --- | --- |
| `actions.json` | rollback-history per server | laatste 200 acties per server |
| `conversations.json` | conversatie-log (voor AI-context) | laatste 50 per server |
| `memories.json` | voorkeuren (geheugen) | laatste 50 per server |
| `analysis.json` | server-analyse-snapshots | laatste 10 per server |
| `templates.json` | **optioneel**, zelf aangemaakt (zie hieronder) | door jou |

- Schrijven gaat atomisch (tijdelijk bestand + rename); een crash kan nooit
  een half bestand achterlaten.
- Een corrupt bestand is nooit fataal: het wordt apart gezet als
  `<naam>.corrupt` en de bot start ermee door (met waarschuwing in de log).
- Data blijft gescheiden per Discord-server (guild isolation).
- Wil je templates gebruiken, maak dan `data/templates.json` aan met een
  lijst als:
  `[{"name": "SMP Starter", "description": "...", "category": "gaming", "tags": ["minecraft"]}]`.

Op een permanente host (eigen server, VPS, Docker-volume) blijven de
bestanden bewaard. Op **Render Free** niet: daar is het bestandssysteem
tijdelijk (zie boven). Zie [docs/self-hosting.md](docs/self-hosting.md) voor
backup-tips.

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

```env
AI_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen3:4b
LOCAL_AI_MODEL=qwen3:4b
LOCAL_AI_AUTO_SETUP=false
LOCAL_AI_AUTO_SELECT_MODEL=true
```

Inspecteer eerst zonder wijzigingen: `python -m setup detect`, daarna
`python -m setup setup` voor de interactieve installatie. Zie
[docs/local-ai.md](docs/local-ai.md) voor Docker, modelkeuze en
troubleshooting. Met Docker Compose gebruik je de overlay:

```bash
docker compose -f compose.yaml -f compose.local-ai.yaml up -d
```

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
- `/rollback amount:<n>` — draai recente opgeslagen actions terug (zolang de
  JSON-history bewaard is gebleven).

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

De tests gebruiken mocks en tijdelijke mappen; er is **geen database nodig**.
De enige opt-in integratietest is die tegen een echte Ollama-server:

```bash
RUN_OLLAMA_TESTS=1 python -m unittest \
  tests.integration.test_ollama_integration
```

## Beveiligingsgrenzen

- Discord-token en provider-keys staan alleen in environment/configuration.
- AI-providers kunnen geen Discord API-acties uitvoeren.
- AI-output wordt gevalideerd voordat de executor wordt aangeroepen.
- Local AI omzeilt geen permission- of confirmation-checks.
- Commit nooit `.env`, API keys of Ollama-modelbestanden.
- Behandel lokaal opgeslagen prompts, memory en action history als gevoelige
  data.
- De health-endpoints tonen nooit tokens, keys of interne details.

## Huidige grenzen

- **JSON-opslag is lokaal**: op Render Free (of elke host met een tijdelijk
  bestandssysteem) gaan rollback-history en conversatie-logs verloren bij
  herstart, redeploy of slaapstand. Op een eigen server/Docker-volume blijven
  ze bewaard.
- Rollback werkt alleen over bewaarde history; zonder history zegt
  `/rollback` "No history found".
- Rollback van `delete_channel`/`delete_role` is een *gedeeltelijk* herstel:
  het kanaal/de rol wordt opnieuw aangemaakt met de opgeslagen naam,
  categorie, kleur en permissies — berichten, overwrites en rol-posities
  worden niet hersteld.
- Conversatie-samenvattingen in de AI-context zijn lichtgewicht (laatste
  verzoeken); er draait geen aparte summarizer.
- Ollama-installatie is best-effort en OS-afhankelijk; controleer altijd de
  voorgestelde actie.
- Modelkwaliteit en JSON-betrouwbaarheid kunnen per lokaal model verschillen.
- Een publiek webdashboard is nog niet geïmplementeerd.
