import os
import sqlite3
from datetime import date
from functools import wraps

from flask import (
    Flask, g, render_template, request, redirect, url_for, session, flash, jsonify
)
from werkzeug.security import generate_password_hash, check_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE = os.path.join(BASE_DIR, "nutritrack.db")

app = Flask(__name__)
app.config["SECRET_KEY"] = "dev-secret-key-change-in-production"
app.config["DATABASE"] = DATABASE

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

# Sentinel allergy row a user selects to explicitly confirm "I have no
# allergies." This lets us tell "confirmed no allergies" apart from
# "hasn't answered yet" (zero rows in user_allergies) without adding a
# new column or table — see is_profile_complete() below.
NO_ALLERGY_LABEL = "No Known Allergies"

# Endpoints reachable by a logged-in user even with an incomplete profile.
PROFILE_SETUP_EXEMPT_ENDPOINTS = {"profile", "logout", "static", None}


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


def init_db():
    db = get_db()
    with app.open_resource("schema.sql") as f:
        db.executescript(f.read().decode("utf8"))
    db.commit()


@app.cli.command("init-db")
def init_db_command():
    """Drop and recreate all tables (destroys existing data)."""
    init_db()
    print("Initialized the database.")


@app.cli.command("seed-db")
def seed_db_command():
    """Populate reference data: allergies, foods, recipes."""
    from seed_data import seed
    seed(get_db())
    print("Seeded the database with foods, allergies and recipes.")


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
        "SELECT id, name FROM allergies ORDER BY name"
    ).fetchall()
    selected_allergy_ids = {
        row["allergy_id"]
        for row in db.execute(
            "SELECT allergy_id FROM user_allergies WHERE user_id = ?", (user_id,)
        ).fetchall()
    }
    no_allergy_row = db.execute(
        "SELECT id FROM allergies WHERE name = ?", (NO_ALLERGY_LABEL,)
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
                    "INSERT INTO user_allergies (user_id, allergy_id) VALUES (?, ?)",
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
             COALESCE(SUM(f.calories * mi.quantity), 0) AS calories,
             COALESCE(SUM(f.protein * mi.quantity), 0)  AS protein,
             COALESCE(SUM(f.carbs * mi.quantity), 0)    AS carbs,
             COALESCE(SUM(f.fat * mi.quantity), 0)      AS fat
           FROM meals m
           JOIN meal_items mi ON mi.meal_id = m.id
           JOIN foods f ON f.id = mi.food_id
           WHERE m.user_id = ? AND m.logged_date = ?""",
        (user_id, today.isoformat()),
    ).fetchone()

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

    return render_template(
        "dashboard.html",
        user=g.user,
        today=today,
        totals=totals,
        meal_types=MEAL_TYPES,
        logged_meal_types=set(logged_meals.keys()),
        logged_meals=logged_meals,
    )


@app.route("/api/foods/search")
@login_required
def api_food_search():
    query = request.args.get("q", "").strip()
    if len(query) < 2:
        return jsonify([])

    db = get_db()
    rows = db.execute(
        """SELECT id, name, category, serving_size, calories, protein,
                  carbs, fat, fiber
           FROM foods
           WHERE name LIKE ?
           ORDER BY name
           LIMIT 20""",
        (f"%{query}%",),
    ).fetchall()
    return jsonify([dict(row) for row in rows])


@app.route("/meals/new", methods=("GET", "POST"))
@login_required
def add_meal():
    db = get_db()
    user_id = g.user["id"]

    if request.method == "POST":
        meal_type = request.form.get("meal_type", "")
        food_ids_raw = request.form.getlist("food_id")
        quantities_raw = request.form.getlist("quantity")

        error = None
        if meal_type not in MEAL_TYPES:
            error = "Please choose a valid meal type."
        elif not food_ids_raw:
            error = "Add at least one food before saving."
        elif len(food_ids_raw) != len(quantities_raw):
            error = "Malformed submission — please try again."

        parsed_items = []
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

        if error is None:
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

        if error is None:
            cur = db.execute(
                "INSERT INTO meals (user_id, meal_type, logged_date) VALUES (?, ?, ?)",
                (user_id, meal_type, date.today().isoformat()),
            )
            meal_id = cur.lastrowid
            db.executemany(
                "INSERT INTO meal_items (meal_id, food_id, quantity) VALUES (?, ?, ?)",
                [(meal_id, food_id, quantity) for food_id, quantity in parsed_items],
            )
            db.commit()
            flash(f"{meal_type} logged successfully.", "success")
            return redirect(url_for("dashboard"))

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
        """SELECT f.name, f.serving_size, f.category, mi.quantity,
                  f.calories, f.protein, f.carbs, f.fat, f.fiber
           FROM meal_items mi
           JOIN foods f ON f.id = mi.food_id
           WHERE mi.meal_id = ?
           ORDER BY mi.id""",
        (meal_id,),
    ).fetchall()

    totals = db.execute(
        """SELECT
             COALESCE(SUM(f.calories * mi.quantity), 0) AS calories,
             COALESCE(SUM(f.protein * mi.quantity), 0)  AS protein,
             COALESCE(SUM(f.carbs * mi.quantity), 0)    AS carbs,
             COALESCE(SUM(f.fat * mi.quantity), 0)      AS fat,
             COALESCE(SUM(f.fiber * mi.quantity), 0)    AS fiber
           FROM meal_items mi
           JOIN foods f ON f.id = mi.food_id
           WHERE mi.meal_id = ?""",
        (meal_id,),
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


if __name__ == "__main__":
    app.run(debug=True)
