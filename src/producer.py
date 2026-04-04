#!/usr/bin/env python3
"""
Kafka Producer — streams Faker-generated messages to a Kafka topic.

Configuration is read from ../config/schema.yaml which controls:
  - Kafka topic and bootstrap servers
  - Duration (seconds), set to 0 for indefinite
  - Burst mode: "uniform" or "random"
  - Message schema: field → Faker provider mapping
"""

import json
import logging
import random
import time
from decimal import Decimal
from pathlib import Path

import yaml
from faker import Faker
from confluent_kafka import Producer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [producer] %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)

# Path relative to this script directory
CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "schema.yaml"


def load_config() -> dict:
    with CONFIG_PATH.open() as f:
        return yaml.safe_load(f)


def build_message(fake: Faker, schema: dict) -> dict:
    """Dynamically call Faker methods based on the schema config."""
    record = {}
    for field, spec in schema.items():
        spec = dict(spec)  # copy so we can mutate
        provider = spec.pop("faker_provider")
        method = getattr(fake, provider)
        value = method(**spec)
        # Decimal is not JSON serialisable — convert to float
        if isinstance(value, Decimal):
            value = float(value)
        record[field] = value
    return record


def delivery_report(err, msg):
    if err:
        log.error("Delivery failed for message: %s", err)
    else:
        log.debug("Delivered to %s [partition %d] @ offset %d",
                  msg.topic(), msg.partition(), msg.offset())


def main():
    cfg = load_config()
    kafka_cfg = cfg["kafka"]
    producer_cfg = cfg["producer"]
    schema = cfg["schema"]

    fake = Faker()

    producer = Producer({
        "bootstrap.servers": kafka_cfg["bootstrap_servers"],
        "client.id": "faker-producer",
    })

    topic = kafka_cfg["topic"]
    duration = producer_cfg["duration_seconds"]
    burst_mode = producer_cfg["burst_mode"]
    uniform_ms = producer_cfg.get("uniform_interval_ms", 500)
    rand_min_ms = producer_cfg.get("random_min_ms", 100)
    rand_max_ms = producer_cfg.get("random_max_ms", 2000)

    log.info("Starting producer → topic=%s  burst_mode=%s  duration=%ss",
             topic, burst_mode, duration if duration else "∞")

    start = time.monotonic()
    count = 0

    try:
        while True:
            # Check duration limit (0 means run forever)
            if duration > 0 and (time.monotonic() - start) >= duration:
                log.info("Duration of %ds reached. Stopping.", duration)
                break

            message = build_message(fake, schema)
            payload = json.dumps(message).encode("utf-8")

            producer.produce(topic, value=payload, callback=delivery_report)
            producer.poll(0)  # trigger delivery callbacks without blocking

            count += 1
            if count % 100 == 0:
                log.info("Messages sent so far: %d", count)

            # Sleep between messages based on burst mode
            if burst_mode == "uniform":
                time.sleep(uniform_ms / 1000)
            elif burst_mode == "random":
                sleep_ms = random.uniform(rand_min_ms, rand_max_ms)
                time.sleep(sleep_ms / 1000)
            else:
                raise ValueError(f"Unknown burst_mode: {burst_mode!r}. "
                                 "Expected 'uniform' or 'random'.")

    except KeyboardInterrupt:
        log.info("Interrupted by user.")
    finally:
        log.info("Flushing remaining messages...")
        producer.flush()
        log.info("Done. Total messages sent: %d", count)


if __name__ == "__main__":
    main()
