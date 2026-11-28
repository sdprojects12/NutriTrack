import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app as webapp
from scripts.init_db import apply_migrations, initialize


class NutriTrackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "test.sqlite3"
        root = Path(__file__).resolve().parent.parent
        initialize(self.db_path, root / "data" / "Anuvaad_INDB_2024_11.xlsx")
        self.old_db = webapp.app.config.get("DATABASE")
        self.old_testing = webapp.app.config.get("TESTING")
        webapp.app.config.update(TESTING=True, DATABASE=str(self.db_path), SECRET_KEY="test-key")
        webapp._usda_search_cache.clear()
        self.client = webapp.app.test_client()

    def tearDown(self):
        self.client = None
        webapp.app.config.update(DATABASE=self.old_db, TESTING=self.old_testing)
        import gc
        gc.collect()
        with webapp.app.app_context():
            webapp.close_db()
        self.temp.cleanup()

    def token(self, path="/signup"):
        response = self.client.get(path)
        self.assertEqual(response.status_code, 200)
        return re.search(rb'name="_csrf_token" value="([^"]+)', response.data).group(1).decode()

    def signup_and_login(self, email="person@example.test"):
        token = self.token()
        response = self.client.post("/signup", data={
            "_csrf_token": token, "name": "Test Person", "email": email,
            "password": "password123", "confirm_password": "password123",
        })
        self.assertEqual(response.status_code, 302)
        token = self.token("/login")
        response = self.client.post("/login", data={
            "_csrf_token": token, "email": email, "password": "password123",
        })
        self.assertEqual(response.status_code, 302)

    def complete_profile(self, allergy_ids=None, diet="Vegan"):
        token = self.token("/profile")
        ids = allergy_ids or [str(self.allergy_id("No Known Allergies"))]
        data = {
            "_csrf_token": token, "age": "30", "height_cm": "170", "weight_kg": "65",
            "dietary_preference": diet, "general_goal": "General Health", "allergies": ids,
        }
        return self.client.post("/profile", data=data)

    def allergy_id(self, name):
        import sqlite3
        with sqlite3.connect(self.db_path) as conn:
            return conn.execute("SELECT id FROM allergens WHERE name=?", (name,)).fetchone()[0]

    def test_health_and_readiness(self):
        self.assertEqual(self.client.get("/health").json["status"], "ok")
        self.assertEqual(self.client.get("/ready").json["status"], "ready")

    def test_missing_database_is_not_created_by_health_check(self):
        missing = self.db_path.parent / "not-initialized.sqlite3"
        webapp.app.config["DATABASE"] = str(missing)
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 503)
        self.assertFalse(missing.exists())

    def test_signup_login_and_invalid_credentials(self):
        self.signup_and_login()
        self.client.post("/logout", data={"_csrf_token": self.token("/profile")})
        token = self.token("/login")
        response = self.client.post("/login", data={"_csrf_token": token, "email": "person@example.test", "password": "wrong"})
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Incorrect email or password", response.data)

    def test_signup_rolls_back_user_when_profile_creation_fails(self):
        import sqlite3
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("CREATE TRIGGER reject_profile BEFORE INSERT ON profiles BEGIN SELECT RAISE(ABORT, 'test failure'); END")
        response = self.client.post("/signup", data={
            "_csrf_token": self.token(), "name": "Atomic", "email": "atomic@example.test",
            "password": "password123", "confirm_password": "password123",
        })
        self.assertEqual(response.status_code, 409)
        with sqlite3.connect(self.db_path) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM users WHERE email='atomic@example.test'").fetchone()[0], 0)

    def test_profile_validation_and_onboarding(self):
        self.signup_and_login()
        response = self.complete_profile(diet="Not a diet")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Please choose a dietary preference", response.data)
        response = self.complete_profile()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.get("/dashboard").status_code, 200)

    def test_local_search_filters_saved_allergens(self):
        self.signup_and_login()
        self.complete_profile([str(self.allergy_id("Peanut"))], diet="Non-Vegetarian")
        response = self.client.get("/api/foods/search?q=peanut")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(all("peanut" not in food["name"].lower() for food in response.json))

    def test_recipe_allergy_filtering_uses_explicit_seed_tags(self):
        self.signup_and_login()
        self.complete_profile([str(self.allergy_id("Peanut"))], diet="Vegan")
        response = self.client.get("/suggestions")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b"Peanut Chaat", response.data)

    def test_google_identity_schema_and_oauth_configuration(self):
        import sqlite3
        with sqlite3.connect(self.db_path) as conn:
            names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertIn("user_identities", names)
            self.assertIn("recipe_allergens", names)
            self.assertIn("usda_meal_items", names)
            versions = [row[0] for row in conn.execute("SELECT version FROM schema_migrations ORDER BY version")]
            self.assertEqual(versions, ["001_usda_meal_items.sql", "002_google_identities.sql", "003_recipe_allergens.sql"])
            apply_migrations(conn)
            conn.execute("DELETE FROM schema_migrations")
            conn.commit()
            apply_migrations(conn)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0], 3)
        import os
        if os.environ.get("GOOGLE_CLIENT_ID") and os.environ.get("GOOGLE_CLIENT_SECRET"):
            self.assertIsNotNone(webapp.oauth.create_client("google"))
        else:
            self.skipTest("Google OAuth credentials are not configured")

    def test_usda_search_filters_matching_and_unverifiable_allergens(self):
        self.signup_and_login()
        self.complete_profile([str(self.allergy_id("Peanut"))], diet="Non-Vegetarian")
        mocked_foods = [
            {"fdc_id": 1, "name": "Peanut butter", "allergens": "peanuts", "ingredients": "peanuts, oil"},
            {"fdc_id": 2, "name": "Apple", "allergens": "", "ingredients": "apple, water"},
            {"fdc_id": 3, "name": "Packaged snack", "allergens": None, "ingredients": None},
            {"fdc_id": 4, "name": "Plain rice", "allergens": "", "ingredients": "rice, water"},
        ]
        with patch.object(webapp, "search_usda_foods", return_value=mocked_foods):
            response = self.client.get("/api/foods/search?source=usda&q=food")

        self.assertEqual(response.status_code, 200)
        self.assertEqual([food["fdc_id"] for food in response.json], [2, 4])
        self.assertTrue(all(food["allergy_check"] for food in response.json))
        self.assertIn("verify the product label", response.json[0]["allergy_note"])

    def test_usda_allergy_scan_uses_ingredients_and_word_boundaries(self):
        self.assertFalse(webapp.usda_allergens_clear(
            {"allergens": "", "ingredients": "roasted peanuts and salt"}, ["Peanut"]
        ))
        self.assertTrue(webapp.usda_allergens_clear(
            {"allergens": "", "ingredients": "eggplant, rice and salt"}, ["Egg"]
        ))
        self.assertFalse(webapp.usda_allergens_clear(
            {"allergens": "Contains: milk", "ingredients": "water"}, ["Dairy"]
        ))
        self.assertFalse(webapp.usda_allergens_clear(
            {"allergens": None, "ingredients": None}, ["Peanut"]
        ))
        self.assertTrue(webapp.usda_allergens_clear(
            {"allergens": None, "ingredients": None}, []
        ))

    def test_usda_failure_returns_empty_results(self):
        self.signup_and_login()
        self.complete_profile()
        with patch.object(webapp, "search_usda_foods", return_value=[]):
            response = self.client.get("/api/foods/search?source=usda&q=apple")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, [])

    def test_usda_timeout_and_malformed_response_are_handled(self):
        with patch.dict("os.environ", {"USDA_API_KEY": "test-key"}):
            with patch.object(webapp.requests, "get", side_effect=webapp.requests.Timeout("timeout")):
                self.assertEqual(webapp.search_usda_foods("apple"), [])
            malformed = unittest.mock.Mock()
            malformed.raise_for_status.return_value = None
            malformed.json.return_value = ["unexpected"]
            with patch.object(webapp.requests, "get", return_value=malformed):
                self.assertEqual(webapp.search_usda_foods("pear"), [])

    def test_meal_quantity_nutrition_history_and_ownership(self):
        self.signup_and_login()
        self.complete_profile()
        result = self.client.get("/api/foods/search?q=banana").json
        self.assertTrue(result)
        food_id = result[0]["id"]
        expected_calories = round(result[0]["calories"] * 2)
        token = self.token("/meals/new")
        bad = self.client.post("/meals/new", data={"_csrf_token": token, "meal_type": "Lunch", "food_id": str(food_id), "quantity": "0"})
        self.assertEqual(bad.status_code, 200)
        self.assertIn(b"Quantity must be greater than 0", bad.data)
        token = self.token("/meals/new")
        good = self.client.post("/meals/new", data={"_csrf_token": token, "meal_type": "Lunch", "food_id": str(food_id), "quantity": "2"})
        self.assertEqual(good.status_code, 302)
        history = self.client.get("/history")
        self.assertEqual(history.status_code, 200)
        import sqlite3
        with sqlite3.connect(self.db_path) as conn:
            meal_id = conn.execute("SELECT id FROM meals ORDER BY id DESC LIMIT 1").fetchone()[0]
            user_id = conn.execute("SELECT id FROM users WHERE email='person@example.test'").fetchone()[0]
            other_id = conn.execute("INSERT INTO users(name,email,password_hash) VALUES('Other','other@example.test','x')").lastrowid
            conn.execute("INSERT INTO profiles(user_id,age,height_cm,weight_kg,dietary_preference,general_goal) VALUES(?,30,170,65,'Vegan','General Health')", (other_id,))
            no_allergy = conn.execute("SELECT id FROM allergens WHERE name='No Known Allergies'").fetchone()[0]
            conn.execute("INSERT INTO user_allergies(user_id,allergen_id) VALUES(?,?)", (other_id, no_allergy))
            conn.commit()
        detail = self.client.get(f"/meals/{meal_id}")
        self.assertEqual(detail.status_code, 200)
        self.assertIn(f"<strong>{expected_calories}</strong> kcal".encode(), detail.data)
        with self.client.session_transaction() as session:
            session["user_id"] = other_id
        self.assertEqual(self.client.get(f"/meals/{meal_id}").status_code, 302)

    def test_initializer_creates_database_and_refuses_existing_path(self):
        schema = (Path(__file__).resolve().parent.parent / "schema.sql").read_text(encoding="utf-8")
        self.assertNotIn("CREATE TABLE usda_meal_items", schema)
        self.assertNotIn("CREATE TABLE user_identities", schema)
        self.assertNotIn("CREATE TABLE recipe_allergens", schema)
        with self.assertRaises(FileExistsError):
            initialize(self.db_path, Path(__file__).resolve().parent.parent / "data" / "Anuvaad_INDB_2024_11.xlsx")


if __name__ == "__main__":
    unittest.main()

