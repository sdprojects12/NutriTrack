"""
Import script: Indian Nutrient Databank (INDB) -> NutriTrack `foods` table.

Source file: data/Anuvaad_INDB_2024_11.xlsx
Source project: https://www.anuvaad.org.in/indian-nutrient-databank/

WHAT'S IN THE SOURCE FILE
--------------------------
The workbook has a single sheet ("Sheet1") with 1,014 Indian food/recipe
rows and 82 columns: a food code, food name, a primary-source tag, ~39
per-100g nutrient columns (energy_kcal, protein_g, carb_g, fat_g, fibre_g,
plus micronutrients), a `servings_unit` label (e.g. "bowl", "piece", "cup"),
and ~39 matching per-serving ("unit_serving_*") nutrient columns.

Confirmed by direct inspection (see chat) — every row has non-null values
for food_name and the per-100g macro columns; 917 of 1,014 rows also have
usable per-serving figures (rows with no `servings_unit` label fall back
to their per-100g values, reported as "100 g").

COLUMN MAPPING (INDB -> our `foods` table)
-------------------------------------------
  foods.name          <- food_name                          (stripped)
  foods.serving_size   <- servings_unit                       ("1 <unit>",
                           or "100 g" when servings_unit is blank)
  foods.calories       <- unit_serving_energy_kcal if available,
                           else energy_kcal (per 100 g)
  foods.protein        <- unit_serving_protein_g   if available,
                           else protein_g            (per 100 g)
  foods.carbs          <- unit_serving_carb_g       if available,
                           else carb_g               (per 100 g)
  foods.fat             <- unit_serving_fat_g        if available,
                           else fat_g                (per 100 g)
  foods.fiber           <- unit_serving_fibre_g      if available,
                           else fibre_g              (per 100 g)

  "Prefer per-serving values when available" (per the project brief) is
  implemented literally: we use the unit_serving_* columns whenever the
  row has both a non-blank servings_unit AND a non-null unit_serving_*
  value, and fall back to the always-present per-100g columns otherwise.

  food_code and primarysource are read but NOT stored — they're INDB's
  internal bookkeeping fields and have no equivalent column in our schema.

COLUMNS INDB DOES **NOT** PROVIDE (and how we filled the gap)
----------------------------------------------------------------
INDB has no category, dietary-type (veg/non-veg/vegan/eggetarian), or
allergen columns at all — it is a pure nutrition table, not a tagging
system. So for:

  foods.category       <- derived heuristically, by keyword-matching the
                           food name against a small set of category word
                           lists (e.g. "curry"/"sabzi"/"dal" -> "Curries &
                           Gravies"). See CATEGORY_RULES below.
  foods.dietary_type    <- derived heuristically the same way: names
                           containing a meat/fish keyword -> Non-Vegetarian;
                           containing "egg" (and not "eggplant") ->
                           Eggetarian; containing a dairy keyword ->
                           Vegetarian; otherwise -> Vegan.
  foods.allergens       <- derived heuristically: the name is scanned for
                           keywords tied to each of our 8 tracked allergens
                           (Peanut, Tree Nuts, Dairy, Gluten, Soy, Egg,
                           Sesame, Mustard).

THIS IS A NAME-ONLY HEURISTIC, NOT INGREDIENT DATA. IMPORTANT CAVEAT:
INDB doesn't give us an ingredient list, so a dish whose name doesn't
mention a dairy/nut/gluten word (e.g. a yogurt-based curry that isn't
named "curd curry") will be under-tagged. This is good enough for a
prototype demo, but it is NOT a substitute for verified ingredient data
and should not be relied on for someone with a serious allergy. Flag this
clearly anywhere allergens are surfaced in the UI.

USAGE
-----
    from scripts.import_indb import load_foods_from_workbook
    rows = load_foods_from_workbook("data/Anuvaad_INDB_2024_11.xlsx")
    # rows is a list of tuples matching the `foods` table column order:
    # (name, category, serving_size, calories, protein, carbs, fat,
    #  fiber, dietary_type, allergens)

Run this file directly for a quick import summary / spot-check:
    python scripts/import_indb.py
"""

import os
import openpyxl

# Column indices in the source sheet (0-based), confirmed by inspection.
COL_FOOD_NAME = 1
COL_ENERGY_KCAL_100G = 4
COL_CARB_100G = 5
COL_PROTEIN_100G = 6
COL_FAT_100G = 7
COL_FIBRE_100G = 9
COL_SERVINGS_UNIT = 42
COL_UNIT_ENERGY_KCAL = 44
COL_UNIT_CARB = 45
COL_UNIT_PROTEIN = 46
COL_UNIT_FAT = 47
COL_UNIT_FIBRE = 49

VALID_DIETARY_TYPES = {"Vegetarian", "Non-Vegetarian", "Vegan", "Eggetarian"}

# ---------------------------------------------------------------------------
# Heuristic keyword lists (name-based; see caveat in module docstring)
# ---------------------------------------------------------------------------

NONVEG_KEYWORDS = [
    "chicken", "mutton", "fish", "prawn", "shrimp", "crab", "meat", "beef",
    "pork", "lamb", "goat", "kheema", "keema", "liver", "bacon", "ham",
    "sausage", "seafood", "tuna", "salmon", "anchovy", "squid", "octopus",
    "turkey", "duck", "venison", "quail", "yakhni",
]
EGG_KEYWORDS = ["egg", "omelette", "omlet", "eggnog"]
EGG_EXCLUDE = ["eggplant"]

DAIRY_KEYWORDS = [
    "milk", "paneer", "cheese", "curd", "yogurt", "yoghurt", "ghee",
    "butter", "cream", "khoa", "khoya", "malai", "lassi", "kheer",
    "shrikhand", "buttermilk", "mawa", "rabri", "payasam", "custard",
    "souffle",
]
GLUTEN_KEYWORDS = [
    "wheat", "atta", "maida", "sooji", "rava", "semolina", "noodle",
    "pasta", "macaroni", "vermicelli", "sevai", "bread", "bun", "biscuit",
    "cookie", "cake", "naan", "kulcha", "poori", "puri", "roti", "chapati",
    "paratha", "parantha", "daliya", "barley", "bulgur", "sandwich",
    "toast", "pav", "chowmein",
]
PEANUT_KEYWORDS = ["peanut", "moongfali", "groundnut"]
TREENUT_KEYWORDS = [
    "cashew", "kaju", "almond", "badam", "walnut", "akhrot", "pista",
    "hazelnut", "pecan", "macadamia", "chestnut",
]
SOY_KEYWORDS = ["soy", "soya", "tofu"]
SESAME_KEYWORDS = ["sesame", "til ", "til(", "tahini", "gingelly"]
MUSTARD_KEYWORDS = ["mustard", "sarson", "rai "]

# Category rules are checked in order; first match wins.
CATEGORY_RULES = [
    ("Beverages", ["tea", "coffee", "juice", "shake", "lassi", "lemonade",
                   "cooler", "punch", "squash", "mocktail", "smoothie",
                   "sherbet", "sharbat", "thandai", "chach", "cocoa",
                   "espresso", "panna", "drink"]),
    ("Non-Veg Mains", NONVEG_KEYWORDS),
    ("Eggs", EGG_KEYWORDS),
    ("Sweets & Desserts", ["halwa", "kheer", "burfi", "ladoo", "laddu",
                            "barfi", "pudding", "souffle", "custard",
                            "jalebi", "gulab", "rasgulla", "payasam",
                            "shrikhand", "kulfi", "ice cream", "cookie",
                            "biscuit", "tart", "pastry", "chocolate", "cake"]),
    ("Snacks", ["sandwich", "cutlet", "pakora", "bhajiya", "samosa", "vada",
                "chaat", "tikki", "roll", "wrap", "bhel", "dhokla", "chips",
                "bonda", "kachori", "toast"]),
    ("Breads & Grains", ["roti", "chapati", "paratha", "parantha", "naan",
                          "kulcha", "poori", "puri", "bhakri", "dosa",
                          "idli", "uttapam", "rice", "pulao", "biryani",
                          "khichdi", "khichri", "upma", "daliya",
                          "porridge", "bread", "bun", "pav", "cheela"]),
    ("Curries & Gravies", ["curry", "sabzi", "masala", "kadhi", "dal ",
                            " dal", "sambar", "rasam", "kofta", "korma",
                            "gravy", "yakhni"]),
    ("Soups", ["soup"]),
    ("Salads", ["salad"]),
    ("Dairy", ["milk", "curd", "yogurt", "paneer", "cheese", "ghee",
               "buttermilk"]),
]


def _has_any(name_lower, keywords):
    return any(kw in name_lower for kw in keywords)


def categorize(name):
    n = name.lower()
    for category, keywords in CATEGORY_RULES:
        if _has_any(n, keywords):
            return category
    return "Other / Mixed Dishes"


def classify_dietary_type(name):
    n = name.lower()
    if _has_any(n, NONVEG_KEYWORDS):
        return "Non-Vegetarian"
    if _has_any(n, EGG_KEYWORDS) and not _has_any(n, EGG_EXCLUDE):
        return "Eggetarian"
    if _has_any(n, DAIRY_KEYWORDS):
        return "Vegetarian"
    return "Vegan"


def detect_allergens(name):
    n = name.lower()
    tags = []
    if _has_any(n, PEANUT_KEYWORDS):
        tags.append("Peanut")
    if _has_any(n, TREENUT_KEYWORDS):
        tags.append("Tree Nuts")
    if _has_any(n, DAIRY_KEYWORDS):
        tags.append("Dairy")
    if _has_any(n, GLUTEN_KEYWORDS):
        tags.append("Gluten")
    if _has_any(n, SOY_KEYWORDS):
        tags.append("Soy")
    if _has_any(n, EGG_KEYWORDS) and not _has_any(n, EGG_EXCLUDE):
        tags.append("Egg")
    if _has_any(n, SESAME_KEYWORDS):
        tags.append("Sesame")
    if _has_any(n, MUSTARD_KEYWORDS):
        tags.append("Mustard")
    return ",".join(tags)


def _first_not_none(*values):
    for v in values:
        if v is not None:
            return v
    return None


def load_foods_from_workbook(xlsx_path):
    """
    Read the INDB workbook and return a list of tuples ready to insert
    into the `foods` table, in column order:
    (name, category, serving_size, calories, protein, carbs, fat, fiber,
     dietary_type, allergens)
    """
    if not os.path.exists(xlsx_path):
        raise FileNotFoundError(
            f"INDB workbook not found at '{xlsx_path}'. Place the file "
            f"there or update the path passed to load_foods_from_workbook()."
        )

    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    ws = wb["Sheet1"]

    rows_out = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        name = (row[COL_FOOD_NAME] or "").strip()
        if not name:
            continue

        servings_unit = (row[COL_SERVINGS_UNIT] or "").strip()
        unit_kcal = row[COL_UNIT_ENERGY_KCAL]

        use_per_serving = bool(servings_unit) and unit_kcal is not None

        if use_per_serving:
            serving_size = f"1 {servings_unit}"
            calories = row[COL_UNIT_ENERGY_KCAL]
            protein = row[COL_UNIT_PROTEIN]
            carbs = row[COL_UNIT_CARB]
            fat = row[COL_UNIT_FAT]
            fiber = row[COL_UNIT_FIBRE]
        else:
            serving_size = "100 g"
            calories = row[COL_ENERGY_KCAL_100G]
            protein = row[COL_PROTEIN_100G]
            carbs = row[COL_CARB_100G]
            fat = row[COL_FAT_100G]
            fiber = row[COL_FIBRE_100G]

        # Per-100g columns had zero nulls in the source file (verified by
        # inspection), but guard anyway rather than let a bad row crash
        # the whole import.
        if calories is None or protein is None or carbs is None or fat is None:
            continue

        category = categorize(name)
        dietary_type = classify_dietary_type(name)
        allergens = detect_allergens(name)

        rows_out.append((
            name,
            category,
            serving_size,
            round(float(calories), 1),
            round(float(protein), 1),
            round(float(carbs), 1),
            round(float(fat), 1),
            round(float(fiber), 1) if fiber is not None else 0.0,
            dietary_type,
            allergens,
        ))

    return rows_out


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    default_path = os.path.join(here, "..", "data", "Anuvaad_INDB_2024_11.xlsx")
    foods = load_foods_from_workbook(default_path)

    from collections import Counter
    cat_counts = Counter(f[1] for f in foods)
    diet_counts = Counter(f[8] for f in foods)

    print(f"Parsed {len(foods)} food rows from INDB workbook.\n")
    print("By category:")
    for cat, n in cat_counts.most_common():
        print(f"  {cat:22s} {n}")
    print("\nBy dietary type:")
    for diet, n in diet_counts.most_common():
        print(f"  {diet:16s} {n}")
    print("\nSample rows:")
    for row in foods[:5]:
        print(" ", row)
