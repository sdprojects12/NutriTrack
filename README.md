# NutriTrack

An Indian-food nutrition tracking web app. College mini-project built with
Python, Flask, SQLite, Jinja2 and vanilla HTML/CSS/JS.

## Tech stack

- Python 3 + Flask
- SQLite (via Python's built-in `sqlite3` module)
- Jinja2 templates
- Werkzeug password hashing + Flask sessions for auth
- Plain HTML/CSS/JS (no React/Node)

## Project status: Complete

All four development stages have been implemented:

- [x] **Stage 1** — Project setup, SQLite schema, seed food data, Flask app, authentication
- [x] **Stage 2** — User profiles (age, height, weight, dietary preference, goal, allergies) + dashboard
- [x] **Stage 3** — Meal logging with live food search, quantity management and nutrition calculation
- [x] **Stage 4** — Meal suggestions (diet- and allergy-aware filtering) + UI/UX polish

## Implemented features

- **Authentication** — sign up, log in, log out (passwords hashed with Werkzeug, never stored in plaintext)
- **Profile management** — age, height, weight, dietary preference (Vegetarian / Non-Vegetarian / Vegan / Eggetarian), nutrition goal, allergy selection with "No Known Allergies" sentinel
- **Forced profile completion** — new users must complete their profile before accessing the app
- **Dashboard** — daily nutrition totals, per-meal nutrition breakdown (calories, protein, carbs, fat), meal status cards with direct links to view or log meals
- **Meal logging** — live food search against 1,014 INDB foods, multi-item meal builder with per-serving quantity control, real-time nutrition summary
- **Meal detail & deletion** — itemised food breakdown with calculated nutrition per item and meal totals
- **Meal suggestions** — recipe recommendations filtered by dietary preference (diet compatibility hierarchy) and allergy exclusions, with per-meal-type filter pills

## Setup

```bash
cd NutriTrack
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

export FLASK_APP=app.py         # Windows (PowerShell): $env:FLASK_APP="app.py"
flask init-db                   # creates nutritrack.db from schema.sql
flask seed-db                   # populates foods / allergies / recipes

flask run
```

Then open **http://127.0.0.1:5000** in your browser.

## Nutrition data source: INDB

`foods` is seeded from the **Indian Nutrient Databank (INDB)** export:
`data/Anuvaad_INDB_2024_11.xlsx`
(https://www.anuvaad.org.in/indian-nutrient-databank/). All 1,014 rows
were imported.

**Import script:** `scripts/import_indb.py` — read its module docstring
for the full column mapping. Short version:

| Our column       | INDB source column(s)                                                                         |
| ---------------- | --------------------------------------------------------------------------------------------- |
| `name`           | `food_name`                                                                                   |
| `serving_size`   | `servings_unit` (as "1 &lt;unit&gt;"), or `"100 g"` when INDB gives no serving unit           |
| `calories`       | `unit_serving_energy_kcal` if available, else `energy_kcal` (per 100 g)                       |
| `protein`        | `unit_serving_protein_g` if available, else `protein_g`                                       |
| `carbs`          | `unit_serving_carb_g` if available, else `carb_g`                                             |
| `fat`            | `unit_serving_fat_g` if available, else `fat_g`                                               |
| `fiber`          | `unit_serving_fibre_g` if available, else `fibre_g`                                           |

Per-serving values are preferred whenever INDB provides them, since users
log meals by serving, not by 100 g.

**`category`, `dietary_type` and `allergens` are NOT in the INDB file** —
INDB is a pure nutrition table with no tagging columns. These fields are
derived by keyword-matching each food's name (e.g. "chicken" →
Non-Vegetarian; "paneer" → Dairy allergen). This is a name-only heuristic,
not verified ingredient data — see `scripts/import_indb.py` for full
documentation of its limitations.

### Known data quality issue in the source file

Roughly **128 of 1,014 rows** (~13%) have implausible fat/carb figures
relative to what the dish actually is — e.g. INDB lists Poori at 77.6 g
fat / 8.2 g carb per 100 g, when real-world figures are closer to ~15-18 g
fat and ~40 g carb. The calorie figure is internally consistent with the
reported macros, suggesting the error is in INDB's own computation for
that subset. These rows were imported as-is rather than silently corrected.

## Project structure

```
NutriTrack/
├── app.py                       # Flask app, all routes, auth
├── schema.sql                   # SQLite schema (8 tables)
├── seed_data.py                 # Seeds allergies, foods (INDB) and recipes
├── requirements.txt             # Flask, Werkzeug, openpyxl
├── scripts/
│   └── import_indb.py           # INDB → foods table mapping + heuristics
├── data/
│   └── Anuvaad_INDB_2024_11.xlsx
├── templates/
│   ├── base.html                # Shared layout, navbar, flash messages
│   ├── login.html               # Login form
│   ├── signup.html              # Registration form
│   ├── dashboard.html           # Daily summary + per-meal nutrition cards
│   ├── profile.html             # Profile setup and editing
│   ├── add_meal.html            # Meal builder with food search
│   ├── meal_detail.html         # Itemised meal view + delete
│   └── suggestions.html         # Diet- and allergy-filtered recipes
├── static/
│   └── css/
│       └── style.css            # Design system (green/teal, Inter + Poppins)
└── nutritrack.db                # SQLite database (created by init-db/seed-db)
```

## Future scope (not implemented)

- Gemini / AI-powered meal recommendations
- Natural-language meal logging ("I had 2 idlis and a chai")
- AI-generated diet plans
- Food image recognition
- Google OAuth login
- Barcode scanning for packaged foods
- Advanced analytics / trends over time
- Calorie and macro targets based on profile goals
