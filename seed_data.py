"""
Seed data for NutriTrack.

DATA SOURCE (foods table)
--------------------------
Foods are now imported from the real Indian Nutrient Databank (INDB)
export: data/Anuvaad_INDB_2024_11.xlsx
(https://www.anuvaad.org.in/indian-nutrient-databank/)

All the parsing, per-serving-vs-per-100g logic, and the name-based
category / dietary-type / allergen heuristics live in
scripts/import_indb.py, which is fully documented there (read the module
docstring for the exact column mapping and its caveats). This file just
calls that script and inserts the results into the `foods` table.

DATA SOURCE (recipes table)
-----------------------------
The `recipes` table (used for Stage 4 meal suggestions) is still a small,
manually curated list below — INDB is a nutrition table, not a curated
"recommend this for breakfast" list, so recipe descriptions and meal-type
tagging are authored by hand here. This is unchanged from before and will
be revisited in Stage 4.
"""

import os

from scripts.import_indb import load_foods_from_workbook

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INDB_XLSX_PATH = os.path.join(BASE_DIR, "data", "Anuvaad_INDB_2024_11.xlsx")

ALLERGIES = [
    # Sentinel option so a user can explicitly confirm "I have no allergies"
    # during profile setup, distinguishing that from "hasn't answered yet"
    # (which is just zero rows in user_allergies). See app.py's
    # is_profile_complete() / NO_ALLERGY_LABEL.
    "No Known Allergies",
    "Peanut",
    "Tree Nuts",
    "Dairy",
    "Gluten",
    "Soy",
    "Egg",
    "Sesame",
    "Mustard",
]

# meal_type in ('Breakfast', 'Lunch', 'Snack', 'Dinner')
# Each tuple: (name, description, ingredients, instructions, meal_type,
#              dietary_type, allergens, calories, protein, carbs, fat)
RECIPES = [
    ("Vegetable Poha", "Light, fluffy flattened rice tempered with mustard seeds, curry leaves and peanuts.",
     "Poha (flattened rice), onion, green chilli, curry leaves, mustard seeds, turmeric, peanuts, lemon, coriander",
     "Rinse poha until soft. Temper mustard seeds, curry leaves and peanuts in oil, add onion and turmeric, then fold in poha. Finish with lemon and coriander.",
     "Breakfast", "Vegan", "Peanut", 250, 4.5, 42.0, 7.0),
    ("Masala Dosa", "Crisp rice-and-lentil crepe filled with spiced potato masala, served with chutney and sambar.",
     "Dosa batter (rice, urad dal), potato, onion, mustard seeds, turmeric, curry leaves, oil",
     "Spread fermented batter thin on a hot griddle. Cook until crisp, add the spiced potato masala, fold and serve hot with chutney and sambar.",
     "Breakfast", "Vegan", "", 350, 6.5, 55.0, 12.0),
    ("Sprouted Moong Salad", "Fresh sprouted moong beans tossed with onion, tomato, lemon and chaat masala.",
     "Sprouted moong beans, onion, tomato, lemon, chaat masala, coriander",
     "Toss sprouted moong with chopped onion and tomato. Season with lemon juice and chaat masala, garnish with coriander.",
     "Breakfast", "Vegan", "", 150, 9.0, 22.0, 1.5),
    ("Rajma Chawal", "Classic kidney bean curry served over steamed rice.",
     "Rajma (kidney beans), onion, tomato, ginger-garlic, rice, garam masala",
     "Pressure-cook soaked rajma until soft. Simmer in an onion-tomato masala until thick. Serve over steamed rice.",
     "Lunch", "Vegan", "", 465, 15.0, 85.0, 6.4),
    ("Paneer Butter Masala with Roti", "Creamy tomato-based paneer curry served with whole wheat roti.",
     "Paneer, tomato, butter, cream, cashew, whole wheat roti",
     "Simmer a tomato-cashew gravy with butter and cream, add paneer cubes and warm through. Serve with roti.",
     "Lunch", "Vegetarian", "Dairy,Gluten", 480, 16.5, 30.0, 31.5),
    ("Chicken Curry with Rice", "Home-style chicken curry served with steamed rice.",
     "Chicken, onion, tomato, ginger-garlic, curry spices, rice",
     "Brown onions, add ginger-garlic and spices, then chicken and tomato. Simmer until cooked through and serve with steamed rice.",
     "Lunch", "Non-Vegetarian", "", 525, 30.3, 53.0, 20.4),
    ("Sambar Rice", "Steamed rice mixed with tangy lentil-and-vegetable sambar.",
     "Toor dal, mixed vegetables, tamarind, sambar powder, rice",
     "Cook toor dal with vegetables until soft, season with tamarind and sambar powder, then mix through steamed rice.",
     "Lunch", "Vegan", "", 350, 10.3, 67.0, 3.9),
    ("Roasted Makhana", "Lightly roasted fox nuts with a pinch of rock salt and spices.",
     "Makhana (fox nuts), ghee or oil, rock salt, spices",
     "Dry roast makhana in a pan with a little ghee until crisp, season with rock salt and spices.",
     "Snack", "Vegan", "", 130, 4.0, 22.0, 3.0),
    ("Peanut Chaat", "Boiled peanuts tossed with onion, tomato, chilli and lemon.",
     "Peanuts, onion, tomato, green chilli, lemon, chaat masala",
     "Boil peanuts until tender, toss with chopped onion, tomato and chilli, finish with lemon and chaat masala.",
     "Snack", "Vegan", "Peanut", 180, 7.5, 15.0, 10.0),
    ("Curd with Fruit", "Fresh curd topped with seasonal fruit.",
     "Curd (yogurt), seasonal fruit, honey (optional)",
     "Whisk chilled curd smooth, top with chopped seasonal fruit and a drizzle of honey if desired.",
     "Snack", "Vegetarian", "Dairy", 160, 7.5, 20.0, 6.3),
    ("Masala Chai with Biscuits", "Spiced milk tea served with two digestive biscuits.",
     "Tea leaves, milk, ginger, cardamom, sugar, digestive biscuits",
     "Simmer tea leaves with milk, ginger and cardamom. Strain, sweeten to taste, and serve with biscuits.",
     "Snack", "Vegetarian", "Dairy,Gluten", 220, 4.5, 30.0, 8.5),
    ("Dal Tadka with Chapati", "Yellow lentils tempered with cumin and garlic, served with chapati.",
     "Toor/moong dal, cumin, garlic, tomato, ghee, chapati",
     "Boil dal until soft. Prepare a cumin-garlic-tomato tempering in ghee and pour over the dal. Serve with chapati.",
     "Dinner", "Vegan", "Gluten", 310, 15.1, 53.0, 3.9),
    ("Palak Paneer with Roti", "Spinach curry with soft paneer cubes, served with roti.",
     "Spinach, paneer, onion, tomato, ginger-garlic, roti",
     "Blanch and puree spinach. Simmer with an onion-tomato base, add paneer cubes and warm through. Serve with roti.",
     "Dinner", "Vegetarian", "Dairy,Gluten", 384, 15.2, 28.0, 25.5),
    ("Egg Curry with Rice", "Boiled eggs simmered in a spiced onion-tomato gravy, served with rice.",
     "Boiled eggs, onion, tomato, ginger-garlic, curry spices, rice",
     "Prepare a spiced onion-tomato gravy, add halved boiled eggs and simmer briefly. Serve with steamed rice.",
     "Dinner", "Eggetarian", "Egg", 465, 18.3, 53.6, 19.4),
    ("Vegetable Pulao with Raita", "Fragrant rice cooked with mixed vegetables, served with cool cucumber raita.",
     "Rice, mixed vegetables, whole spices, curd, cucumber",
     "Sauté whole spices and vegetables, add rice and water and cook until fluffy. Serve with cucumber raita.",
     "Dinner", "Vegetarian", "Dairy", 460, 9.9, 65.0, 13.5),
]


def seed(db):
    """Populate allergies, foods and recipes reference tables (idempotent)."""
    for allergy in ALLERGIES:
        db.execute(
            "INSERT OR IGNORE INTO allergies (name) VALUES (?)", (allergy,)
        )

    foods = load_foods_from_workbook(INDB_XLSX_PATH)
    db.execute("DELETE FROM foods")
    db.executemany(
        """INSERT INTO foods
           (name, category, serving_size, calories, protein, carbs, fat,
            fiber, dietary_type, allergens)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        foods,
    )

    db.execute("DELETE FROM recipes")
    db.executemany(
        """INSERT INTO recipes
           (name, description, ingredients, instructions, meal_type,
            dietary_type, allergens, calories, protein, carbs, fat)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        RECIPES,
    )

    db.commit()


if __name__ == "__main__":
    # Lets you run `python seed_data.py` directly from the project root,
    # as an alternative to `flask seed-db`. Both use this same seed()
    # function and both write to the same nutritrack.db — this does not
    # create or duplicate any database file.
    import sqlite3

    DB_PATH = os.path.join(BASE_DIR, "nutritrack.db")

    if not os.path.exists(DB_PATH):
        raise SystemExit(
            f"'{DB_PATH}' doesn't exist yet. Run `flask init-db` first "
            f"(with FLASK_APP=app.py set) to create the schema, then "
            f"re-run this script."
        )

    connection = sqlite3.connect(DB_PATH)
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        seed(connection)
        food_count = connection.execute("SELECT COUNT(*) FROM foods").fetchone()[0]
        recipe_count = connection.execute("SELECT COUNT(*) FROM recipes").fetchone()[0]
        allergy_count = connection.execute("SELECT COUNT(*) FROM allergies").fetchone()[0]
        print(f"Seeded {DB_PATH}:")
        print(f"  {food_count} foods (from INDB)")
        print(f"  {recipe_count} recipes")
        print(f"  {allergy_count} allergies")
    finally:
        connection.close()
