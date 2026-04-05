# Streaming Ingestion — Local Dev Suite

A hybrid local pipeline that generates fake data with Python → publishes it to **Kafka** → consumes it and stores every message in **PostgreSQL**. The infrastructure runs in Docker while the producer and consumer run as standalone Python scripts.

```
┌─────────────┐     Kafka topic     ┌──────────────┐     INSERT     ┌──────────────────────┐
│  producer   │ ───────────────────►│   consumer   │ ──────────────►│ staging.raw_events   │
│ (Faker/py)  │    raw_events       │    (py)      │                │  (PostgreSQL JSONB)  │
└─────────────┘                     └──────────────┘                └──────────────────────┘
(runs on host)                       (runs on host)                     (runs in Docker)
```

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Project Structure](#2-project-structure)
3. [First-Time Setup](#3-first-time-setup)
4. [Running the Stack](#4-running-the-stack)
5. [Checking It Works](#5-checking-it-works)
6. [Configuration Guide](#6-configuration-guide)
7. [Changing the Message Schema](#7-changing-the-message-schema)
8. [Stopping and Cleaning Up](#8-stopping-and-cleaning-up)
9. [Troubleshooting](#9-troubleshooting)
10. [Architecture Deep-Dive](#10-architecture-deep-dive)

---

## 1. Prerequisites

You need the following installed on your machine:

| Tool | Minimum Version | How to Check |
|---|---|---|
| Python | 3.11+ | `python3 --version` |
| Docker Desktop / Docker Engine | 24+ | `docker --version` |
| Docker Compose (plugin) | v2+ | `docker compose version` |

> **Linux only — Docker permission fix**
> If you get `permission denied while trying to connect to the Docker API`, run:
> ```bash
> sudo usermod -aG docker $USER
> newgrp docker
> ```
> Then try again. You may need to log out and back in for the group change to apply system-wide.

---

## 2. Project Structure

```
streaming-ingestion/
│
├── docker-compose.yaml        ← Defines infrastructure (Zookeeper, Kafka, Postgres)
├── .env.example               ← Template for environment variables (copy to .env)
├── .env                       ← YOUR local env file (not committed to git)
├── requirements.txt           ← Python dependencies for both scripts
│
├── config/
│   └── schema.yaml            ← ⭐ Main configuration file (edit this to customise)
│
├── src/
│   ├── producer.py            ← Python script: generates + sends Kafka messages
│   └── consumer.py            ← Python script: reads Kafka + inserts into Postgres
│
└── init-db/
    └── init.sql               ← SQL run once on Postgres startup (creates the table)
```

---

## 3. First-Time Setup

### Step 1 — Clone / navigate to the project

```bash
cd streaming-ingestion
```

### Step 2 — Create your `.env` file

```bash
cp .env.example .env
```

The default values in `.env` are fine for local development. The file looks like:

```dotenv
POSTGRES_USER=admin
POSTGRES_PASSWORD=password
POSTGRES_DB=streaming_db
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
```

> ⚠️ Never commit `.env` to git. Add it to `.gitignore` if you haven't already.

### Step 3 — Install Python Dependencies

You only need one virtual environment at the project root for both scripts.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

---

## 4. Running the Stack

You run the infrastructure via Docker, but you run the Python scripts manually from the project root.

### Step 1 — Start Infrastructure

Start Zookeeper, Kafka, and PostgreSQL in the background:

```bash
docker compose up -d
```

> Kafka can take 20–30 seconds to become healthy. Wait for it using `docker compose ps`.

### Step 2 — Run the Consumer

Open a **new terminal tab**, activate the virtual environment, load `.env`, and run the consumer:

```bash
source .venv/bin/activate
set -a; source .env; set +a  # Load env vars manually for the script
python src/consumer.py
```

*Note: You can also use a tool like `python-dotenv` inside the script, but the above command loads the env vars straight into the bash session.*

### Step 3 — Run the Producer

Open **another terminal tab**, activate the virtual environment, and run the producer:

```bash
source .venv/bin/activate
python src/producer.py
```

---

## 5. Checking It Works

### Watch live logs

The producer and consumer output their logs directly to the terminal tabs where you ran them.

**Healthy producer output looks like:**
```
2026-04-02 19:30:00 [producer] INFO Starting producer → topic=raw_events  burst_mode=uniform  duration=60s
2026-04-02 19:30:01 [producer] INFO Messages sent so far: 100
```

**Healthy consumer output looks like:**
```
2026-04-02 19:30:01 [consumer] INFO Connected to PostgreSQL at localhost:5432/streaming_db
2026-04-02 19:30:01 [consumer] INFO Subscribed to topic: raw_events
2026-04-02 19:30:02 [consumer] INFO Rows inserted so far: 100
```

### Query Postgres directly

Open a psql shell inside the Postgres container:

```bash
docker compose exec postgres psql -U admin -d streaming_db
```

Then run some SQL:

```sql
-- How many rows have arrived?
SELECT COUNT(*) FROM staging.raw_events;

-- Preview the last 5 messages
SELECT id, payload, received_at
FROM staging.raw_events
ORDER BY id DESC
LIMIT 5;

-- Look inside a specific field in the JSON payload
SELECT payload->>'email' AS email,
       payload->>'event_type' AS event_type,
       payload->>'amount' AS amount,
       received_at
FROM staging.raw_events
ORDER BY id DESC
LIMIT 10;
```

Type `\q` to quit psql.

### Check service health

```bash
docker compose ps
```

The infrastructure services should show `healthy` or `running`.

---

## 6. Configuration Guide

Everything for Kafka and generation logic is controlled from **`config/schema.yaml`**. 

```yaml
kafka:
  topic: raw_events
  bootstrap_servers: localhost:9092

producer:
  duration_seconds: 60         # How long to run. 0 = run forever
  burst_mode: uniform          # "uniform" or "random"
  uniform_interval_ms: 500     # (uniform mode) ms between messages
```

### After changing config

Simply stop (`Ctrl+C`) and restart your Python scripts (`python src/producer.py` or `python src/consumer.py`).

---

## 7. Changing the Message Schema

The `schema:` section in `config/schema.yaml` maps field names to [Faker](https://faker.readthedocs.io/) methods. You can freely add, remove, or change fields.

```yaml
schema:
  user_id:
    faker_provider: uuid4
  name:
    faker_provider: name
  event_type:
    faker_provider: random_element
    elements: [click, view, purchase, scroll]
```

After editing, simply restart the producer script.

> The `staging.raw_events` table stores the full message as `JSONB`, so you never need to change any SQL or Python code when the schema changes.

---

## 8. Stopping and Cleaning Up

Stop your Python scripts using `Ctrl+C`.

Then clean up infrastructure:

```bash
# Stop all containers (keeps data in Postgres volume)
docker compose down

# Stop AND delete all data (full reset)
docker compose down -v
```

---

## 9. Troubleshooting

### Producer exits immediately

Check the terminal output.
Common causes:
- Kafka isn't ready yet (did you run `docker compose up -d`?).
- A bad value in `config/schema.yaml` — check for typos in `faker_provider` names.
- Virtual environment isn't activated.

### Consumer not inserting rows

Check the terminal output.
Common causes:
- Postgres isn't ready.
- It cannot find the environment variables (`POSTGRES_USER`, etc.). Ensure you loaded `.env` into your shell before running it.

### Kafka topic doesn't exist yet

`KAFKA_AUTO_CREATE_TOPICS_ENABLE: "true"` is set inside Docker — the topic is created automatically when the producer first publishes. No manual topic creation needed.

---

## 10. Architecture Deep-Dive

### Why two Kafka listeners?

Kafka runs two listeners:
- `PLAINTEXT://kafka:29092` — used **inside Docker** (inter-broker communication).
- `PLAINTEXT_HOST://localhost:9092` — used from your **host machine**. Since our scripts run on the host now, they connect to `localhost:9092`.

### Why JSONB?

The raw table stores messages as `JSONB` (binary JSON) in Postgres. Benefits:
- Schema changes require zero SQL migrations
- You can still query individual fields with `payload->>'field_name'`

### Modifying the raw table

If you want to add columns later (e.g., a `source` or `partition_key` column), edit `init-db/init.sql`. Note: `init.sql` only runs on **first creation** of the Postgres volume. To rerun it:

```bash
docker compose down -v   # wipe the volume
docker compose up -d     # recreate — init.sql runs again
```
