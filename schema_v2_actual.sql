-- NutriTrack v2 schema snapshot exported from the actual migrated database,
-- including the additive USDA meal-item migration.
-- Reference only. No DROP statements; safe to keep as documentation.
PRAGMA foreign_keys = ON;

CREATE TABLE allergens (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE brands (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL UNIQUE,
    manufacturer TEXT
);

CREATE TABLE categories (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE food_aliases (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    food_id INTEGER NOT NULL,
    alias   TEXT NOT NULL,
    FOREIGN KEY (food_id) REFERENCES foods(id) ON DELETE CASCADE,
    UNIQUE (food_id, alias)
);

CREATE TABLE food_allergens (
    food_id     INTEGER NOT NULL,
    allergen_id INTEGER NOT NULL,
    PRIMARY KEY (food_id, allergen_id),
    FOREIGN KEY (food_id)     REFERENCES foods(id)     ON DELETE CASCADE,
    FOREIGN KEY (allergen_id) REFERENCES allergens(id) ON DELETE RESTRICT
);

CREATE TABLE food_categories (
    food_id     INTEGER NOT NULL,
    category_id INTEGER NOT NULL,
    PRIMARY KEY (food_id, category_id),
    FOREIGN KEY (food_id)     REFERENCES foods(id)      ON DELETE CASCADE,
    FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE RESTRICT
);

CREATE TABLE food_nutrition (
    -- 1:1 extension of foods: food_id is the primary key, not a surrogate
    -- id, so "more than one nutrition row per food" isn't just avoided by
    -- convention, it's schema-structurally impossible.
    food_id          INTEGER PRIMARY KEY,
    -- The reference amount these numbers are FOR, e.g. 100 g or 100 ml.
    -- Restricted to mass/volume (not a count like "piece"), matching how
    -- nutrition databases (INDB, USDA) actually report density figures.
    -- Unit-specific servings ("1 egg", "1 cup") live in food_servings and
    -- convert back to this reference amount/unit.
    per_amount       REAL NOT NULL DEFAULT 100 CHECK (per_amount > 0),
    per_unit         TEXT NOT NULL CHECK (per_unit IN ('g', 'ml')),

    calories         REAL NOT NULL CHECK (calories >= 0),
    protein_g        REAL NOT NULL CHECK (protein_g >= 0),
    carbohydrates_g  REAL NOT NULL CHECK (carbohydrates_g >= 0),
    fat_g            REAL NOT NULL CHECK (fat_g >= 0),
    fiber_g          REAL DEFAULT 0 CHECK (fiber_g IS NULL OR fiber_g >= 0),
    sugar_g          REAL           CHECK (sugar_g IS NULL OR sugar_g >= 0),
    sodium_mg        REAL           CHECK (sodium_mg IS NULL OR sodium_mg >= 0),

    -- Room for future micronutrients. All nullable: most sources (INDB
    -- included) won't populate every one of these for every food.
    calcium_mg       REAL CHECK (calcium_mg IS NULL OR calcium_mg >= 0),
    iron_mg          REAL CHECK (iron_mg IS NULL OR iron_mg >= 0),
    potassium_mg     REAL CHECK (potassium_mg IS NULL OR potassium_mg >= 0),
    vitamin_a_mcg    REAL CHECK (vitamin_a_mcg IS NULL OR vitamin_a_mcg >= 0),
    vitamin_c_mg     REAL CHECK (vitamin_c_mg IS NULL OR vitamin_c_mg >= 0),
    vitamin_d_mcg    REAL CHECK (vitamin_d_mcg IS NULL OR vitamin_d_mcg >= 0),
    vitamin_b12_mcg  REAL CHECK (vitamin_b12_mcg IS NULL OR vitamin_b12_mcg >= 0),

    FOREIGN KEY (food_id) REFERENCES foods(id) ON DELETE CASCADE
);

CREATE TABLE food_servings (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    food_id          INTEGER NOT NULL,
    serving_name     TEXT NOT NULL,          -- e.g. '1 idli', '1 cup', '100 g'
    serving_quantity REAL NOT NULL CHECK (serving_quantity > 0),
    -- At most one default serving per food — enforced structurally below
    -- via a partial unique index, not just left to the app layer.
    is_default       INTEGER NOT NULL DEFAULT 0 CHECK (is_default IN (0, 1)),
    FOREIGN KEY (food_id) REFERENCES foods(id) ON DELETE CASCADE,
    UNIQUE (food_id, serving_name)
);

CREATE TABLE food_sources (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,          -- e.g. 'INDB', 'USDA'
    version     TEXT,                   -- e.g. '2024_11'
    url         TEXT,
    description TEXT,
    imported_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (name, version)
);

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
    -- Single classification tier, not a junction table. A food is not a
    -- set of independent diet tags — it's one ordinal classification
    -- (Vegan is a subset of Vegetarian, which is a subset of Eggetarian,
    -- which is a subset of Non-Vegetarian). A many-to-many table would
    -- allow contradictory combinations and add a join to a filter that's
    -- actually just a scalar comparison (see app.py's DIET_COMPATIBILITY
    -- map). Reviewed again in this revision; kept unchanged.
    dietary_type   TEXT NOT NULL DEFAULT 'Vegetarian'
                   CHECK (dietary_type IN ('Vegetarian', 'Non-Vegetarian', 'Vegan', 'Eggetarian')),
    description    TEXT,
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (source_id) REFERENCES food_sources(id) ON DELETE RESTRICT,
    FOREIGN KEY (brand_id)  REFERENCES brands(id)        ON DELETE SET NULL,
    UNIQUE (source_id, source_food_id)
);

CREATE TABLE meal_items (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    meal_id INTEGER NOT NULL,
    food_id INTEGER NOT NULL,

    quantity REAL NOT NULL DEFAULT 1 CHECK (quantity > 0),

    -- Snapshot of foods / food_nutrition / food_servings AT THE MOMENT OF
    -- LOGGING. calories_at_logging etc. are for ONE unit of whatever
    -- serving the user picked (already the result of the food_servings
    -- scale-factor conversion described above) — the app still multiplies
    -- by `quantity` to get a meal item's total, exactly as it does today.
    food_name_at_logging        TEXT NOT NULL,
    serving_name_at_logging     TEXT NOT NULL,
    serving_quantity_at_logging REAL NOT NULL CHECK (serving_quantity_at_logging > 0),
    serving_unit_at_logging     TEXT NOT NULL,

    calories_at_logging REAL NOT NULL CHECK (calories_at_logging >= 0),
    protein_at_logging  REAL NOT NULL CHECK (protein_at_logging >= 0),
    carbs_at_logging    REAL NOT NULL CHECK (carbs_at_logging >= 0),
    fat_at_logging       REAL NOT NULL CHECK (fat_at_logging >= 0),
    fiber_at_logging     REAL DEFAULT 0 CHECK (fiber_at_logging IS NULL OR fiber_at_logging >= 0),

    FOREIGN KEY (meal_id) REFERENCES meals(id) ON DELETE CASCADE,
    -- RESTRICT, not CASCADE: deleting a food must never silently delete a
    -- user's meal history.
    FOREIGN KEY (food_id) REFERENCES foods(id) ON DELETE RESTRICT
);

CREATE TABLE meals (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    meal_type   TEXT NOT NULL CHECK (meal_type IN ('Breakfast', 'Lunch', 'Snack', 'Dinner')),
    logged_date DATE NOT NULL,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE usda_meal_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    meal_id INTEGER NOT NULL,
    fdc_id INTEGER NOT NULL,
    quantity REAL NOT NULL CHECK (quantity > 0),
    food_name_at_logging TEXT NOT NULL,
    serving_name_at_logging TEXT NOT NULL,
    serving_grams_at_logging REAL NOT NULL CHECK (serving_grams_at_logging > 0),
    calories_at_logging REAL NOT NULL CHECK (calories_at_logging >= 0),
    protein_at_logging REAL NOT NULL CHECK (protein_at_logging >= 0),
    carbs_at_logging REAL NOT NULL CHECK (carbs_at_logging >= 0),
    fat_at_logging REAL NOT NULL CHECK (fat_at_logging >= 0),
    fiber_at_logging REAL NOT NULL DEFAULT 0 CHECK (fiber_at_logging >= 0),
    FOREIGN KEY (meal_id) REFERENCES meals(id) ON DELETE CASCADE
);

CREATE TABLE profiles (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id             INTEGER NOT NULL UNIQUE,
    age                 INTEGER CHECK (age IS NULL OR (age BETWEEN 1 AND 120)),
    height_cm           REAL    CHECK (height_cm IS NULL OR (height_cm BETWEEN 50 AND 250)),
    weight_kg           REAL    CHECK (weight_kg IS NULL OR (weight_kg BETWEEN 20 AND 300)),
    -- Kept as a single CHECK-constrained column, not a lookup table — see
    -- "Design decisions" note in the accompanying explanation. Reviewed
    -- again in this revision; no concrete reason found to change it.
    dietary_preference  TEXT NOT NULL DEFAULT 'Vegetarian'
                        CHECK (dietary_preference IN ('Vegetarian', 'Non-Vegetarian', 'Vegan', 'Eggetarian')),
    -- Free text on purpose: this is an app-level enum (app.py's
    -- GENERAL_GOALS) that may change without needing a schema migration.
    general_goal        TEXT,
    updated_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

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

CREATE TABLE user_allergies (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    allergen_id INTEGER NOT NULL,
    FOREIGN KEY (user_id)     REFERENCES users(id)    ON DELETE CASCADE,
    FOREIGN KEY (allergen_id) REFERENCES allergens(id) ON DELETE RESTRICT,
    UNIQUE (user_id, allergen_id)
);

CREATE TABLE users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    email         TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE user_identities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    provider TEXT NOT NULL,
    provider_subject TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    UNIQUE (provider, provider_subject),
    UNIQUE (user_id, provider)
);

CREATE INDEX idx_user_identities_user_id ON user_identities(user_id);

CREATE INDEX idx_food_aliases_alias ON food_aliases(alias);

CREATE INDEX idx_food_allergens_allergen_id  ON food_allergens(allergen_id);

CREATE INDEX idx_food_categories_category_id ON food_categories(category_id);

CREATE UNIQUE INDEX idx_food_servings_one_default
    ON food_servings(food_id)
    WHERE is_default = 1;

CREATE INDEX idx_foods_name ON foods(name);

CREATE INDEX idx_meal_items_food_id ON meal_items(food_id);

CREATE INDEX idx_meal_items_meal_id ON meal_items(meal_id);

CREATE INDEX idx_usda_meal_items_meal_id ON usda_meal_items(meal_id);
CREATE INDEX idx_usda_meal_items_fdc_id ON usda_meal_items(fdc_id);

CREATE INDEX idx_meals_user_date ON meals(user_id, logged_date);

CREATE INDEX idx_recipe_items_food_id   ON recipe_items(food_id);

CREATE INDEX idx_recipe_items_recipe_id ON recipe_items(recipe_id);

CREATE INDEX idx_user_allergies_allergen_id  ON user_allergies(allergen_id);
