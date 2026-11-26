# Gratis deployen op Render Free (€0/maand)

Deze gids zet AI-Discord-Builder als **gratis, databasevrije** installatie op
[Render](https://render.com): één Free web service, verder niets. Monitoring
loopt via [UptimeRobot Free](https://uptimerobot.com). Maandelijks kostenplaatje:
**€0**.

Alles hieronder is geschreven voor beginners; je hoeft geen Render-ervaring
te hebben.

## 1. Wat wordt er gedeployd?

[`render.yaml`](../render.yaml) beschrijft precies één resource:

- **`ai-discord-builder`** — een Free (`plan: free`) web service die de
  `Dockerfile` uit deze repository draait.

Er is **geen** database, geen persistent disk en geen andere betaalde dienst.
De bot slaat rollback-history en conversatie-logs op in lokale JSON-bestanden
in `/app/data` (zie [self-hosting.md](self-hosting.md)).

De web service luistert op de poort uit de `PORT`-variabele die Render zelf
instelt (standaard `10000`); de bot herkent dit automatisch (`WEB_PORT` →
`PORT` → `8080`).

## 2. Blijft de Discord Gateway-verbinding de gratis service actief?

**Nee.** Dit is de belangrijkste verwachting om bij te stellen. Gecontroleerd
tegen de actuele Render-documentatie
([render.com/docs/free](https://render.com/docs/free)):

> Render *spins down* a Free web service that goes 15 minutes without
> receiving any inbound traffic. This includes both HTTP requests and
> WebSocket messages from existing connections.

- Een Free web service valt **na 15 minuten zonder inkomend verkeer** in
  slaap. Het proces wordt gestopt.
- De Discord Gateway is een **uitgaande** WebSocket-verbinding die de bot
  zélf opent. Dat telt niet als inkomend verkeer en houdt de service dus
  niet wakker. Bij een slaapstand valt de verbinding sowieso weg (het proces
  stopt).
- Bij een nieuw inkomend request wordt de service weer gewekt; dat duurt
  **ongeveer 1 minuut**.

### Wat houdt de service dan wél actief?

De UptimeRobot-monitor uit stap 5: elke **5 minuten** doet UptimeRobot Free
een HTTP-request naar `https://<servicenaam>.onrender.com/readyz`. Dat is
inkomend verkeer → de service blijft in de praktijk continu wakker. Met een
interval van 5 minuten wordt de grens van 15 minuten nooit bereikt.

Dus: de gratis opstelling **werkt**, maar de bot-uptime hangt af van die
monitoring:

- houdt UptimeRobot op (account stopgezet, storing langer dan 15 minuten),
  dan slaapt de service in en is de bot offline tot de volgende check;
- na elke slaapstand/wekker is er ~1 minuut opstarttijd voordat de bot weer
  op Discord reageert;
- Render mag een Free web service **op elk moment herstarten**;
- Render mag een Free web service opschorten als die uitzonderlijk veel
  verkeer naar buiten genereert (denk aan continue AI-API-calls) — zie
  "Service-initiated traffic threshold" in de Render-docs;
- je workspace krijgt 750 gratis instance-uren per maand; een 24/7 actieve
  service gebruikt er ~730, dus het past — maar het is krap.

Wil je absolute uptime zonder deze kanttekeningen, dan is een betaalde
instance de eerlijke optie — maar de harde eis van dit project is €0, en met
bovenstaande begrepen werkt dat.

## 3. Belangrijk: bestanden zijn tijdelijk op Render Free

Render Free web services hebben een **tijdelijk bestandssysteem**. Alle
wijzigingen aan lokale bestanden — dus ook `actions.json` en
`conversations.json` in `/app/data` — gaan **verloren** bij:

- elke redeploy;
- elke herstart (Render herstart Free services op elk moment);
- elke slaapstand (spin-down).

Gevolg: rollback-history en conversatie-context blijven bewaard zolang de
service onafgebroken draait, maar beginnen leeg na elke herstart/wekker. De
bot blijft volledig functioneren; alleen `/rollback` zegt dan tijdelijk
"No history found". Op een eigen server of Docker-volume blijven de
bestanden wél bewaard (zie [self-hosting.md](self-hosting.md)).

## 4. Stap-voor-stap deployen

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
   wat er aangemaakt wordt: één web service (`ai-discord-builder`), plan
   **Free**. Er verschijnt géén database.
4. Render vraagt éénmalig de geheime waarden (deze staan **nooit** in git):
   - `DISCORD_TOKEN` — je Discord bot-token;
   - `GROQ_API_KEY` — je Groq-key (laat leeg bij OpenAI);
   - `OPENAI_API_KEY` — je OpenAI-key (laat leeg bij Groq);
   - `AI_PROVIDER` — typ `groq` (of `openai`).
5. Bevestig. Render bouwt de Docker-image en start de bot. Er zijn geen
   migraties of database-stappen.

### Stap 4 — controleren

1. Open in het Render-dashboard de **Logs** van de service. Verwachte regels:
   `JSON storage ready (data dir: /app/data)`, `Logged in as <bot> (ID: ...)`.
2. Open `https://<jouw-servicenaam>.onrender.com/readyz` — je zou
   `{"status": "ready", ...}` moeten zien met HTTP 200.
3. Test in Discord: `/ask maak een kanaal genaamd test`.

### Stap 5 — UptimeRobot instellen (verplicht voor uptime!)

1. Maak een gratis account aan op [uptimerobot.com](https://uptimerobot.com).
2. **Add New Monitor** → kies type **HTTP(s)**.
3. Vul in:
   - *Friendly Name*: `AI-Discord-Builder readiness`;
   - *URL*: `https://<jouw-servicenaam>.onrender.com/readyz`;
   - *Monitoring Interval*: 5 minuten.
4. Zet je e-mail/SMS-notificaties aan.

Deze check doet twee dingen tegelijk: hij houdt de Free service **wakker**
(zie sectie 2) en hij waarschuwt je zodra de bot niet ready is (HTTP 503).
Zet desnoods een tweede monitor op `/healthz` als je proces-incidenten los
wilt zien.

### Stap 6 — bot uitnodigen

Gebruik de uitnodigings-URL uit de Developer Portal (scopes `bot` en
`applications.commands`) en voeg de bot toe aan je server.

## 5. Updaten

Doe een `git push` naar de gekoppelde branch. In `render.yaml` staat
`autoDeployTrigger: checksPass`: Render deploait pas als de GitHub CI-tests
groen zijn. Handmatig kan ook via **Manual Deploy → Deploy latest commit**.

Let op: elke deploy wist de JSON-bestanden (sectie 3).

## 6. Welke environment variables zet ik waar?

Op Render hoef je bijna niets te doen: `DATA_DIR` en `PORT` zijn automatisch.
De enige variabelen die je zelf invult zijn de vier die Render bij het
Blueprint-vraagt: `DISCORD_TOKEN`, `AI_PROVIDER`, `GROQ_API_KEY`/
`OPENAI_API_KEY`. De volledige tabel staat in
[self-hosting.md](self-hosting.md#complete-configuratietabel).

Wil je later iets bijstellen (bijv. `MAX_ACTIONS_PER_PLAN` of `LOG_LEVEL`),
voeg het toe bij **Environment** in het Render-dashboard. Let op: variabelen
die in `render.yaml` staan worden bij een Blueprint-sync opnieuw ingesteld;
`sync: false`-variabelen (`DISCORD_TOKEN`, `AI_PROVIDER`, keys) blijven onder
jouw beheer.

## 7. Ollama op Render?

`AI_PROVIDER=ollama` vereist een bereikbare Ollama-server en dat is op een
Free web service niet mogelijk (geen resources voor, geen persistent disk).
Gebruik op Render Groq of OpenAI. Lokaal of via Docker Compose draait Ollama
wél; zie [local-ai.md](local-ai.md).

## 8. Problemen oplossen

| Symptoom | Oorzaak → oplossing |
| --- | --- |
| Bot offline, UptimeRobot alarmeert, service "sleeping" | De service is in slaapstand; de volgende check wekt hem (~1 minuut). Controleer of je monitor-interval 5 minuten is en niet gepauzeerd. |
| `/readyz` geeft 503, `discord: starting` | De bot kon niet inloggen — controleer `DISCORD_TOKEN` en de Logs. |
| `/readyz` geeft 503, `components.storage: unhealthy` | De container-schijf is niet beschrijfbaar; check de Logs. |
| Deploy faalt met "port detection" | De service luistert niet op `PORT`. Deze repo lost dit automatisch op; zorg dat je de laatste code draait. |
| Logs: `Missing required environment variables: GROQ_API_KEY` | Je koos `AI_PROVIDER=groq` maar vulde de key niet in. Vul de key bij **Environment**. |
| Slash-commands verschijnen niet in Discord | Commands worden per guild gesynct bij `on_ready`; wacht ~1 minuut na een deploy/herstart en check de Logs op `Synced N commands to guild`. |
| `/rollback` zegt "No history found" | De JSON-history is gewist door een herstart/redeploy/slaapstand — verwacht op Render Free (sectie 3). |
| Service geschorst door Render | Waarschijnlijk door de "service-initiated traffic"-drempel (AI-API-calls) of overschreden free hours; zie de Render-docs over Free-beperkingen. |

## 9. Kosten

- Render Free web service: **€0** (750 gratis instance-uren per maand per
  workspace).
- UptimeRobot Free: **€0** (50 monitors, interval 5 minuten).
- Groq: gratis tier beschikbaar; OpenAI is betaald per gebruik.

Er zijn geen andere resources nodig.
