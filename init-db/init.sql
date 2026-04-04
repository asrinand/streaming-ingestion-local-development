-- Create the staging schema
CREATE SCHEMA IF NOT EXISTS staging;

-- Raw events table — stores every Kafka message as a JSONB payload
CREATE TABLE IF NOT EXISTS staging.raw_events (
    id          SERIAL       PRIMARY KEY,
    payload     JSONB        NOT NULL,
    received_at TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
