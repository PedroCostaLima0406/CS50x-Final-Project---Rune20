-- USERS
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL
);

-- CAMPAIGNS
CREATE TABLE campaigns (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    join_code TEXT NOT NULL UNIQUE,
    created_by INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- CHARACTERS
CREATE TABLE characters (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    race TEXT NOT NULL,
    class TEXT NOT NULL,
    level INTEGER DEFAULT 1,
    xp INTEGER DEFAULT 0,
    gold INTEGER DEFAULT 0,
    owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    campaign_id INTEGER REFERENCES campaigns(id) ON DELETE SET NULL,

    -- Core stats
    strength INTEGER DEFAULT 8,
    dexterity INTEGER DEFAULT 8,
    constitution INTEGER DEFAULT 8,
    intelligence INTEGER DEFAULT 8,
    wisdom INTEGER DEFAULT 8,
    charisma INTEGER DEFAULT 8,
    hit_points INTEGER DEFAULT 8,
    max_hit_points INTEGER DEFAULT 8,
    temp_hp INTEGER DEFAULT 0,

    background TEXT NOT NULL,
    notes TEXT NOT NULL,
    skills_notes TEXT NOT NULL
);

-- SPELL CATALOG
CREATE TABLE spell_catalog (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    level INTEGER,
    school TEXT,
    casting_time TEXT,
    range TEXT,
    components TEXT,
    duration TEXT
);

-- CHARACTER SPELLS
CREATE TABLE character_spells (
    character_id INTEGER NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
    spell_id INTEGER NOT NULL REFERENCES spell_catalog(id) ON DELETE CASCADE,
    learned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (character_id, spell_id)
);

-- ITEM CATALOG
CREATE TABLE item_catalog (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    item_type TEXT,
    rarity TEXT,
    weight NUMERIC,
    value INTEGER
);

-- CUSTOM ITEMS
CREATE TABLE custom_items (
    id SERIAL PRIMARY KEY,
    created_by INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT,
    UNIQUE (created_by, name)
);

-- CHARACTER INVENTORY
CREATE TABLE character_inventory (
    character_id INTEGER NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
    item_id INTEGER REFERENCES item_catalog(id) ON DELETE CASCADE,
    custom_item_id INTEGER REFERENCES custom_items(id) ON DELETE CASCADE,
    quantity INTEGER DEFAULT 1,

    CHECK (
    (item_id IS NOT NULL AND custom_item_id IS NULL)
    OR
    (item_id IS NULL AND custom_item_id IS NOT NULL)
    )
);

-- Unique constraints for one of either item type
CREATE UNIQUE INDEX unique_character_inventory_item
  ON character_inventory(character_id, item_id)
  WHERE custom_item_id IS NULL;

CREATE UNIQUE INDEX unique_character_inventory_custom_item
  ON character_inventory(character_id, custom_item_id)
  WHERE item_id IS NULL;

-- DICE LOGS
CREATE TABLE dice_logs (
    id SERIAL PRIMARY KEY,
    campaign_id INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    character_id INTEGER NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
    roll_result INTEGER NOT NULL,
    display_name TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX idx_campaigns_join_code ON campaigns(join_code);
CREATE INDEX idx_campaigns_created_by ON campaigns(created_by);

CREATE INDEX idx_characters_owner_id ON characters(owner_id);
CREATE INDEX idx_characters_campaign_id ON characters(campaign_id);

CREATE INDEX idx_character_spells_id ON character_spells(character_id);
CREATE INDEX idx_character_spells_spell_id ON character_spells(spell_id);

CREATE INDEX idx_custom_items_created_by ON custom_items(created_by);

CREATE INDEX idx_character_inventory_character_id ON character_inventory(character_id);
CREATE INDEX idx_inventory_item_id ON character_inventory(item_id);
CREATE INDEX idx_inventory_custom_item_id ON character_inventory(custom_item_id);

CREATE INDEX idx_dice_logs_campaign_id ON dice_logs(campaign_id);
CREATE INDEX idx_dice_logs_character_id ON dice_logs(character_id);
CREATE INDEX idx_dice_logs_created_at ON dice_logs(created_at);
