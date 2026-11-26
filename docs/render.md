# Deployen op Render

Deze gids zet AI-Discord-Builder als **self-hosted** installatie op
[Render](https://render.com): jij bent de enige gebruiker, met je eigen
Discord-bot, eigen AI-key en eigen database. Er is geen centraal platform.

Alles hieronder is geschreven voor beginners; je hoeft geen Render-ervaring
te hebben.

## 1. Waarom deze architectuur?

Een Discord-bot houdt een **permanente Gateway-verbinding** (WebSocket) open.
Dat bepaalt welke Render-service geschikt is:

| Optie | Kan het? | Waarom (niet) |
| --- | --- | --- |
| **Web Service (betaald)** — onze keuze | ✅ | Altijd aan, publieke healthcheck-URL voor UptimeRobot, `healthCheckPath` voor zero-downtime deploys. |
| Web Service (Free) | ❌ | Render draait Free web services **na 15 minuten zonder inkomend verkeer** naar beneden; de bot valt dan stil. Ook classificeert Render het "wakker houden" met externe pings als ongeschikt gebruik — en het werkt niet eens: uitgaand bot-verkeer telt niet als inkomend verkeer. Free is niet voor productie bedoeld. |
| Background Worker | ❌ | Geen publieke URL en geen health checks; UptimeRobot kan de bot dus niet monitoren. En workers zijn bij Render sowieso altijd betaald. |

Conclusie: de kleinste **betaalde Web Service** (`0.5c-512mb`) plus een
**managed Render Postgres**-database. Dat is de combinatie in
[`render.yaml`](../render.yaml) in de repository.

De web service draait de gewone `Dockerfile` en luistert op de poort uit de
`PORT`-omgevingsvariabele die Render automatisch instelt (standaard `10000`).
De bot herkent dit automatisch: `WEB_PORT` heeft voorrang, anders geldt `PORT`,
anders `8080` (Docker-standaard lokaal).

## 2. Healthchecks en UptimeRobot

De bot exposeert twee endpoints (zie `web/app.py`):

- **`/healthz`** — proces-gezondheid ("leeft het proces?"). Dit is de
  `healthCheckPath` in `render.yaml`; Render gebruikt die voor deploys en om
  een vastgelopen proces opnieuw te starten.
- **`/readyz`** — echte gereedheid: geeft **HTTP 503** zolang de
  Discord-verbinding niet staat **of** de database niet bereikbaar/migraties
  niet in orde zijn. Pas als alles werkt volgt HTTP 200. Dit endpoint toont
  alleen *statussen* (`ok`/`unhealthy`) — nooit API-keys, tokens, DSN's of
  andere interne details.

Waarom deze verdeling? Als de database even wegvalt, blijft de bot verbonden
met Discord en herstelt de opslaglaag zichzelf (verbindingen worden opnieuw
geprobeerd). Een `healthCheckPath` die op `/readyz` staat zou de bot dan
onnodig herstarten en de Gateway-verbinding verbreken. Jij wilt wél direct
melding krijgen — dat doet UptimeRobot op `/readyz`.

### UptimeRobot instellen

1. Maak een gratis account aan op [uptimerobot.com](https://uptimerobot.com).
2. **Add New Monitor** → kies type **HTTP(s)**.
3. Vul in:
   - *Friendly Name*: `AI-Discord-Builder readiness`;
   - *URL*: `https://<jouw-servicenaam>.onrender.com/readyz`;
   - *Monitoring Interval*: 5 minuten.
4. Optioneel: voeg een tweede monitor toe voor
   `https://<jouw-servicenaam>.onrender.com/healthz` als je ook
   proces-incidenten los wilt zien.
5. Zet je e-mail/SMS-notificaties aan.

UptimeRobot krijgt HTTP 503 zodra de bot of database niet operationeel is en
waarschuwt je dan. Je kunt een geslaagde check herkennen aan de statuscode:
alleen HTTP 200 betekent "ready".

## 3. Stap-voor-stap deployen

### Stap 1 — Discord bot klaarzetten

Volg "Discord bot configureren" in de [README](../README.md#discord-bot-configureren).
Je hebt straks nodig:

- de **Bot Token** (Developer Portal → Bot → Reset Token);
- een AI-key: **Groq** (aanbevolen, gratis tier beschikbaar) of **OpenAI**;
- de bot-uitnodigings-URL met scopes `bot` + `applications.commands` en de
  rechten `Manage Channels`, `Manage Roles`, `Send Messages`.

### Stap 2 — Repository op GitHub zetten

Render deploait vanuit GitHub (geen zip-uploads).

1. [Fork](https://github.com/bmeesss/AI-Discord-Builder/fork) deze repository
   (of maak een eigen repo en push de code).
2. Controleer dat `render.yaml` in de root staat — dat is de *Blueprint* die
   Render leest.

### Stap 3 — Blueprint deployen

1. Maak een account op [dashboard.render.com](https://dashboard.render.com).
2. Kies **New → Blueprint** en koppel je GitHub-account.
3. Selecteer de repository uit stap 2. Render leest `render.yaml` en toont
   wat er aangemaakt wordt: één web service (`ai-discord-builder`) en één
   Postgres-database (`ai-discord-builder-db`).
4. Render vraagt nu éénmalig de geheime waarden (deze staan **nooit** in git):
   - `DISCORD_TOKEN` — je Discord bot-token;
   - `GROQ_API_KEY` — je Groq-key (laat leeg bij OpenAI);
   - `OPENAI_API_KEY` — je OpenAI-key (laat leeg bij Groq);
   - `AI_PROVIDER` — typ `groq` (of `openai`).
5. Bevestig. Render bouwt de Docker-image, maakt de database aan en injecteert
   `DATABASE_URL` automatisch. De bot draait de database-migraties bij het
   opstarten (`DB_MIGRATE_ON_STARTUP=true`).

### Stap 4 — controleren

1. Open in het Render-dashboard de **Logs** van de service. Verwachte regels:
   `Applied database migrations: ...` (alleen de eerste keer),
   `PostgreSQL backend ready`, `Logged in as <bot> (ID: ...)`.
2. Open `https://<jouw-servicenaam>.onrender.com/readyz` — je zou
   `{"status": "ready", ...}` moeten zien met HTTP 200.
3. Test in Discord: `/ask maak een kanaal genaamd test`.
4. Zet UptimeRobot op zoals in sectie 2.

### Stap 5 — bot uitnodigen

Gebruik de uitnodigings-URL uit de Developer Portal (scopes `bot` en
`applications.commands`) en voeg de bot toe aan je server.

## 4. Updaten

Doe een `git push` naar de gekoppelde branch. In `render.yaml` staat
`autoDeployTrigger: checksPass`: Render deploait pas als de GitHub CI-tests
groen zijn. Handmatig kan ook via **Manual Deploy → Deploy latest commit**.

Tijdens een deploy blijft de oude versie draaien tot de nieuwe gezond is
(zero-downtime); de bot maakt daarna opnieuw verbinding met Discord.

## 5. Welke environment variables zet ik waar?

Op Render hoef je bijna niets te doen: `DATABASE_BACKEND`, `DATABASE_URL` en
`AI_PROVIDER` komen uit `render.yaml`, en `PORT` zet Render zelf. De rest
heeft werkende standaarden. De volledige tabel staat in
[self-hosting.md](self-hosting.md#complete-configuratietabel); de enige
variabelen die je zelf invult zijn:

| Variabele | Waar | Waarde |
| --- | --- | --- |
| `DISCORD_TOKEN` | Render (gevraagd bij Blueprint) | Discord bot-token |
| `AI_PROVIDER` | Render (gevraagd bij Blueprint) | `groq` of `openai` |
| `GROQ_API_KEY` | Render (gevraagd bij Blueprint) | Groq API-key |
| `OPENAI_API_KEY` | Render (gevraagd bij Blueprint) | OpenAI API-key |

Wil je later iets bijstellen (bijv. `MAX_ACTIONS_PER_PLAN` of `LOG_LEVEL`),
voeg het toe bij **Environment** in het Render-dashboard. Let op: variabelen
die in `render.yaml` staan worden bij een Blueprint-sync opnieuw ingesteld;
`sync: false`-variabelen (`DISCORD_TOKEN`, `AI_PROVIDER`, keys) blijven onder
jouw beheer.

## 6. Ollama op Render?

`AI_PROVIDER=ollama` vereist een bereikbare Ollama-server. Dat kan op Render
alleen met een aparte (dure, trage) service en is **niet** de bedoeling van
deze blueprint — gebruik op Render Groq of OpenAI. Lokaal of via Docker
Compose draait Ollama wél; zie [local-ai.md](local-ai.md).

## 7. Backups

Render Postgres kun je backuppen via het dashboard (**Backups**-tab van de
database) en met `pg_dump`:

```bash
# Lokaal (met de Render External Database URL uit het dashboard):
pg_dump "$RENDER_DATABASE_URL" > backup.sql
```

De database bevat alleen bot-state (conversations, memories,
rollback-history); de Discord-server zelf is de bron van waarheid.

## 8. Problemen oplossen

| Symptoom | Oorzaak → oplossing |
| --- | --- |
| Deploy faalt met "port detection" | De service luistert niet op `PORT`. Deze repo lost dit automatisch op (`WEB_PORT`→`PORT`→`8080`); zorg dat je de laatste code draait. |
| `/readyz` geeft 503, `discord: starting` | De bot kon niet inloggen — controleer `DISCORD_TOKEN` en de Logs. |
| `/readyz` geeft 503, `components.database: unhealthy` | Database niet bereikbaar of migraties niet gelukt — kijk in de Logs naar `Database initialization failed`. |
| Logs: `Missing required environment variables: GROQ_API_KEY` | Je koos `AI_PROVIDER=groq` maar vulde de key niet in. Vul de key bij **Environment** (of kies een andere provider). |
| Slash-commands verschijnen niet in Discord | Commands worden per guild gesynct bij `on_ready`; wacht ~1 minuut na een deploy en controleer de Logs op `Synced N commands to guild`. |
| Bot reageert niet, UptimeRobot alarmeert | Klik in Render op **Restart**; lees de Logs voor de oorzaak. |
| Database "connection limit" | Je draait meer instanties dan `numInstances: 1`; laat dit op 1 staan. |

## 9. Kostenindicatie

- Web Service `0.5c-512mb`: kleinste betaalde compute-plan (prijs:
  [render.com/pricing](https://render.com/pricing)).
- Postgres `0.1c-256mb`: kleinste betaalde database (15 GB schijf inbegrepen).
- UptimeRobot: gratis tier monitort 50 URLs.

Gratis (`plan: free`) kan voor een korte test, maar niet voor productie:
Free web services vallen na 15 minuten inactiviteit stil, en Free Render
Postgres verloopt 30 dagen na aanmaak.
