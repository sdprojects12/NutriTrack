-- Add USDA meal snapshots without rebuilding the populated local meal tables.
-- Safe to run once against nutritrack_v2.db; existing meals are untouched.
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

CREATE INDEX idx_usda_meal_items_meal_id ON usda_meal_items(meal_id);
CREATE INDEX idx_usda_meal_items_fdc_id ON usda_meal_items(fdc_id);
