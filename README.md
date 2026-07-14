# AI-Discord-Builder

Een AI-gestuurde Discord bot waarmee gebruikers servers bouwen en beheren via
natuurlijke taal (`/ask <vraag>`). De AI maakt een veilig, gevalideerd
actieplan en voert dit pas uit na expliciete bevestiging via knoppen.

## Projectstructuur

```
AI-Discord-Builder/
├── main.py                # Entrypoint
├── config.py               # Environment config
├── requirements.txt
├── .env.example
├── commands/
│   └── ask.py               # /ask slash command + confirm/cancel UI
├── ai/
│   ├── client.py            # AI API calls + JSON validatie
│   └── prompts.py           # System prompt / action-schema
├── builder/
│   ├── executor.py          # Voert gevalideerd plan uit
│   ├── categories.py
│   ├── channels.py
│   └── roles.py
├── security/
│   └── permissions.py       # Admin-check, bot-permissie check
└── logs/
    └── actions.log          # Audit log (wordt aangemaakt bij eerste run)
```

## 1. Discord bot token instellen

1. Ga naar https://discord.com/developers/applications
2. **New Application** → geef een naam (bv. "AI Discord Builder")
3. Ga naar **Bot** in het linkermenu → **Reset Token** → kopieer de token
4. Zet onder **Privileged Gateway Intents**: schakel **Server Members Intent** in
   (nodig om permissies van leden goed te lezen)
5. Ga naar **OAuth2 → URL Generator**:
   - Scopes: `bot`, `applications.commands`
   - Bot permissions: `Manage Channels`, `Manage Roles`, `Send Messages`,
     `Embed Links`, `Read Message History`
6. Kopieer de gegenereerde URL, open die in je browser, en nodig de bot uit op
   je server.

## 2. AI API instellen

**Groq (aanbevolen, gratis tier beschikbaar):**
1. Ga naar https://console.groq.com → API Keys → maak een nieuwe key
2. Zet deze in `.env` als `GROQ_API_KEY`

**OpenAI (optioneel alternatief):**
1. Ga naar https://platform.openai.com/api-keys
2. Zet `AI_PROVIDER=openai` en `OPENAI_API_KEY=...` in `.env`

## 3. Lokaal testen

```bash
# Kopieer het voorbeeld-env bestand en vul je gegevens in
cp .env.example .env
# open .env en vul DISCORD_TOKEN en GROQ_API_KEY in

# Installeer dependencies
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt

# Start de bot
python main.py
```

Als alles goed gaat zie je in de console:
```
Ingelogd als AI Discord Builder#1234 (ID: ...)
Synced X slash command(s)
```

Ga naar je Discord server en typ `/ask maak een minecraft smp server`. Let op:
het kan tot een uur duren voordat slash commands globaal zichtbaar zijn na de
eerste sync; op de testserver waar de bot net is uitgenodigd gaat dit meestal
binnen enkele minuten.

## 4. Hosten op Render

1. Push dit project naar een GitHub repository
2. Ga naar https://dashboard.render.com → **New +** → **Background Worker**
   (geen Web Service — deze bot luistert niet op een HTTP poort)
3. Koppel je GitHub repo
4. Instellingen:
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `python main.py`
5. Onder **Environment**, voeg alle variabelen uit `.env.example` toe met je
   echte waarden (DISCORD_TOKEN, GROQ_API_KEY, etc.)
6. Deploy. Render herstart de bot automatisch bij een crash of nieuwe push.

> **Let op:** Render's gratis tier voor Background Workers kan slapen bij
> inactiviteit op sommige planvarianten — check de huidige Render-voorwaarden
> voor een always-on bot.

## 5. Gebruik

```
/ask Maak een Minecraft SMP Discord server
/ask maak een kanaal genaamd 67
/ask verwijder kanaal test
/ask verplaats kanaal general naar community
/ask maak een moderator rol
```

De bot toont altijd eerst een plan met ✅ Bevestigen / ❌ Annuleren knoppen.
Alleen na bevestiging worden er daadwerkelijk wijzigingen gemaakt.

## Uitbreidingsmogelijkheden (toekomst)

- **Server templates**: voeg vooraf gedefinieerde JSON-plannen toe in
  `ai/prompts.py` of een nieuw `templates/` bestand voor Minecraft SMP,
  Gaming, School, YouTube, Esports, Bedrijf — en laat de AI kiezen welk
  template het beste past, of gebruik ze als few-shot voorbeelden in de prompt.
- **AI branding**: nieuwe actie-types zoals `set_server_description` of
  `generate_rules_channel_content` toevoegen aan het schema + executor.
- **Advanced mode** ("maak mijn server professioneler"): bouw een
  `server_context` string (huidige categorieën/kanalen/rollen ophalen via
  `guild.categories`, `guild.channels`, `guild.roles`) en geef die mee aan
  `generate_plan()` — het schema ondersteunt dit al via de
  `server_context` parameter in `ai/prompts.py`.
- **Database**: voor multi-server geheugen (bv. onthouden welke templates per
  server gebruikt zijn) kun je later SQLite of Postgres toevoegen zonder de
  bestaande structuur te breken — de executor blijft stateless per aanroep.
lol