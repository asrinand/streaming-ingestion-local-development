#!/usr/bin/env python3
"""
Kafka Consumer — reads messages from a Kafka topic and inserts them
into staging.raw_events in PostgreSQL as JSONB payloads.

Configuration is read from ../config/schema.yaml.
Postgres connection is taken from environment variables:
  POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB
  POSTGRES_HOST (default: localhost), POSTGRES_PORT (default: 5432)
"""

import json
import logging
import os
import time

import psycopg2
import yaml
from confluent_kafka import Consumer, KafkaError, KafkaException
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [consumer] %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)

# Path relative to this script directory
CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "schema.yaml"

INSERT_SQL = """
    INSERT INTO staging.raw_events (payload)
    VALUES (%s)
"""


def load_config() -> dict:
    with CONFIG_PATH.open() as f:
        return yaml.safe_load(f)


def get_pg_connection(retries: int = 10, delay: float = 3.0):
    """Attempt to connect to Postgres with retries (waits for DB to be ready)."""
    host = os.environ.get("POSTGRES_HOST", "localhost")
    port = os.environ.get("POSTGRES_PORT", "5432")
    dbname = os.environ.get("POSTGRES_DB", "streaming_db")
    user = os.environ.get("POSTGRES_USER", "admin")
    password = os.environ.get("POSTGRES_PASSWORD", "password")

    for attempt in range(1, retries + 1):
        try:
            conn = psycopg2.connect(
                host=host, port=port, dbname=dbname,
                user=user, password=password,
            )
            conn.autocommit = True
            log.info("Connected to PostgreSQL at %s:%s/%s", host, port, dbname)
            return conn
        except psycopg2.OperationalError as e:
            log.warning("Postgres not ready (attempt %d/%d): %s", attempt, retries, e)
            time.sleep(delay)

    raise RuntimeError("Could not connect to PostgreSQL after multiple retries.")


def main():
    cfg = load_config()
    kafka_cfg = cfg["kafka"]
    topic = kafka_cfg["topic"]

    consumer = Consumer({
        "bootstrap.servers": kafka_cfg["bootstrap_servers"],
        "group.id": "raw-events-consumer-group",
        "auto.offset.reset": "earliest",
        "enable.auto.commit": True,
    })

    conn = get_pg_connection()
    cursor = conn.cursor()

    consumer.subscribe([topic])
    log.info("Subscribed to topic: %s", topic)

    inserted = 0
    try:
        while True:
            msg = consumer.poll(timeout=1.0)

            if msg is None:
                continue

            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    log.debug("End of partition reached %s [%d]",
                              msg.topic(), msg.partition())
                else:
                    raise KafkaException(msg.error())
                continue

            try:
                payload = json.loads(msg.value().decode("utf-8"))
                cursor.execute(INSERT_SQL, (json.dumps(payload),))
                inserted += 1
                log.info("Rows inserted so far: %d", inserted)
            except (json.JSONDecodeError, psycopg2.Error) as e:
                log.error("Failed to process message: %s", e)

    except KeyboardInterrupt:
        log.info("Interrupted by user.")
    finally:
        consumer.close()
        cursor.close()
        conn.close()
        log.info("Shutdown complete. Total rows inserted: %d", inserted)


if __name__ == "__main__":
    main()
