"""Create a fresh normalized NutriTrack database and load reference data.

The command refuses every existing destination. It is intentionally separate
from application startup and never upgrades or resets a database in place.
"""
import argparse
import os
import sqlite3
from pathlib import Path
import sys
import openpyxl

# When invoked as ``python scripts/init_db.py``, Python puts ``scripts/`` on
# sys.path rather than the project root. Add the root so package imports work
# for both direct-file and ``python -m`` execution.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.import_indb import load_foods_from_workbook
from scripts.reference_data import ALLERGIES, RECIPES

MIGRATIONS_DIR = ROOT / "migrations"


def apply_migrations(connection: sqlite3.Connection) -> None:
    """Apply ordered migrations transactionally, once per database."""
    connection.execute(
        """CREATE TABLE IF NOT EXISTS schema_migrations (
               version TEXT PRIMARY KEY,
               applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
           )"""
    )
    for migration in sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9]_*.sql")):
        version = migration.name
        if connection.execute(
            "SELECT 1 FROM schema_migrations WHERE version = ?", (version,)
        ).fetchone():
            continue
        connection.execute("BEGIN IMMEDIATE")
        try:
            pending = []
            for line in migration.read_text(encoding="utf-8-sig").splitlines():
                pending.append(line)
                statement = "\n".join(pending)
                if sqlite3.complete_statement(statement):
                    if statement.strip():
                        connection.execute(statement)
                    pending = []
            if any(line.strip() and not line.lstrip().startswith("--") for line in pending):
                raise sqlite3.OperationalError(f"Incomplete SQL in {migration.name}")
            connection.execute(
                "INSERT INTO schema_migrations(version) VALUES (?)", (version,)
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise


def initialize(path: Path, workbook: Path) -> None:
    path = path.expanduser().resolve()
    if path.exists():
        raise FileExistsError(f"Refusing to initialize existing path: {path}")
    if not workbook.is_file():
        raise FileNotFoundError(f"INDB workbook not found: {workbook}")
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = load_foods_from_workbook(str(workbook))
    source_rows = {}
    book = openpyxl.load_workbook(workbook, read_only=True, data_only=True)
    try:
        for source_row in book["Sheet1"].iter_rows(min_row=2, values_only=True):
            food_name = (source_row[1] or "").strip()
            if food_name:
                source_rows[food_name] = source_row
    finally:
        book.close()
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        schema = (ROOT / "schema.sql").read_text(encoding="utf-8-sig")
        connection.executescript(f"BEGIN IMMEDIATE;\n{schema}\nCOMMIT;")
        apply_migrations(connection)
        with connection:
            connection.executemany("INSERT INTO allergens(name) VALUES (?)", [(x,) for x in ALLERGIES])
            source_id = connection.execute(
                "INSERT INTO food_sources(name,version,url,description) VALUES(?,?,?,?)",
                ("INDB", "2024_11", "https://www.anuvaad.org.in/indian-nutrient-databank/", "Indian Nutrient Databank export"),
            ).lastrowid
            for (name, category, serving, calories, protein, carbs, fat, fiber, diet, allergen_names) in rows:
                # INDB's per-serving figures are converted to an approximate
                # serving mass using the per-100g energy ratio, as in the
                # project's existing populated normalized catalogue.
                source_row = source_rows[name]
                serving_amount = 100.0
                per100 = (source_row[4], source_row[6], source_row[5], source_row[7], source_row[9])
                if serving != "100 g":
                    per_serving = (source_row[44], source_row[46], source_row[45], source_row[47], source_row[49])
                    if per100[0] and per_serving[0]:
                        serving_amount = float(per_serving[0]) / float(per100[0]) * 100
                if any(value is None for value in per100[:4]):
                    # The importer already filters these, but retain a safe
                    # fallback if the workbook changes between the two reads.
                    per100 = (calories, protein, carbs, fat, fiber)
                food_id = connection.execute(
                    "INSERT INTO foods(name,source_id,source_food_id,food_type,dietary_type) VALUES(?,?,?,?,?)",
                    (name, source_id, str(source_row[0]) if source_row[0] is not None else None, "Prepared Dish", diet),
                ).lastrowid
                connection.execute("INSERT OR IGNORE INTO categories(name) VALUES(?)", (category,))
                category_id = connection.execute("SELECT id FROM categories WHERE name=?", (category,)).fetchone()[0]
                connection.execute("INSERT INTO food_categories(food_id,category_id) VALUES(?,?)", (food_id, category_id))
                connection.execute(
                    "INSERT INTO food_nutrition(food_id,per_amount,per_unit,calories,protein_g,carbohydrates_g,fat_g,fiber_g) VALUES(?,100,'g',?,?,?,?,?)",
                    (food_id, *[float(value or 0) for value in per100]),
                )
                connection.execute(
                    "INSERT INTO food_servings(food_id,serving_name,serving_quantity,is_default) VALUES(?,?,?,1)",
                    (food_id, serving, max(serving_amount, 0.01)),
                )
                for allergen in filter(None, allergen_names.split(",")):
                    allergen_id = connection.execute("SELECT id FROM allergens WHERE name=?", (allergen,)).fetchone()
                    if allergen_id:
                        connection.execute("INSERT OR IGNORE INTO food_allergens(food_id,allergen_id) VALUES(?,?)", (food_id, allergen_id[0]))
            for recipe in RECIPES:
                name, description, ingredients, instructions, meal_type, diet, _allergens, *_nutrition = recipe
                recipe_id = connection.execute(
                    "INSERT INTO recipes(name,description,instructions,meal_type,dietary_type) VALUES(?,?,?,?,?)",
                    (name, description + "\nIngredients: " + ingredients, instructions, meal_type, diet),
                ).lastrowid
                for allergen in filter(None, _allergens.split(",")):
                    allergen_id = connection.execute("SELECT id FROM allergens WHERE name=?", (allergen,)).fetchone()
                    if allergen_id:
                        connection.execute("INSERT INTO recipe_allergens(recipe_id,allergen_id) VALUES(?,?)", (recipe_id, allergen_id[0]))
        connection.execute("PRAGMA optimize")
    finally:
        connection.close()
    print(f"Initialized {path} with {len(rows)} INDB foods and {len(RECIPES)} recipes.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=os.environ.get("DATABASE_PATH", str(ROOT / "nutritrack_v2.db")), help="New database destination (must not exist)")
    parser.add_argument("--workbook", default=str(ROOT / "data" / "Anuvaad_INDB_2024_11.xlsx"))
    args = parser.parse_args()
    initialize(Path(args.db), Path(args.workbook))


if __name__ == "__main__":
    main()
