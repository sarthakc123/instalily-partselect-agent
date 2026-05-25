-- PartSelect chat agent schema. Postgres 16+. No ORM, raw SQL only.
-- Compatibility is the workhorse table: it is the structured edge that the
-- check_compatibility tool resolves against, and the KG mirror of it.

CREATE TABLE IF NOT EXISTS parts (
  id              TEXT PRIMARY KEY,                 -- e.g. PS11752778
  name            TEXT NOT NULL,
  manufacturer    TEXT NOT NULL,
  appliance_type  TEXT NOT NULL,                    -- refrigerator | dishwasher | other
  part_type       TEXT NOT NULL,                    -- ice_maker, water_inlet_valve, etc.
  price_cents     INTEGER NOT NULL,
  in_stock        BOOLEAN NOT NULL DEFAULT TRUE,
  image_url       TEXT NOT NULL DEFAULT '',
  description     TEXT NOT NULL DEFAULT '',
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS parts_appliance_idx ON parts(appliance_type);
CREATE INDEX IF NOT EXISTS parts_type_idx      ON parts(part_type);
-- Trigram index for fuzzy SKU search via pg_trgm if extension available; fallback to rapidfuzz in app.
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE INDEX IF NOT EXISTS parts_id_trgm_idx ON parts USING gin (id gin_trgm_ops);

CREATE TABLE IF NOT EXISTS models (
  id              TEXT PRIMARY KEY,                 -- e.g. WDT780SAEM1
  brand           TEXT NOT NULL,
  appliance_type  TEXT NOT NULL,
  year            INTEGER,
  series          TEXT,                             -- e.g. WDT78x
  manual_url      TEXT NOT NULL DEFAULT '',
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS models_brand_idx     ON models(brand);
CREATE INDEX IF NOT EXISTS models_appliance_idx ON models(appliance_type);
CREATE INDEX IF NOT EXISTS models_series_idx    ON models(series);
CREATE INDEX IF NOT EXISTS models_id_trgm_idx   ON models USING gin (id gin_trgm_ops);

-- The compatibility edge. check_compatibility hits this table directly.
CREATE TABLE IF NOT EXISTS compatibility (
  part_id            TEXT NOT NULL REFERENCES parts(id)  ON DELETE CASCADE,
  model_id           TEXT NOT NULL REFERENCES models(id) ON DELETE CASCADE,
  sub_assembly_only  BOOLEAN NOT NULL DEFAULT FALSE,
  requires_adapter   BOOLEAN NOT NULL DEFAULT FALSE,
  supersedes         TEXT,
  PRIMARY KEY (part_id, model_id)
);
CREATE INDEX IF NOT EXISTS compat_part_idx  ON compatibility(part_id);
CREATE INDEX IF NOT EXISTS compat_model_idx ON compatibility(model_id);

CREATE TABLE IF NOT EXISTS symptoms (
  id                TEXT PRIMARY KEY,               -- e.g. SY_ICE_MAKER_NOT_WORKING
  description       TEXT NOT NULL,
  canonical_label   TEXT NOT NULL,
  appliance_type    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS symptoms_appliance_idx ON symptoms(appliance_type);
CREATE INDEX IF NOT EXISTS symptoms_label_idx     ON symptoms(canonical_label);

-- Edge: Part FIXES Symptom. Used by find_parts_by_symptom + troubleshoot KG augmentation.
CREATE TABLE IF NOT EXISTS symptom_fixes (
  symptom_id        TEXT NOT NULL REFERENCES symptoms(id) ON DELETE CASCADE,
  part_id           TEXT NOT NULL REFERENCES parts(id)    ON DELETE CASCADE,
  likelihood        REAL NOT NULL DEFAULT 0.5,
  common_cause_rank INTEGER NOT NULL DEFAULT 99,
  PRIMARY KEY (symptom_id, part_id)
);

CREATE TABLE IF NOT EXISTS install_guides (
  id                    TEXT PRIMARY KEY,
  part_id               TEXT NOT NULL UNIQUE REFERENCES parts(id) ON DELETE CASCADE,
  difficulty            TEXT NOT NULL DEFAULT 'Easy',
  estimated_minutes     INTEGER NOT NULL DEFAULT 20,
  tools_required        TEXT NOT NULL DEFAULT '',     -- comma-separated for v1
  safety_warnings       TEXT NOT NULL DEFAULT '',
  steps                 TEXT NOT NULL,                -- newline-separated for v1
  video_url             TEXT NOT NULL DEFAULT '',
  series_fitment_hint   TEXT                         -- e.g. "fits all WDT78x"; powers the 'inferred' compat path
);

CREATE TABLE IF NOT EXISTS repair_stories (
  id                TEXT PRIMARY KEY,
  appliance_type    TEXT NOT NULL,
  brand             TEXT NOT NULL,
  symptom_id        TEXT REFERENCES symptoms(id),
  title             TEXT NOT NULL,
  body              TEXT NOT NULL,
  fixing_part_id    TEXT REFERENCES parts(id)
);
CREATE INDEX IF NOT EXISTS stories_appliance_idx ON repair_stories(appliance_type);
CREATE INDEX IF NOT EXISTS stories_brand_idx     ON repair_stories(brand);

CREATE TABLE IF NOT EXISTS conversations (
  id                TEXT PRIMARY KEY,
  llm_provider      TEXT NOT NULL,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  state             JSONB NOT NULL DEFAULT '{}'::jsonb  -- session: model_no, brand, last_part
);

CREATE TABLE IF NOT EXISTS messages (
  id                BIGSERIAL PRIMARY KEY,
  conversation_id   TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  role              TEXT NOT NULL,                          -- user | assistant | tool
  content           TEXT NOT NULL,
  tool_calls        JSONB,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS messages_conv_idx ON messages(conversation_id);

-- Tickets: PII NEVER references the LLM context. contact_blob is encrypted at app layer
-- in v2; for v1 we store it raw but isolated. The LLM only sees the ticket id.
CREATE TABLE IF NOT EXISTS tickets (
  id                TEXT PRIMARY KEY,
  conversation_id   TEXT NOT NULL,
  summary           TEXT NOT NULL,
  model_number      TEXT,
  symptom_tags      TEXT NOT NULL DEFAULT '',
  status            TEXT NOT NULL DEFAULT 'open',
  contact_blob      JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
