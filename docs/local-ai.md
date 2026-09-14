# Local AI met Ollama

Local AI is volledig optioneel. AI Discord Builder blijft Groq en OpenAI
ondersteunen. Kies `AI_PROVIDER=ollama` alleen als je model lokaal wilt draaien.

Wanneer Ollama lokaal wordt gebruikt, worden prompts naar de lokale Ollama-URL
verstuurd en niet naar Groq of OpenAI. Let op: de Discord bot zelf communiceert
uiteraard nog steeds met Discord.

## Hardware en modelkeuze

De setup-tool detecteert zo goed mogelijk:

- besturingssysteem en architectuur;
- aantal CPU-cores;
- RAM;
- vrije schijfruimte;
- een NVIDIA- of AMD-GPU wanneer een officiële vendor-tool betrouwbaar
  beschikbaar is;
- Docker en of de Docker daemon draait.

Hardwaredetectie is best-effort. Een onbekende GPU of onbekend RAM wordt niet als
voldoende beschouwd; de tool geeft een waarschuwing en maakt geen overdreven
prestatieclaims.

De conservatieve standaard is:

```env
LOCAL_AI_MODEL=qwen3:4b
OLLAMA_MODEL=qwen3:4b
LOCAL_AI_AUTO_SELECT_MODEL=true
```

De waarden in de modelcatalogus zijn slechts advisories. Modelgebruik hangt af
van quantization, contextlengte, Ollama-versie en de rest van het systeem. Een
gebruiker kan altijd een ander Ollama-model instellen.

## Installatie op de host

1. Installeer de Python dependencies of gebruik de Docker-variant.
2. Maak `.env` aan vanuit `.env.example`.
3. Voer de read-only detectie uit:

```bash
python -m setup detect
```

4. Start de interactieve setup:

```bash
python -m setup setup
```

De tool:

1. inspecteert de machine;
2. controleert Ollama en de ingestelde URL;
3. vraagt toestemming voordat ontbrekende software wordt geïnstalleerd;
4. vraagt toestemming voordat een model wordt gedownload;
5. start een bestaande lokale Ollama-installatie wanneer mogelijk;
6. controleert of het model aanwezig is;
7. voert een model-smoketest uit;
8. kan alleen lokale-AI-settings naar `.env` schrijven.

Gebruik nooit `--yes` als je niet wilt toestaan dat de installer ontbrekende
componenten installeert en het model downloadt.

Voor een niet-interactieve, expliciet goedgekeurde setup:

```bash
python -m setup setup --yes
```

`detect` verandert niets. De bot zelf voert geen software-installatie uit bij
startup, ook niet wanneer `LOCAL_AI_AUTO_SETUP=true` staat. Software-installatie
hoort bij de expliciete setup-flow.

## Configuratie

```env
AI_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen3:4b
LOCAL_AI_MODEL=qwen3:4b
LOCAL_AI_AUTO_SETUP=false
LOCAL_AI_AUTO_SELECT_MODEL=true
```

De provider gebruikt de bestaande AI-planning pipeline. Ollama maakt alleen
tekst voor een AI-plan. De bestaande JSON-validation, confirmation view,
server-side permissions, executor en rollback blijven verantwoordelijk voor
Discord-wijzigingen.

## Docker

De standaard Compose-configuratie start geen Ollama (wel PostgreSQL + bot):

```bash
docker compose up -d
```

Voor local AI gebruik je expliciet de overlay:

```bash
docker compose \
  -f compose.yaml \
  -f compose.local-ai.yaml \
  up -d
```

In deze modus draaien PostgreSQL, de bot, Ollama en de eenmalige
model-initialisatie (`ollama-model`) naast elkaar.

De overlay:

- voegt alleen dan de `ollama/ollama` container toe;
- gebruikt een named volume `ollama_models`;
- publiceert Ollama alleen op localhost;
- gebruikt binnen het Docker-netwerk `http://ollama:11434`;
- plaatst geen model in de AI Discord Builder image;
- start een one-shot `ollama-model` service die het gekozen model pullt.

De `ollama-model` service voert `ollama pull` uit nadat Ollama healthy is. Bij
volgende container-restarts blijft het volume bestaan en wordt het model niet
opnieuw in de bot-image ingebouwd. Handmatig opnieuw pullen kan altijd:

```bash
docker compose \
  -f compose.yaml \
  -f compose.local-ai.yaml \
  exec ollama ollama pull qwen3:4b
```

Test de lokale provider via:

```bash
docker compose \
  -f compose.yaml \
  -f compose.local-ai.yaml \
  exec bot python -m setup test
```

Binnen Docker gebruikt de bot `OLLAMA_BASE_URL=http://ollama:11434`; een
host-gebaseerde setup-tool gebruikt `http://localhost:11434`.

Het volume blijft bestaan bij `docker compose down` en bij een container
recreate. Verwijder het niet met `docker compose down -v` als je het model wilt
behouden.

## Cloud AI blijft beschikbaar

Voor Groq:

```env
AI_PROVIDER=groq
GROQ_API_KEY=...
GROQ_MODEL=llama-3.3-70b-versatile
```

Voor OpenAI:

```env
AI_PROVIDER=openai
OPENAI_API_KEY=...
OPENAI_MODEL=gpt-4o-mini
```

Cloud-only installaties importeren of starten geen Ollama-service en downloaden
geen lokale modellen.

## Troubleshooting

### Ollama niet bereikbaar

Controleer:

```bash
python -m setup detect
curl http://localhost:11434/api/tags
```

Start Ollama handmatig als de executable wel aanwezig is maar de service niet
loopt.

### Poort 11434 is bezet

Gebruik bijvoorbeeld `OLLAMA_HOST_PORT=11435` en zet voor een host-gebaseerde
setup `OLLAMA_BASE_URL=http://localhost:11435` in `.env`. In Docker blijft de
interne containerpoort 11434 staan; alleen de host mapping verandert.

### Model ontbreekt

Controleer:

```bash
ollama list
```

of in Docker:

```bash
docker compose -f compose.yaml -f compose.local-ai.yaml exec ollama ollama list
```

### Onvoldoende RAM of diskruimte

Kies een kleiner model of maak schijfruimte vrij. De tool kan resourcegebruik
niet exact voorspellen en weigert daarom niet op basis van een onzekere GPU- of
RAM-detectie; hij geeft een waarschuwing.

### Ongeldige JSON

Ollama-output wordt door dezelfde `AIClient` en `ai.validation.parse_plan()`
verwerkt als Groq- en OpenAI-output. Een ongeldige response bereikt de executor
niet.
