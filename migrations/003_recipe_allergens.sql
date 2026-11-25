-- Preserve curated recipe allergy labels even before recipe ingredients are
-- fully normalized. Safe to apply more than once to the normalized schema.
CREATE TABLE IF NOT EXISTS recipe_allergens (
    recipe_id INTEGER NOT NULL,
    allergen_id INTEGER NOT NULL,
    PRIMARY KEY (recipe_id, allergen_id),
    FOREIGN KEY (recipe_id) REFERENCES recipes(id) ON DELETE CASCADE,
    FOREIGN KEY (allergen_id) REFERENCES allergens(id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_recipe_allergens_allergen_id
    ON recipe_allergens(allergen_id);
