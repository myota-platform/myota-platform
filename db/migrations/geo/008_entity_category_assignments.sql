-- Synchronized from myota-geodata-service/migrations/008_entity_category_assignments.sql.
-- The primary entity_type_code remains for compatibility; this relation stores
-- every shared category assigned to an entity.
CREATE TABLE IF NOT EXISTS geodata_entity_category (
    entity_id uuid NOT NULL REFERENCES geodata_entity(id) ON DELETE CASCADE,
    category_id uuid NOT NULL REFERENCES entity_type(id) ON DELETE RESTRICT,
    category_code text NOT NULL,
    is_primary boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (entity_id, category_id),
    UNIQUE (entity_id, category_code)
);

CREATE INDEX IF NOT EXISTS geodata_entity_category_code_idx
    ON geodata_entity_category (category_code, entity_id);

CREATE UNIQUE INDEX IF NOT EXISTS geodata_entity_category_primary_idx
    ON geodata_entity_category (entity_id) WHERE is_primary;

-- Backfill the legacy primary category so existing entities immediately use
-- the relational assignment model after the migration.
INSERT INTO geodata_entity_category(entity_id, category_id, category_code, is_primary)
SELECT id, entity_type_id, entity_type_code, true
FROM geodata_entity
WHERE entity_type_id IS NOT NULL AND entity_type_code IS NOT NULL
ON CONFLICT (entity_id, category_id) DO UPDATE
SET category_code = EXCLUDED.category_code, is_primary = true;
