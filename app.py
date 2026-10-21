import os
import copy
import sqlite3
import time
from datetime import date
from functools import wraps
from authlib.integrations.flask_client import OAuth
from dotenv import load_dotenv
import requests
from flask import (
    Flask, g, render_template, request, redirect, url_for, session, flash, jsonify
)
from werkzeug.security import generate_password_hash, check_password_hash

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE = os.path.join(BASE_DIR, "nutritrack_v2.db")

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("FLASK_SECRET_KEY", "local-development-key-change-before-deployment")
app.config["DATABASE"] = DATABASE
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0

oauth = OAuth(app)
if os.environ.get("GOOGLE_CLIENT_ID") and os.environ.get("GOOGLE_CLIENT_SECRET"):
    oauth.register(
        name="google",
        client_id=os.environ["GOOGLE_CLIENT_ID"],
        client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )


@app.after_request
def disable_personal_page_caching(response):
    # Logged-in pages and search results contain profile and health data.
    if request.endpoint != "static":
        response.headers["Cache-Control"] = "no-store, private"
    return response

# Stage 2 constants — kept in one place so the profile form and its
# server-side validation can never drift apart.
DIETARY_PREFERENCES = ["Vegetarian", "Non-Vegetarian", "Vegan", "Eggetarian"]
GENERAL_GOALS = [
    "Lose Weight",
    "Maintain Weight",
    "Gain Weight",
    "Build Muscle",
    "General Health",
]
MEAL_TYPES = ["Breakfast", "Lunch", "Snack", "Dinner"]

# Short in-process cache for repeated USDA searches; user-specific filtering is
# applied after retrieving these shared source records.
USDA_SEARCH_CACHE_SECONDS = 120
_usda_search_cache = {}

# Sentinel allergy row a user selects to explicitly confirm "I have no
# allergies." This lets us tell "confirmed no allergies" apart from
# "hasn't answered yet" (zero rows in user_allergies) without adding a
# new column or table — see is_profile_complete() below.
NO_ALLERGY_LABEL = "No Known Allergies"

# Diet compatibility: which recipe dietary_types a user on a given
# preference can eat, from strictest (Vegan) to least strict
# (Non-Vegetarian). A stricter recipe always suits a less strict eater.
DIET_COMPATIBILITY = {
    "Vegan": ["Vegan"],
    "Vegetarian": ["Vegan", "Vegetarian"],
    "Eggetarian": ["Vegan", "Vegetarian", "Eggetarian"],
    "Non-Vegetarian": ["Vegan", "Vegetarian", "Eggetarian", "Non-Vegetarian"],
}

# Endpoints reachable by a logged-in user even with an incomplete profile.
PROFILE_SETUP_EXEMPT_ENDPOINTS = {"profile", "logout", "google_callback", "static", None}


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


# The old init-db and seed-db commands intentionally are not registered here.
# schema_v2.sql contains DROP TABLE statements and must NEVER be run against
# the populated migrated database as part of normal application startup.


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if session.get("user_id") is None:
            flash("Please log in to continue.", "error")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped_view


@app.before_request
def load_logged_in_user():
    user_id = session.get("user_id")
    if user_id is None:
        g.user = None
    else:
        g.user = get_db().execute(
            "SELECT * FROM users WHERE id = ?", (user_id,)
        ).fetchone()


def is_profile_complete(db, user_id):
    """True once age, height, weight, dietary preference and nutrition
    goal are all filled in AND the user has made an explicit allergy
    choice (a real allergy, or the 'No Known Allergies' sentinel)."""
    row = db.execute(
        """SELECT age, height_cm, weight_kg, dietary_preference, general_goal
           FROM profiles WHERE user_id = ?""",
        (user_id,),
    ).fetchone()
    if row is None:
        return False
    if row["age"] is None or row["height_cm"] is None or row["weight_kg"] is None:
        return False
    if not row["dietary_preference"] or not row["general_goal"]:
        return False
    has_allergy_choice = db.execute(
        "SELECT 1 FROM user_allergies WHERE user_id = ? LIMIT 1", (user_id,)
    ).fetchone()
    return has_allergy_choice is not None


def google_client():
    client = oauth.create_client("google")
    if client is None:
        flash("Google sign-in is not configured yet. Add the Google OAuth settings to your .env file.", "error")
    return client


def google_identity_table_exists(db):
    return db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='user_identities'"
    ).fetchone() is not None


@app.before_request
def require_complete_profile():
    # Runs after load_logged_in_user (registered above it), so g.user is
    # already set. Bounces any logged-in user with an incomplete profile
    # to the profile page, from any route except the exempt few.
    if g.get("user") is None:
        return
    if request.endpoint in PROFILE_SETUP_EXEMPT_ENDPOINTS:
        return
    if not is_profile_complete(get_db(), g.user["id"]):
        flash("Please complete your profile to continue.", "error")
        return redirect(url_for("profile"))


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    if g.user:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/signup", methods=("GET", "POST"))
def signup():
    if g.user:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")

        error = None
        if not name:
            error = "Name is required."
        elif not email:
            error = "Email is required."
        elif not password or len(password) < 6:
            error = "Password must be at least 6 characters long."
        elif password != confirm:
            error = "Passwords do not match."

        db = get_db()
        if error is None:
            existing = db.execute(
                "SELECT id FROM users WHERE email = ?", (email,)
            ).fetchone()
            if existing is not None:
                error = f"An account with email '{email}' already exists."

        if error is None:
            db.execute(
                "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
                (name, email, generate_password_hash(password)),
            )
            db.commit()
            user = db.execute(
                "SELECT id FROM users WHERE email = ?", (email,)
            ).fetchone()
            # Create an empty profile row so later edits are simple UPDATEs.
            db.execute(
                "INSERT INTO profiles (user_id, dietary_preference) VALUES (?, ?)",
                (user["id"], "Vegetarian"),
            )
            db.commit()
            flash("Account created successfully. Please log in.", "success")
            return redirect(url_for("login"))

        flash(error, "error")

    return render_template("signup.html")


@app.route("/login", methods=("GET", "POST"))
def login():
    if g.user:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        db = get_db()
        error = None
        user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()

        if user is None or not check_password_hash(user["password_hash"], password):
            error = "Incorrect email or password."

        if error is None:
            session.clear()
            session["user_id"] = user["id"]
            if is_profile_complete(db, user["id"]):
                flash(f"Welcome back, {user['name']}!", "success")
                return redirect(url_for("dashboard"))
            flash(f"Welcome, {user['name']}! Let's finish setting up your profile.", "success")
            return redirect(url_for("profile"))

        flash(error, "error")

    return render_template("login.html")


@app.route("/auth/google")
def google_login():
    client = google_client()
    if client is None:
        return redirect(url_for("login"))
    if not google_identity_table_exists(get_db()):
        flash("Google sign-in needs the included database migration applied first.", "error")
        return redirect(url_for("login"))
    session.pop("google_link_user_id", None)
    return client.authorize_redirect(url_for("google_callback", _external=True))


@app.route("/auth/google/link")
@login_required
def google_link():
    client = google_client()
    if client is None:
        return redirect(url_for("profile"))
    if not google_identity_table_exists(get_db()):
        flash("Google sign-in needs the included database migration applied first.", "error")
        return redirect(url_for("profile"))
    session["google_link_user_id"] = g.user["id"]
    return client.authorize_redirect(url_for("google_callback", _external=True))


@app.route("/auth/google/callback")
def google_callback():
    client = google_client()
    if client is None:
        return redirect(url_for("login"))
    db = get_db()
    if not google_identity_table_exists(db):
        flash("Google sign-in needs the included database migration applied first.", "error")
        return redirect(url_for("login"))

    try:
        token = client.authorize_access_token()
        claims = token.get("userinfo") or {}
    except Exception:
        app.logger.exception("Google sign-in callback failed")
        flash("Google sign-in could not be completed. Please try again.", "error")
        return redirect(url_for("login"))

    subject = claims.get("sub")
    email = (claims.get("email") or "").strip().lower()
    name = (claims.get("name") or "").strip() or email.partition("@")[0]
    if not subject or not email or claims.get("email_verified") is not True:
        flash("Google did not provide a verified email address. Please try another account.", "error")
        return redirect(url_for("login"))

    linked_user_id = session.pop("google_link_user_id", None)
    identity = db.execute(
        "SELECT user_id FROM user_identities WHERE provider = 'google' AND provider_subject = ?",
        (subject,),
    ).fetchone()
    if linked_user_id is not None:
        if g.user is None or g.user["id"] != linked_user_id:
            flash("Your session changed during Google linking. Sign in and try again.", "error")
            return redirect(url_for("login"))
        if identity and identity["user_id"] != linked_user_id:
            flash("That Google account is already linked to another NutriTrack account.", "error")
            return redirect(url_for("profile"))
        db.execute(
            "INSERT OR IGNORE INTO user_identities (user_id, provider, provider_subject) VALUES (?, 'google', ?)",
            (linked_user_id, subject),
        )
        db.commit()
        flash("Google sign-in linked to your account.", "success")
        return redirect(url_for("profile"))

    if identity:
        user = db.execute("SELECT id, name FROM users WHERE id = ?", (identity["user_id"],)).fetchone()
        if user is None:
            flash("This Google sign-in is not connected to an active account.", "error")
            return redirect(url_for("login"))
    else:
        existing_user = db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        if existing_user:
            flash("An account already uses this email. Log in with your password, then link Google from your profile.", "error")
            return redirect(url_for("login"))
        # Existing schema requires a password hash. This random value is
        # discarded and cannot be used as a password by the user.
        cursor = db.execute(
            "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
            (name, email, generate_password_hash(os.urandom(32).hex())),
        )
        user_id = cursor.lastrowid
        db.execute("INSERT INTO profiles (user_id, dietary_preference) VALUES (?, ?)", (user_id, "Vegetarian"))
        db.execute(
            "INSERT INTO user_identities (user_id, provider, provider_subject) VALUES (?, 'google', ?)",
            (user_id, subject),
        )
        db.commit()
        user = db.execute("SELECT id, name FROM users WHERE id = ?", (user_id,)).fetchone()

    session.clear()
    session["user_id"] = user["id"]
    if is_profile_complete(db, user["id"]):
        flash(f"Welcome back, {user['name']}!", "success")
        return redirect(url_for("dashboard"))
    flash(f"Welcome, {user['name']}! Let's finish setting up your profile.", "success")
    return redirect(url_for("profile"))


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("login"))


@app.route("/profile", methods=("GET", "POST"))
@login_required
def profile():
    db = get_db()
    user_id = g.user["id"]

    # Was the profile already complete before this request? Decides
    # where a successful save sends the user (dashboard the first time,
    # back to the profile page on later edits) and which heading/button
    # copy the page shows.
    was_complete = is_profile_complete(db, user_id)

    user_profile = db.execute(
        "SELECT * FROM profiles WHERE user_id = ?", (user_id,)
    ).fetchone()
    all_allergies = db.execute(
        "SELECT id, name FROM allergens ORDER BY name"
    ).fetchall()
    selected_allergy_ids = {
        row["allergy_id"]
        for row in db.execute(
            "SELECT allergen_id AS allergy_id FROM user_allergies WHERE user_id = ?", (user_id,)
        ).fetchall()
    }
    no_allergy_row = db.execute(
        "SELECT id FROM allergens WHERE name = ?", (NO_ALLERGY_LABEL,)
    ).fetchone()
    no_allergy_id = no_allergy_row["id"] if no_allergy_row else None

    if request.method == "POST":
        age_raw = request.form.get("age", "").strip()
        height_raw = request.form.get("height_cm", "").strip()
        weight_raw = request.form.get("weight_kg", "").strip()
        dietary_preference = request.form.get("dietary_preference", "")
        general_goal = request.form.get("general_goal", "").strip()
        submitted_allergy_ids = request.form.getlist("allergies")

        # If "No Known Allergies" was checked alongside real allergies
        # (e.g. JS disabled), the sentinel wins and the rest are dropped.
        if no_allergy_id is not None and str(no_allergy_id) in submitted_allergy_ids:
            submitted_allergy_ids = [str(no_allergy_id)]

        error = None
        age_val = height_val = weight_val = None

        if not age_raw:
            error = "Age is required."
        else:
            try:
                age_val = int(age_raw)
                if not (1 <= age_val <= 120):
                    error = "Age must be between 1 and 120."
            except ValueError:
                error = "Age must be a whole number."

        if error is None and not height_raw:
            error = "Height is required."
        elif error is None:
            try:
                height_val = float(height_raw)
                if not (50 <= height_val <= 250):
                    error = "Height must be between 50 and 250 cm."
            except ValueError:
                error = "Height must be a number."

        if error is None and not weight_raw:
            error = "Weight is required."
        elif error is None:
            try:
                weight_val = float(weight_raw)
                if not (20 <= weight_val <= 300):
                    error = "Weight must be between 20 and 300 kg."
            except ValueError:
                error = "Weight must be a number."

        if error is None and dietary_preference not in DIETARY_PREFERENCES:
            error = "Please choose a dietary preference."

        if error is None and general_goal not in GENERAL_GOALS:
            error = "Please choose a nutrition goal."

        if error is None and not submitted_allergy_ids:
            error = 'Please select your allergies, or choose "No Known Allergies".'

        if error is None:
            db.execute(
                """UPDATE profiles
                   SET age = ?, height_cm = ?, weight_kg = ?,
                       dietary_preference = ?, general_goal = ?,
                       updated_at = CURRENT_TIMESTAMP
                   WHERE user_id = ?""",
                (age_val, height_val, weight_val, dietary_preference,
                 general_goal, user_id),
            )
            db.execute("DELETE FROM user_allergies WHERE user_id = ?", (user_id,))
            for allergy_id in submitted_allergy_ids:
                db.execute(
                    "INSERT INTO user_allergies (user_id, allergen_id) VALUES (?, ?)",
                    (user_id, allergy_id),
                )
            db.commit()

            if not was_complete:
                flash("Profile completed! Welcome to NutriTrack.", "success")
                return redirect(url_for("dashboard"))
            flash("Profile updated successfully.", "success")
            return redirect(url_for("profile"))

        flash(error, "error")
        # Re-display exactly what the user submitted rather than the
        # stale DB values, so a validation error doesn't wipe their input.
        user_profile = {
            "age": age_raw,
            "height_cm": height_raw,
            "weight_kg": weight_raw,
            "dietary_preference": dietary_preference,
            "general_goal": general_goal,
        }
        selected_allergy_ids = {int(i) for i in submitted_allergy_ids}

    return render_template(
        "profile.html",
        profile=user_profile,
        all_allergies=all_allergies,
        selected_allergy_ids=selected_allergy_ids,
        dietary_preferences=DIETARY_PREFERENCES,
        general_goals=GENERAL_GOALS,
        no_allergy_label=NO_ALLERGY_LABEL,
        onboarding=not was_complete,
    )


@app.route("/dashboard")
@login_required
def dashboard():
    db = get_db()
    user_id = g.user["id"]
    today = date.today()

    totals = db.execute(
        """SELECT
              COALESCE(SUM(mi.calories_at_logging * mi.quantity), 0) AS calories,
              COALESCE(SUM(mi.protein_at_logging * mi.quantity), 0)  AS protein,
              COALESCE(SUM(mi.carbs_at_logging * mi.quantity), 0)    AS carbs,
              COALESCE(SUM(mi.fat_at_logging * mi.quantity), 0)      AS fat
            FROM meals m
            LEFT JOIN meal_items mi ON mi.meal_id = m.id
            WHERE m.user_id = ? AND m.logged_date = ?""",
        (user_id, today.isoformat()),
    ).fetchone()
    usda_totals = db.execute(
        """SELECT COALESCE(SUM(ui.calories_at_logging * ui.quantity), 0) calories,
                  COALESCE(SUM(ui.protein_at_logging * ui.quantity), 0) protein,
                  COALESCE(SUM(ui.carbs_at_logging * ui.quantity), 0) carbs,
                  COALESCE(SUM(ui.fat_at_logging * ui.quantity), 0) fat
           FROM meals m JOIN usda_meal_items ui ON ui.meal_id = m.id
           WHERE m.user_id = ? AND m.logged_date = ?""",
        (user_id, today.isoformat()),
    ).fetchone()
    totals = dict(totals)
    for key in ("calories", "protein", "carbs", "fat"):
        totals[key] += usda_totals[key]

    # Most recent meal id per type logged today, so the dashboard can link
    # straight to "View meal" for a type that's already logged. If a user
    # logs the same type twice in one day (not prevented by the schema),
    # the newest one is what gets linked.
    todays_meal_rows = db.execute(
        """SELECT id, meal_type FROM meals
           WHERE user_id = ? AND logged_date = ?
           ORDER BY created_at DESC""",
        (user_id, today.isoformat()),
    ).fetchall()
    logged_meals = {}
    for row in todays_meal_rows:
        logged_meals.setdefault(row["meal_type"], row["id"])

    # Per-meal-type nutrition totals for today's dashboard cards
    meal_nutrition_rows = db.execute(
        """SELECT m.meal_type,
             COALESCE(SUM(mi.calories_at_logging * mi.quantity), 0) AS calories,
             COALESCE(SUM(mi.protein_at_logging * mi.quantity), 0)  AS protein,
             COALESCE(SUM(mi.carbs_at_logging * mi.quantity), 0)    AS carbs,
             COALESCE(SUM(mi.fat_at_logging * mi.quantity), 0)      AS fat
            FROM meals m
            JOIN meal_items mi ON mi.meal_id = m.id
            WHERE m.user_id = ? AND m.logged_date = ?
            GROUP BY m.meal_type""",
        (user_id, today.isoformat()),
    ).fetchall()
    meal_nutrition = {row["meal_type"]: dict(row) for row in meal_nutrition_rows}
    usda_meal_nutrition = db.execute(
        """SELECT m.meal_type,
                  SUM(ui.calories_at_logging * ui.quantity) calories,
                  SUM(ui.protein_at_logging * ui.quantity) protein,
                  SUM(ui.carbs_at_logging * ui.quantity) carbs,
                  SUM(ui.fat_at_logging * ui.quantity) fat
           FROM meals m JOIN usda_meal_items ui ON ui.meal_id = m.id
           WHERE m.user_id = ? AND m.logged_date = ? GROUP BY m.meal_type""",
        (user_id, today.isoformat()),
    ).fetchall()
    for row in usda_meal_nutrition:
        bucket = meal_nutrition.setdefault(row["meal_type"], {
            "calories": 0, "protein": 0, "carbs": 0, "fat": 0
        })
        for key in ("calories", "protein", "carbs", "fat"):
            bucket[key] += row[key] or 0

    return render_template(
        "dashboard.html",
        user=g.user,
        today=today,
        totals=totals,
        meal_types=MEAL_TYPES,
        logged_meal_types=set(logged_meals.keys()),
        logged_meals=logged_meals,
        meal_nutrition=meal_nutrition,
    )

def search_usda_foods(query, limit=8):
    """Search USDA FoodData Central without modifying the local database.

    Search-result nutrient values are shown as USDA-provided values per 100 g.
    USDA records are deliberately not assigned a local ``id``.
    """
    api_key = os.getenv("USDA_API_KEY")
    if not api_key:
        app.logger.warning("USDA search skipped because USDA_API_KEY is not configured")
        return []

    cache_key = (query.casefold(), limit)
    now = time.monotonic()
    cached = _usda_search_cache.get(cache_key)
    if cached and cached[0] > now:
        return copy.deepcopy(cached[1])
    url = "https://api.nal.usda.gov/fdc/v1/foods/search"
    try:
        response = requests.get(
            url,
            params={"api_key": api_key, "query": query, "pageSize": limit,
                    "dataType": ["Foundation", "SR Legacy", "Survey (FNDDS)"]},
            timeout=6,
        )
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError):
        app.logger.exception("USDA food search failed")
        return []

    # USDA nutrient IDs are more stable than display names across data types.
    nutrient_ids = {1008: "calories", 2047: "calories", 2048: "calories",
                    1003: "protein", 1005: "carbs", 1004: "fat", 1079: "fiber"}
    results = []
    for food in data.get("foods", []):
        nutrients = {}
        for item in food.get("foodNutrients", []):
            nutrient_id = item.get("nutrientId")
            name = nutrient_ids.get(nutrient_id)
            amount = item.get("value", item.get("amount"))
            if name and amount is not None and name not in nutrients:
                nutrients[name] = amount
        portions = []
        for measure in food.get("foodMeasures", []) or []:
            grams = measure.get("gramWeight")
            label = measure.get("disseminationText")
            if grams and grams > 0 and label:
                portions.append({"label": label, "grams": grams})
        results.append({
            "source": "USDA",
            "fdc_id": food.get("fdcId"),
            "name": food.get("description", ""),
            "data_type": food.get("dataType", ""),
            "serving_size": "per 100 g (USDA data)",
            "calories": nutrients.get("calories", 0),
            "protein": nutrients.get("protein", 0),
            "carbs": nutrients.get("carbs", 0),
            "fat": nutrients.get("fat", 0),
            "fiber": nutrients.get("fiber", 0),
            "portions": portions,
            "ingredients": food.get("ingredients"),
            "allergens": food.get("allergens"),
        })
    _usda_search_cache[cache_key] = (now + USDA_SEARCH_CACHE_SECONDS, results)
    # Keep the cache bounded even during long-running development sessions.
    if len(_usda_search_cache) > 128:
        for key, value in list(_usda_search_cache.items()):
            if value[0] <= now:
                _usda_search_cache.pop(key, None)
    return copy.deepcopy(results)

def usda_food_matches_diet(food_name, dietary_preference):
    """Conservatively filter USDA descriptions by the user's saved diet.

    USDA descriptions are not complete ingredient lists, so this only removes
    obvious conflicts. It cannot certify that a food is suitable for a diet.
    """
    import re

    name = (food_name or "").lower()

    # Word-boundary matching avoids treating words such as "eggplant" as egg.
    meat_or_seafood = re.compile(
        r"\b(chicken|turkey|duck|goose|beef|pork|bacon|ham|sausage|"
        r"lamb|mutton|goat meat|venison|rabbit|quail|meat|fish|salmon|"
        r"tuna|anchovy|sardine|trout|cod|haddock|tilapia|prawn|shrimp|"
        r"crab|lobster|crayfish|clam|mussel|oyster|scallop|squid|octopus|"
        r"anchovy|gelatin|lard|tallow|suet)\b"
    )
    eggs = re.compile(
        r"\b(egg|eggs|egg white|egg yolk|omelet|omelette|mayonnaise|mayo)\b"
    )
    dairy = re.compile(
        r"\b(milk|cheese|butter|ghee|cream|yogurt|yoghurt|curd|paneer|"
        r"whey|casein|lactose|buttermilk|kefir|khoa|khoya|malai|custard)\b"
    )
    animal_derived = re.compile(
        r"\b(honey|beeswax|royal jelly)\b"
    )

    if dietary_preference == "Non-Vegetarian":
        return True

    if meat_or_seafood.search(name):
        return False

    # The app's local compatibility rules treat Vegetarian as egg-free,
    # while Eggetarian permits egg but excludes meat and seafood.
    if dietary_preference == "Vegetarian" and eggs.search(name):
        return False

    if dietary_preference == "Vegan":
        if eggs.search(name) or dairy.search(name) or animal_derived.search(name):
            return False

    return True


def get_usda_food_nutrition(fdc_id):
    """Fetch key nutrition values for one USDA food record."""
    api_key = os.getenv("USDA_API_KEY")

    if not api_key:
        return None

    try:
        response = requests.get(
            f"https://api.nal.usda.gov/fdc/v1/food/{fdc_id}",
            params={"api_key": api_key},
            timeout=10,
        )
        response.raise_for_status()
        food = response.json()

    except (requests.RequestException, ValueError):
        app.logger.exception(
            "USDA nutrition lookup failed for FDC ID %s",
            fdc_id,
        )
        return None

    nutrient_numbers = {"208": "calories", "957": "calories",
                        "203": "protein", "205": "carbs", "204": "fat",
                        "291": "fiber"}
    nutrients = {}
    for item in food.get("foodNutrients", []):
        nutrient = item.get("nutrient", {})
        name = nutrient_numbers.get(str(nutrient.get("number", "")))
        amount = item.get("amount")
        if name and amount is not None:
            nutrients.setdefault(name, amount)

    portions = []
    for portion in food.get("foodPortions", []) or []:
        grams = portion.get("gramWeight")
        label = portion.get("portionDescription") or portion.get("modifier")
        if grams and grams > 0 and label:
            portions.append({"label": label, "grams": grams})
    return {
        "fdc_id": food.get("fdcId"),
        "name": food.get("description", ""),
        "data_type": food.get("dataType", ""),
        "calories": nutrients.get("calories"),
        "protein": nutrients.get("protein"),
        "carbs": nutrients.get("carbs"),
        "fat": nutrients.get("fat"),
        "fiber": nutrients.get("fiber", 0),
        "portions": portions,
        "ingredients": food.get("ingredients"),
        "allergens": food.get("allergens"),
    }


def usda_allergens_clear(food, user_allergies):
    """Fail closed when an external record cannot be checked for allergies."""
    if not user_allergies:
        return True
    declaration = food.get("allergens")
    if not declaration:
        return False
    text = str(declaration).casefold()
    aliases = {
        "peanut": ("peanut",),
        "tree nuts": ("tree nut", "almond", "walnut", "cashew", "pecan", "pistachio", "hazelnut"),
        "dairy": ("milk", "dairy", "whey", "casein", "lactose"),
        "gluten": ("gluten", "wheat", "barley", "rye"),
        "soy": ("soy", "soya"),
        "egg": ("egg",),
        "sesame": ("sesame",),
        "mustard": ("mustard",),
    }
    return not any(alias in text for allergy in user_allergies
                   for alias in aliases.get(allergy.casefold(), (allergy.casefold(),)))

@app.route("/api/foods/search")
@login_required
def api_food_search():
    query = request.args.get("q", "").strip()
    if len(query) < 2:
        return jsonify([])

    db = get_db()
    user_id = g.user["id"]

    # Read the user's saved dietary preference.
    profile = db.execute(
        """SELECT dietary_preference
           FROM profiles
           WHERE user_id = ?""",
        (user_id,),
    ).fetchone()

    dietary_preference = (
        profile["dietary_preference"] if profile else "Vegetarian"
    )
    user_allergies = [row["name"] for row in db.execute(
        """SELECT a.name FROM user_allergies ua JOIN allergens a ON a.id=ua.allergen_id
           WHERE ua.user_id=? AND a.name != ?""",
        (user_id, NO_ALLERGY_LABEL),
    ).fetchall()]

    if request.args.get("source") == "usda":
        usda_results = search_usda_foods(query, limit=6)
        usda_results = [
            food for food in usda_results
            if usda_food_matches_diet(food.get("name", ""), dietary_preference)
        ]
        for food in usda_results:
            food["allergy_check"] = usda_allergens_clear(food, user_allergies)
            food["allergy_note"] = (
                "Allergen declaration available" if food["allergy_check"] and user_allergies
                else "USDA does not provide a declaration for this record; allergen safety cannot be confirmed"
                if user_allergies else "Check product label for allergens"
            )
        return jsonify(usda_results)

    # Food types compatible with each dietary preference.
    diet_compatibility = {
        "Vegan": ["Vegan"],
        "Vegetarian": ["Vegan", "Vegetarian"],
        "Eggetarian": ["Vegan", "Vegetarian", "Eggetarian"],
        "Non-Vegetarian": [
            "Vegan",
            "Vegetarian",
            "Eggetarian",
            "Non-Vegetarian",
        ],
    }

    compatible_diets = diet_compatibility.get(
        dietary_preference, ["Vegan", "Vegetarian"]
    )
    diet_placeholders = ",".join("?" for _ in compatible_diets)

    rows = db.execute(
        f"""SELECT f.id, f.name,
                   COALESCE(
                       (SELECT GROUP_CONCAT(c.name, ', ')
                        FROM food_categories fc
                        JOIN categories c ON c.id = fc.category_id
                        WHERE fc.food_id = f.id),
                       ''
                   ) AS category,
                   COALESCE(
                       fs.serving_name,
                       CAST(fn.per_amount AS TEXT) || ' ' || fn.per_unit
                   ) AS serving_size,
                   fn.calories *
                       (COALESCE(fs.serving_quantity, fn.per_amount)
                        / fn.per_amount) AS calories,
                   fn.protein_g *
                       (COALESCE(fs.serving_quantity, fn.per_amount)
                        / fn.per_amount) AS protein,
                   fn.carbohydrates_g *
                       (COALESCE(fs.serving_quantity, fn.per_amount)
                        / fn.per_amount) AS carbs,
                   fn.fat_g *
                       (COALESCE(fs.serving_quantity, fn.per_amount)
                        / fn.per_amount) AS fat,
                   COALESCE(fn.fiber_g, 0) *
                       (COALESCE(fs.serving_quantity, fn.per_amount)
                        / fn.per_amount) AS fiber
            FROM foods f
            JOIN food_nutrition fn ON fn.food_id = f.id
            LEFT JOIN food_servings fs
                ON fs.food_id = f.id AND fs.is_default = 1
            WHERE f.dietary_type IN ({diet_placeholders})
              AND (
                  f.name LIKE ?
                  OR EXISTS (
                      SELECT 1
                      FROM food_aliases fa
                      WHERE fa.food_id = f.id
                        AND fa.alias LIKE ?
                  )
              )
              AND NOT EXISTS (
                  SELECT 1
                  FROM user_allergies ua
                  JOIN allergens a ON a.id = ua.allergen_id
                  JOIN food_allergens fa ON fa.allergen_id = a.id
                  WHERE ua.user_id = ?
                    AND a.name != ?
                    AND fa.food_id = f.id
              )
            ORDER BY f.name
            LIMIT 20""",
        (
            *compatible_diets,
            f"%{query}%",
            f"%{query}%",
            user_id,
            NO_ALLERGY_LABEL,
        ),
    ).fetchall()

    local_results = []
    for row in rows:
        food = dict(row)
        food["source"] = "Local"
        local_results.append(food)

    return jsonify(local_results)



@app.route("/meals/new", methods=("GET", "POST"))
@login_required
def add_meal():
    db = get_db()
    user_id = g.user["id"]

    if request.method == "POST":
        meal_type = request.form.get("meal_type", "")
        food_ids_raw = request.form.getlist("food_id")
        quantities_raw = request.form.getlist("quantity")
        fdc_ids_raw = request.form.getlist("fdc_id")
        usda_quantities_raw = request.form.getlist("usda_quantity")
        usda_grams_raw = request.form.getlist("usda_grams")
        usda_labels_raw = request.form.getlist("usda_serving_label")

        error = None
        if meal_type not in MEAL_TYPES:
            error = "Please choose a valid meal type."
        elif not food_ids_raw and not fdc_ids_raw:
            error = "Add at least one food before saving."
        elif len(food_ids_raw) != len(quantities_raw):
            error = "Malformed submission — please try again."

        parsed_items = []
        parsed_usda_items = []
        if error is None:
            for fid_raw, qty_raw in zip(food_ids_raw, quantities_raw):
                try:
                    food_id = int(fid_raw)
                except ValueError:
                    error = "Invalid food selected."
                    break
                try:
                    quantity = float(qty_raw)
                except ValueError:
                    error = "Quantity must be a number."
                    break
                if not (0 < quantity <= 50):
                    error = "Quantity must be greater than 0 and at most 50 servings."
                    break
                parsed_items.append((food_id, quantity))

        if error is None and not (
            len(fdc_ids_raw) == len(usda_quantities_raw) == len(usda_grams_raw) == len(usda_labels_raw)
        ):
            error = "Malformed USDA food submission — please try again."
        if error is None:
            for fdc_raw, qty_raw, grams_raw, label in zip(
                fdc_ids_raw, usda_quantities_raw, usda_grams_raw, usda_labels_raw
            ):
                try:
                    fdc_id, quantity, grams = int(fdc_raw), float(qty_raw), float(grams_raw)
                except (ValueError, TypeError):
                    error = "Invalid USDA food selection."
                    break
                if fdc_id <= 0 or not (0 < quantity <= 50) or not (0 < grams <= 5000):
                    error = "USDA quantity must be between 0 and 50 servings."
                    break
                parsed_usda_items.append((fdc_id, quantity, grams, label[:120]))

        if error is None and parsed_items:
            food_id_set = {food_id for food_id, _ in parsed_items}
            placeholders = ",".join("?" * len(food_id_set))
            valid_ids = {
                row["id"]
                for row in db.execute(
                    f"SELECT id FROM foods WHERE id IN ({placeholders})",
                    tuple(food_id_set),
                ).fetchall()
            }
            if valid_ids != food_id_set:
                error = "One or more selected foods could not be found."

        if error is None and parsed_items:
            active_allergy_ids = [row["allergen_id"] for row in db.execute(
                """SELECT allergen_id FROM user_allergies ua
                   JOIN allergens a ON a.id=ua.allergen_id
                   WHERE ua.user_id=? AND a.name != ?""",
                (user_id, NO_ALLERGY_LABEL),
            ).fetchall()]
            if active_allergy_ids:
                allergy_marks = ",".join("?" for _ in active_allergy_ids)
                conflict = db.execute(
                    f"""SELECT 1 FROM food_allergens
                       WHERE food_id IN ({','.join('?' for _ in {food_id for food_id, _ in parsed_items})})
                         AND allergen_id IN ({allergy_marks}) LIMIT 1""",
                    (*{food_id for food_id, _ in parsed_items}, *active_allergy_ids),
                ).fetchone()
                if conflict:
                    error = "One or more foods conflict with your saved allergy settings."

        if error is None and parsed_items:
            # Resolve the exact nutrition row used by search and copy its values
            # into the meal item. Historical records must not change when a
            # food's canonical nutrition is updated later.
            nutrition_by_food = {}
            for food_id, _quantity in parsed_items:
                nutrition = db.execute(
                    """SELECT fn.per_amount, fn.per_unit, fn.calories, fn.protein_g,
                              fn.carbohydrates_g, fn.fat_g, fn.fiber_g,
                              fs.serving_name, fs.serving_quantity
                       FROM food_nutrition fn
                       LEFT JOIN food_servings fs
                         ON fs.food_id = fn.food_id AND fs.is_default = 1
                       WHERE fn.food_id = ?""",
                    (food_id,),
                ).fetchone()
                if nutrition is None:
                    error = "Nutrition data is unavailable for one or more selected foods."
                    break
                nutrition_by_food[food_id] = nutrition

        if error is None:
            try:
                cur = db.execute(
                    "INSERT INTO meals (user_id, meal_type, logged_date) VALUES (?, ?, ?)",
                    (user_id, meal_type, date.today().isoformat()),
                )
                meal_id = cur.lastrowid
                profile = db.execute(
                    "SELECT dietary_preference FROM profiles WHERE user_id = ?", (user_id,)
                ).fetchone()
                dietary_preference = profile["dietary_preference"] if profile else "Vegetarian"
                for food_id, quantity in parsed_items:
                    nutrition = nutrition_by_food[food_id]
                    serving_quantity = nutrition["serving_quantity"] or nutrition["per_amount"]
                    serving_unit = nutrition["per_unit"]
                    scale = serving_quantity / nutrition["per_amount"]
                    db.execute(
                        """INSERT INTO meal_items (
                               meal_id, food_id, quantity, food_name_at_logging,
                               serving_name_at_logging, serving_quantity_at_logging,
                               serving_unit_at_logging, calories_at_logging,
                               protein_at_logging, carbs_at_logging, fat_at_logging,
                               fiber_at_logging
                           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            meal_id, food_id, quantity,
                            db.execute("SELECT name FROM foods WHERE id = ?", (food_id,)).fetchone()["name"],
                            nutrition["serving_name"] or (
                                f"{serving_quantity:g} {serving_unit}"
                            ),
                            serving_quantity, serving_unit,
                            nutrition["calories"] * scale,
                            nutrition["protein_g"] * scale,
                            nutrition["carbohydrates_g"] * scale,
                            nutrition["fat_g"] * scale,
                            (nutrition["fiber_g"] or 0) * scale,
                        ),
                    )
                user_allergies = [row["name"] for row in db.execute(
                    """SELECT a.name FROM user_allergies ua
                       JOIN allergens a ON a.id=ua.allergen_id
                       WHERE ua.user_id=? AND a.name != ?""",
                    (user_id, NO_ALLERGY_LABEL),
                ).fetchall()]
                for fdc_id, quantity, grams, label in parsed_usda_items:
                    food = get_usda_food_nutrition(fdc_id)
                    if (not food or food.get("fdc_id") != fdc_id or
                            not usda_food_matches_diet(food.get("name"),
                                dietary_preference) or
                            not usda_allergens_clear(food, user_allergies)):
                        raise ValueError("USDA food could not be verified against your saved dietary and allergy settings.")
                    portion = next((p for p in food.get("portions", [])
                                    if abs(float(p["grams"]) - grams) < 0.01), None)
                    if not portion and abs(grams - 100) < 0.01 and label == "100 g":
                        portion = {"label": label, "grams": grams}
                    if not portion:
                        raise ValueError("That USDA serving size is no longer available. Search again and choose a listed serving.")
                    values = [food.get(k) for k in ("calories", "protein", "carbs", "fat", "fiber")]
                    if any(value is None or value < 0 for value in values):
                        raise ValueError("USDA nutrition data is incomplete for this food.")
                    scale = grams / 100
                    db.execute(
                        """INSERT INTO usda_meal_items (
                           meal_id, fdc_id, quantity, food_name_at_logging,
                           serving_name_at_logging, serving_grams_at_logging,
                           calories_at_logging, protein_at_logging, carbs_at_logging,
                           fat_at_logging, fiber_at_logging
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (meal_id, fdc_id, quantity, food["name"],
                         portion["label"] if portion else label, grams,
                         values[0] * scale, values[1] * scale, values[2] * scale,
                         values[3] * scale, values[4] * scale),
                    )
                db.commit()
                flash(f"{meal_type} logged successfully.", "success")
                return redirect(url_for("dashboard"))
            except sqlite3.Error:
                db.rollback()
                app.logger.exception("Failed to save meal")
                error = "The meal could not be saved. Please try again."
            except ValueError as exc:
                db.rollback()
                error = str(exc)

        flash(error, "error")
        return render_template(
            "add_meal.html", meal_types=MEAL_TYPES, selected_type=meal_type
        )

    selected_type = request.args.get("type", "")
    if selected_type not in MEAL_TYPES:
        selected_type = MEAL_TYPES[0]
    return render_template(
        "add_meal.html", meal_types=MEAL_TYPES, selected_type=selected_type
    )


@app.route("/meals/<int:meal_id>")
@login_required
def view_meal(meal_id):
    db = get_db()
    meal = db.execute(
        "SELECT * FROM meals WHERE id = ? AND user_id = ?",
        (meal_id, g.user["id"]),
    ).fetchone()
    if meal is None:
        flash("Meal not found.", "error")
        return redirect(url_for("dashboard"))

    items = db.execute(
        """SELECT mi.food_id, mi.quantity, mi.serving_quantity_at_logging,
                  mi.serving_unit_at_logging,
                  COALESCE(mi.food_name_at_logging, f.name) AS name,
                  COALESCE(mi.serving_name_at_logging,
                           CAST(mi.serving_quantity_at_logging AS TEXT) || ' ' ||
                           mi.serving_unit_at_logging) AS serving_size,
                  mi.calories_at_logging AS calories,
                  mi.protein_at_logging AS protein,
                  mi.carbs_at_logging AS carbs,
                  mi.fat_at_logging AS fat,
                  COALESCE(mi.fiber_at_logging, 0) AS fiber
           FROM meal_items mi
           JOIN foods f ON f.id = mi.food_id
           WHERE mi.meal_id = ?
           UNION ALL
           SELECT NULL AS food_id, quantity, serving_grams_at_logging,
                  'g' AS serving_unit_at_logging, food_name_at_logging AS name,
                  serving_name_at_logging AS serving_size,
                  calories_at_logging AS calories, protein_at_logging AS protein,
                  carbs_at_logging AS carbs, fat_at_logging AS fat,
                  fiber_at_logging AS fiber
           FROM usda_meal_items WHERE meal_id = ?
           ORDER BY name""",
        (meal_id, meal_id),
    ).fetchall()

    totals = db.execute(
        """SELECT COALESCE(SUM(calories),0) calories,
                  COALESCE(SUM(protein),0) protein,
                  COALESCE(SUM(carbs),0) carbs,
                  COALESCE(SUM(fat),0) fat,
                  COALESCE(SUM(fiber),0) fiber
           FROM (
             SELECT SUM(calories_at_logging * quantity) calories,
                    SUM(protein_at_logging * quantity) protein,
                    SUM(carbs_at_logging * quantity) carbs,
                    SUM(fat_at_logging * quantity) fat,
                    SUM(COALESCE(fiber_at_logging,0) * quantity) fiber
             FROM meal_items WHERE meal_id = ?
             UNION ALL
             SELECT SUM(calories_at_logging * quantity),
                    SUM(protein_at_logging * quantity),
                    SUM(carbs_at_logging * quantity),
                    SUM(fat_at_logging * quantity),
                    SUM(fiber_at_logging * quantity)
             FROM usda_meal_items WHERE meal_id = ?
           )""",
        (meal_id, meal_id),
    ).fetchone()

    return render_template("meal_detail.html", meal=meal, items=items, totals=totals)


@app.route("/meals/<int:meal_id>/delete", methods=("POST",))
@login_required
def delete_meal(meal_id):
    db = get_db()
    meal = db.execute(
        "SELECT id FROM meals WHERE id = ? AND user_id = ?",
        (meal_id, g.user["id"]),
    ).fetchone()
    if meal is None:
        flash("Meal not found.", "error")
    else:
        db.execute("DELETE FROM meals WHERE id = ?", (meal_id,))
        db.commit()
        flash("Meal deleted.", "success")
    return redirect(url_for("dashboard"))


@app.route("/history")
@login_required
def meal_history():
    db = get_db()
    selected_date = request.args.get("date", "").strip()
    if selected_date:
        try:
            date.fromisoformat(selected_date)
        except ValueError:
            selected_date = ""
    sql = "SELECT id, meal_type, logged_date, created_at FROM meals WHERE user_id = ?"
    params = [g.user["id"]]
    if selected_date:
        sql += " AND logged_date = ?"
        params.append(selected_date)
    sql += " ORDER BY logged_date DESC, created_at DESC LIMIT 100"
    meals = db.execute(sql, params).fetchall()
    return render_template("history.html", meals=meals, selected_date=selected_date)


@app.route("/suggestions")
@login_required
def suggestions():
    db = get_db()
    user_id = g.user["id"]

    profile_row = db.execute(
        "SELECT dietary_preference FROM profiles WHERE user_id = ?", (user_id,)
    ).fetchone()
    dietary_preference = profile_row["dietary_preference"] if profile_row else "Vegetarian"
    compatible_diets = DIET_COMPATIBILITY.get(dietary_preference, DIETARY_PREFERENCES)

    user_allergy_names = {
        row["name"]
        for row in db.execute(
            """SELECT a.name FROM user_allergies ua
               JOIN allergens a ON a.id = ua.allergen_id
               WHERE ua.user_id = ?""",
            (user_id,),
        ).fetchall()
        if row["name"] != NO_ALLERGY_LABEL
    }

    selected_type = request.args.get("type", "")
    if selected_type not in MEAL_TYPES:
        selected_type = ""

    placeholders = ",".join("?" * len(compatible_diets))
    sql = f"SELECT * FROM recipes WHERE dietary_type IN ({placeholders})"
    params = list(compatible_diets)
    if selected_type:
        sql += " AND meal_type = ?"
        params.append(selected_type)
    sql += " ORDER BY meal_type, name"
    candidates = db.execute(sql, params).fetchall()

    recipes = []
    for recipe in candidates:
        recipe_id = recipe["id"]
        recipe_items = db.execute(
            """SELECT ri.quantity, ri.unit, f.name,
                      fn.per_amount, fn.per_unit, fn.calories,
                      fn.protein_g, fn.carbohydrates_g, fn.fat_g
               FROM recipe_items ri
               JOIN foods f ON f.id = ri.food_id
               LEFT JOIN food_nutrition fn ON fn.food_id = f.id
               WHERE ri.recipe_id = ?
               ORDER BY ri.id""",
            (recipe_id,),
        ).fetchall()

        recipe_allergens = {
            row["name"]
            for row in db.execute(
                """SELECT DISTINCT a.name
                   FROM recipe_items ri
                   JOIN food_allergens fa ON fa.food_id = ri.food_id
                   JOIN allergens a ON a.id = fa.allergen_id
                   WHERE ri.recipe_id = ?""",
                (recipe_id,),
            ).fetchall()
        }
        ingredient_labels = []
        calories = protein = carbs = fat = 0.0
        # Only calculate totals when recipe ingredient units can be safely
        # reconciled with the food's stored nutrition basis. The migrated
        # legacy recipes currently have no recipe_items, so their totals remain unknown.
        has_nutrition = bool(recipe_items) and all(
            item["per_amount"] is not None
            and item["per_unit"] is not None
            and item["unit"].strip().lower() in {
                item["per_unit"].strip().lower(),
                "g", "gram", "grams", "ml", "milliliter", "milliliters"
            }
            for item in recipe_items
        )
        for item in recipe_items:
            ingredient_labels.append(f"{item['name']} ({item['quantity']:g} {item['unit']})")
            unit = item["unit"].strip().lower()
            per_unit = item["per_unit"].strip().lower() if item["per_unit"] else ""
            if unit in {"g", "gram", "grams", "ml", "milliliter", "milliliters"} and per_unit in {"g", "gram", "grams", "ml", "milliliter", "milliliters"}:
                factor = item["quantity"] / item["per_amount"]
            elif unit == per_unit:
                factor = item["quantity"] / item["per_amount"]
            else:
                factor = 0
            calories += (item["calories"] or 0) * factor
            protein += (item["protein_g"] or 0) * factor
            carbs += (item["carbohydrates_g"] or 0) * factor
            fat += (item["fat_g"] or 0) * factor

        # Migrated legacy recipes may not yet have recipe_items. The old
        # ingredient text was preserved in description, so do not invent
        # ingredient quantities or claim nutrition values we cannot calculate.
        recipe_dict = dict(recipe)
        recipe_dict["ingredients"] = ", ".join(ingredient_labels) if ingredient_labels else "Ingredient details need to be updated for this recipe."
        recipe_dict["description"] = recipe["description"] or ""
        recipe_dict["instructions"] = recipe["instructions"] or ""
        recipe_dict["calories"] = round(calories, 2) if has_nutrition else None
        recipe_dict["protein"] = round(protein, 2) if has_nutrition else None
        recipe_dict["carbs"] = round(carbs, 2) if has_nutrition else None
        recipe_dict["fat"] = round(fat, 2) if has_nutrition else None

        if recipe_allergens & user_allergy_names:
            continue
        recipes.append(recipe_dict)

    return render_template(
        "suggestions.html",
        recipes=recipes,
        meal_types=MEAL_TYPES,
        selected_type=selected_type,
        dietary_preference=dietary_preference,
    )


if __name__ == "__main__":
    app.run(debug=True)
