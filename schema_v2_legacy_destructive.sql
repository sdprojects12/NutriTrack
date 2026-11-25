-- HISTORICAL COPY: the original header's schema.sql reference predates the
-- current canonical schema.sql. This file is not an initialization input.
-- ============================================================================
-- NutriTrack 2.0 — normalized database schema (DESIGN STAGE)
-- ============================================================================
-- This file is a NEW, separate schema. It does not modify, replace, or run
-- against the existing schema.sql / nutritrack.db. It is meant to be applied
-- to a fresh database file once the corresponding app.py migration work is
-- planned and approved.
--
-- SQLite-compatible SQL. Run `PRAGMA foreign_keys = ON;` on every connection
-- that uses this schema (the app already does this in get_db() — see
-- app.py). It's also declared here so the file behaves correctly if someone
-- runs it directly via the sqlite3 CLI.
-- ============================================================================

PRAGMA foreign_keys = ON;

-- Drop order respects FK dependencies (children before parents), so this
-- file can be re-run idempotently against its OWN fresh database file.
DROP TABLE IF EXISTS recipe_items;
DROP TABLE IF EXISTS recipes;
DROP TABLE IF EXISTS meal_items;
DROP TABLE IF EXISTS meals;
DROP TABLE IF EXISTS food_aliases;
DROP TABLE IF EXISTS food_allergens;
DROP TABLE IF EXISTS food_categories;
DROP TABLE IF EXISTS food_nutrition;
DROP TABLE IF EXISTS foods;
DROP TABLE IF EXISTS categories;
DROP TABLE IF EXISTS brands;
DROP TABLE IF EXISTS food_sources;
DROP TABLE IF EXISTS user_allergies;
DROP TABLE IF EXISTS allergens;
DROP TABLE IF EXISTS profiles;
DROP TABLE IF EXISTS users;


-- ============================================================================
-- USERS & PROFILES
-- ============================================================================

CREATE TABLE users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    email         TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE profiles (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id             INTEGER NOT NULL UNIQUE,
    age                 INTEGER CHECK (age IS NULL OR (age BETWEEN 1 AND 120)),
    height_cm           REAL    CHECK (height_cm IS NULL OR (height_cm BETWEEN 50 AND 250)),
    weight_kg           REAL    CHECK (weight_kg IS NULL OR (weight_kg BETWEEN 20 AND 300)),
    -- Kept as a single CHECK-constrained column, not a lookup table — see
    -- "Design decisions" note #1 in the accompanying explanation.
    dietary_preference  TEXT NOT NULL DEFAULT 'Vegetarian'
                        CHECK (dietary_preference IN ('Vegetarian', 'Non-Vegetarian', 'Vegan', 'Eggetarian')),
    -- Free text on purpose: this is an app-level enum (app.py's
    -- GENERAL_GOALS) that may change without needing a schema migration.
    general_goal        TEXT,
    updated_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);


-- ============================================================================
-- ALLERGENS (shared vocabulary — used by both users and foods)
-- ============================================================================
-- Renamed from "allergies" (Stage 2/3 name) to "allergens": the table
-- describes substances, not a person's condition, and this same lookup
-- table is now shared by USER_ALLERGIES and FOOD_ALLERGENS.

CREATE TABLE allergens (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE user_allergies (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    allergen_id INTEGER NOT NULL,
    FOREIGN KEY (user_id)     REFERENCES users(id)     ON DELETE CASCADE,
    FOREIGN KEY (allergen_id) REFERENCES allergens(id)  ON DELETE RESTRICT,
    UNIQUE (user_id, allergen_id)
);


-- ============================================================================
-- FOOD PROVENANCE: SOURCES & BRANDS
-- ============================================================================

CREATE TABLE food_sources (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,          -- e.g. 'INDB', 'USDA'
    version     TEXT,                   -- e.g. '2024_11'
    url         TEXT,
    description TEXT,
    imported_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (name, version)
);

CREATE TABLE brands (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL UNIQUE,
    manufacturer TEXT
);


-- ============================================================================
-- FOODS — canonical identity only (no nutrition numbers live here)
-- ============================================================================

CREATE TABLE foods (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT NOT NULL,
    source_id      INTEGER NOT NULL,
    -- The ID this food had in its source dataset (e.g. the INDB food
    -- code). Nullable because not every future source is guaranteed to
    -- expose one; SQLite treats multiple NULLs in a UNIQUE constraint as
    -- distinct, so that doesn't create false collisions below.
    source_food_id TEXT,
    brand_id       INTEGER,             -- NULL for unbranded/generic foods
    -- Provisional classification distinguishing a raw ingredient from a
    -- prepared dish or a packaged product. Kept small on purpose — this
    -- is not a full food taxonomy.
    food_type      TEXT NOT NULL DEFAULT 'Ingredient'
                   CHECK (food_type IN ('Ingredient', 'Prepared Dish', 'Packaged Product')),
    -- Single classification tier, not a junction table — see "Design
    -- decisions" note #1.
    dietary_type   TEXT NOT NULL DEFAULT 'Vegetarian'
                   CHECK (dietary_type IN ('Vegetarian', 'Non-Vegetarian', 'Vegan', 'Eggetarian')),
    description    TEXT,
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (source_id) REFERENCES food_sources(id) ON DELETE RESTRICT,
    FOREIGN KEY (brand_id)  REFERENCES brands(id)        ON DELETE SET NULL,
    UNIQUE (source_id, source_food_id)
);

-- Structured nutrition, decoupled from identity. A food can have more than
-- one row here (e.g. one 'per_100g' row and one 'per_serving' row) but at
-- most one of each basis — see "Design decisions" note #2.
CREATE TABLE food_nutrition (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    food_id          INTEGER NOT NULL,
    serving_quantity REAL NOT NULL CHECK (serving_quantity > 0),
    serving_unit     TEXT NOT NULL,          -- e.g. 'g', 'ml', 'piece', 'cup'
    basis            TEXT NOT NULL CHECK (basis IN ('per_serving', 'per_100g')),

    calories         REAL NOT NULL CHECK (calories >= 0),
    protein_g        REAL NOT NULL CHECK (protein_g >= 0),
    carbohydrates_g  REAL NOT NULL CHECK (carbohydrates_g >= 0),
    fat_g            REAL NOT NULL CHECK (fat_g >= 0),
    fiber_g          REAL DEFAULT 0   CHECK (fiber_g IS NULL OR fiber_g >= 0),
    sugar_g          REAL             CHECK (sugar_g IS NULL OR sugar_g >= 0),
    sodium_mg        REAL             CHECK (sodium_mg IS NULL OR sodium_mg >= 0),

    -- Room for future micronutrients. All nullable: most sources (INDB
    -- included) won't populate every one of these for every food.
    calcium_mg       REAL CHECK (calcium_mg IS NULL OR calcium_mg >= 0),
    iron_mg          REAL CHECK (iron_mg IS NULL OR iron_mg >= 0),
    potassium_mg     REAL CHECK (potassium_mg IS NULL OR potassium_mg >= 0),
    vitamin_a_mcg    REAL CHECK (vitamin_a_mcg IS NULL OR vitamin_a_mcg >= 0),
    vitamin_c_mg     REAL CHECK (vitamin_c_mg IS NULL OR vitamin_c_mg >= 0),
    vitamin_d_mcg    REAL CHECK (vitamin_d_mcg IS NULL OR vitamin_d_mcg >= 0),
    vitamin_b12_mcg  REAL CHECK (vitamin_b12_mcg IS NULL OR vitamin_b12_mcg >= 0),

    FOREIGN KEY (food_id) REFERENCES foods(id) ON DELETE CASCADE,
    UNIQUE (food_id, basis)
);


-- ============================================================================
-- CATEGORIES (many-to-many with foods)
-- ============================================================================

CREATE TABLE categories (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);

-- Composite primary key doubles as the "unique combination" constraint —
-- no surrogate id column, matching how this junction was specified.
CREATE TABLE food_categories (
    food_id     INTEGER NOT NULL,
    category_id INTEGER NOT NULL,
    PRIMARY KEY (food_id, category_id),
    FOREIGN KEY (food_id)     REFERENCES foods(id)      ON DELETE CASCADE,
    FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE RESTRICT
);


-- ============================================================================
-- FOOD ALLERGENS (many-to-many; replaces the old comma-separated text)
-- ============================================================================

CREATE TABLE food_allergens (
    food_id     INTEGER NOT NULL,
    allergen_id INTEGER NOT NULL,
    PRIMARY KEY (food_id, allergen_id),
    FOREIGN KEY (food_id)     REFERENCES foods(id)     ON DELETE CASCADE,
    FOREIGN KEY (allergen_id) REFERENCES allergens(id) ON DELETE RESTRICT
);


-- ============================================================================
-- FOOD ALIASES (search resolution: Brinjal -> Eggplant -> Aubergine)
-- ============================================================================

CREATE TABLE food_aliases (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    food_id INTEGER NOT NULL,
    alias   TEXT NOT NULL,
    FOREIGN KEY (food_id) REFERENCES foods(id) ON DELETE CASCADE,
    UNIQUE (food_id, alias)
);


-- ============================================================================
-- MEALS & MEAL ITEMS
-- ============================================================================

CREATE TABLE meals (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    meal_type   TEXT NOT NULL CHECK (meal_type IN ('Breakfast', 'Lunch', 'Snack', 'Dinner')),
    logged_date DATE NOT NULL,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- meal_items carries a full historical nutrition snapshot. See "Why the
-- historical snapshot exists" in the accompanying explanation.
CREATE TABLE meal_items (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    meal_id  INTEGER NOT NULL,
    food_id  INTEGER NOT NULL,
    quantity REAL NOT NULL DEFAULT 1 CHECK (quantity > 0),

    -- Snapshot of foods/food_nutrition AT THE MOMENT OF LOGGING. These are
    -- PER-SERVING values (same semantics as the live food_nutrition row
    -- they were copied from) — the app still multiplies by `quantity` to
    -- get a meal item's total, exactly as it does today with a live JOIN.
    calories_at_logging         REAL NOT NULL CHECK (calories_at_logging >= 0),
    protein_at_logging          REAL NOT NULL CHECK (protein_at_logging >= 0),
    carbs_at_logging            REAL NOT NULL CHECK (carbs_at_logging >= 0),
    fat_at_logging               REAL NOT NULL CHECK (fat_at_logging >= 0),
    fiber_at_logging            REAL DEFAULT 0 CHECK (fiber_at_logging IS NULL OR fiber_at_logging >= 0),
    serving_quantity_at_logging REAL NOT NULL CHECK (serving_quantity_at_logging > 0),
    serving_unit_at_logging     TEXT NOT NULL,

    FOREIGN KEY (meal_id) REFERENCES meals(id) ON DELETE CASCADE,
    -- RESTRICT, not CASCADE: deleting a food must never silently delete a
    -- user's meal history. See "Design decisions" note #3.
    FOREIGN KEY (food_id) REFERENCES foods(id) ON DELETE RESTRICT
);


-- ============================================================================
-- RECIPES & RECIPE ITEMS
-- ============================================================================

CREATE TABLE recipes (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL,
    description  TEXT,
    instructions TEXT,
    meal_type    TEXT NOT NULL CHECK (meal_type IN ('Breakfast', 'Lunch', 'Snack', 'Dinner')),
    dietary_type TEXT NOT NULL DEFAULT 'Vegetarian'
                 CHECK (dietary_type IN ('Vegetarian', 'Non-Vegetarian', 'Vegan', 'Eggetarian')),
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Replaces the old free-text `ingredients` column with real rows tying
-- each recipe to canonical foods.
CREATE TABLE recipe_items (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    recipe_id INTEGER NOT NULL,
    food_id   INTEGER NOT NULL,
    quantity  REAL NOT NULL CHECK (quantity > 0),
    unit      TEXT NOT NULL,
    FOREIGN KEY (recipe_id) REFERENCES recipes(id) ON DELETE CASCADE,
    -- Same RESTRICT reasoning as meal_items.food_id: don't let a food
    -- deletion silently strip an ingredient out of a curated recipe.
    FOREIGN KEY (food_id)   REFERENCES foods(id)   ON DELETE RESTRICT
);


-- ============================================================================
-- INDEXES
-- ============================================================================
-- users.email, profiles.user_id, allergens.name, categories.name,
-- brands.name, food_sources(name, version) and foods(source_id,
-- source_food_id) are all already backed by the UNIQUE constraints above
-- (SQLite creates an index automatically for every UNIQUE constraint), so
-- they are deliberately NOT duplicated below.

-- meals: the app's most common query is "this user's meals on this date"
-- (dashboard totals, logged/not-logged status).
CREATE INDEX idx_meals_user_date ON meals(user_id, logged_date);

-- meal_items: FK columns are not auto-indexed by SQLite.
CREATE INDEX idx_meal_items_meal_id ON meal_items(meal_id);
CREATE INDEX idx_meal_items_food_id ON meal_items(food_id);

-- foods: name search/sort.
CREATE INDEX idx_foods_name ON foods(name);

-- food_aliases: this is the whole point of the table (resolve alias -> food).
CREATE INDEX idx_food_aliases_alias ON food_aliases(alias);

-- Junction tables: their composite PRIMARY KEY already indexes the FIRST
-- column efficiently, so only the second column of each pair needs an
-- explicit index for the reverse lookup direction.
CREATE INDEX idx_food_categories_category_id ON food_categories(category_id);
CREATE INDEX idx_food_allergens_allergen_id  ON food_allergens(allergen_id);
CREATE INDEX idx_user_allergies_allergen_id  ON user_allergies(allergen_id);

-- recipe_items: no composite PK here (a recipe listing the same food
-- twice at different quantities is legitimate), so both FK columns need
-- their own index.
CREATE INDEX idx_recipe_items_recipe_id ON recipe_items(recipe_id);
CREATE INDEX idx_recipe_items_food_id   ON recipe_items(food_id);
