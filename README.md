# NutriTrack

NutriTrack is a web-based nutrition tracking application designed to help users track their daily meals, monitor nutritional intake, manage dietary preferences and allergies, and discover suitable meal suggestions.

The application focuses on Indian foods and uses data from the Indian Nutrient Databank (INDB) to provide nutritional information for foods available in the database.

## Features

- User registration and login
- Secure password hashing
- User profile and onboarding
- Dietary preference selection
- Allergy management
- Daily nutrition dashboard
- Meal logging for breakfast, lunch, snacks, and dinner
- Food search with live results
- Quantity-based nutrition calculation
- Calories, protein, carbohydrates, fat, and fiber tracking
- Detailed meal history
- Rule-based meal suggestions
- Optional Gemini-personalized meal suggestions for adult users
- Responsive web interface

## Technology Stack

### Backend

- Python
- Flask
- SQLite
- Jinja2
- Werkzeug

### Frontend

- HTML
- CSS
- JavaScript
- Jinja2 templates

### Data

- Indian Nutrient Databank (INDB)

## Google sign-in setup

Google sign-in uses OpenID Connect and requests only the user's basic profile and verified email; it does not access Gmail. To enable it:

1. Install the project dependencies with `pip install -r requirements.txt`.
2. Create a Google OAuth web client in Google Cloud Console and add the app callback URL as an authorized redirect URI. For local development, use `http://127.0.0.1:5000/auth/google/callback`.
3. Put `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` in the local `.env` file. Keep `.env` private and out of Git.
4. Apply `migrations/002_google_identities.sql` to the existing database as an additive migration. Back up the database first; do not run schema initialization against it.

An existing password account must be signed into before linking Google from the profile page. This avoids silently merging accounts based only on matching email addresses.

## Gemini suggestions

The optional Gemini feature is available to users aged 18 and over. Set `GEMINI_API_KEY` in the local `.env` file to enable it. The dashboard and suggestions page call Gemini only after the user clicks the personalization button. The request contains the user's dietary preference and nutrition goal plus locally diet- and allergen-filtered recipes with structured ingredients and database nutrition; it excludes the user's name, age, height, weight, allergy list, and meal history. Gemini can rank known recipe IDs and explain the picks, but it cannot add foods or nutrition values. Review the [Gemini API terms](https://ai.google.dev/gemini-api/terms) before using real user data; unpaid API usage may be used to improve Google's products.

## How It Works

NutriTrack follows a simple client-server architecture.

```text
User
 |
 v
Web Browser
(HTML, CSS, JavaScript)
 |
 | HTTP Requests
 v
Flask Application
(app.py)
 |
 +------------------+
 |                  |
 v                  v
Jinja2            Application
Templates          Logic
 |
 v
SQLite Database
 |
 +-------------------------------+
 |        |        |      |      |
Users   Profiles  Foods  Meals  Recipes
                         |
                         v
                    Meal Items
