# NutriTrack

NutriTrack is a Flask-based nutrition tracking application focused on Indian
foods. Users can create an account, complete a nutrition profile, search food
databases, log meals, review nutrition totals, and receive rule-based recipe
suggestions.

The application uses the Indian Nutrient Databank (INDB) for its local food
catalogue and can optionally search USDA FoodData Central for additional food
records.

## Features

### Accounts and authentication

- User registration and password login
- Secure password hashing with Werkzeug
- Google OpenID Connect sign-in
- Linking Google sign-in to an existing password account
- Profile onboarding for new users
- Session protection and CSRF validation for state-changing requests

### Profile and preferences

- Age, height, and weight information
- Dietary preferences:
  - Vegetarian
  - Non-Vegetarian
  - Vegan
  - Eggetarian
- Nutrition goals:
  - Lose Weight
  - Maintain Weight
  - Gain Weight
  - Build Muscle
  - General Health
- Allergy selection, including a **No Known Allergies** option
- Dietary and allergy filtering for local foods and recipe suggestions

### Food search and meal logging

- Live search across local INDB foods
- Optional USDA FoodData Central search
- Search results with serving information and nutrition values
- USDA serving-size selection
- Quantity-based nutrition calculations
- Meal logging for:
  - Breakfast
  - Lunch
  - Snack
  - Dinner
- Meal logging from both local and USDA food sources
- Server-side validation of submitted foods, quantities, diets, and allergies
- Nutrition snapshots stored at logging time so historical meals remain stable

### Nutrition tracking

- Daily calorie totals
- Protein, carbohydrate, and fat totals
- Fiber information for logged items
- Per-meal nutrition summaries
- Detailed meal views
- Meal deletion
- Date-filtered meal history

### Recipe suggestions

- Rule-based recipe recommendations
- Filtering by meal type
- Dietary preference compatibility filtering
- Allergy filtering
- Ingredient and preparation information
- Nutrition totals when structured ingredient data is available
- Clear messaging when recipe nutrition is incomplete

### User experience

- Responsive dark-themed interface
- Mobile, tablet, laptop, and desktop layouts
- Keyboard focus indicators
- Accessible form labels and live search status messages
- Responsive food search and meal logging controls
- Consistent buttons, cards, form controls, spacing, and allergy-selection states

> Gemini integration is intentionally not part of the current application.

## Technology stack

### Backend

- Python
- Flask
- SQLite
- Jinja2
- Werkzeug
- Authlib
- Requests
- python-dotenv

### Frontend

- HTML
- Jinja2 templates
- CSS
- Vanilla JavaScript

### Data sources

- Indian Nutrient Databank (local database)
- USDA FoodData Central API (optional)

## Project structure

```text
NutriTrack_v2/
├── app.py                         # Flask application and routes
├── requirements.txt               # Python dependencies
├── nutritrack_v2.db              # Populated application database
├── schema.sql                     # Original schema reference
├── schema_v2.sql                  # Schema reference
├── schema_v2_actual.sql           # Snapshot of the migrated schema
├── migrations/
│   ├── 001_usda_meal_items.sql    # USDA meal snapshot table
│   └── 002_google_identities.sql   # Google identity linking table
├── scripts/
│   └── import_indb.py             # INDB import utility
├── data/
│   └── Anuvaad_INDB_2024_11.xlsx  # INDB source workbook
├── static/
│   └── css/style.css              # Application styles
└── templates/                     # Jinja2 page templates
```

## Requirements

- Python 3.10 or newer
- A populated SQLite database
- Optional: USDA FoodData Central API key
- Optional: Google OAuth web application credentials

## Installation

Create and activate a virtual environment:

### Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### macOS or Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install dependencies:

```bash
python -m pip install -r requirements.txt
```

## Configuration

Create a local `.env` file in the project root:

```env
FLASK_SECRET_KEY=replace-with-a-long-random-secret
FLASK_ENV=development
FLASK_DEBUG=1

# Optional USDA FoodData Central integration
USDA_API_KEY=your-usda-api-key

# Optional Google OpenID Connect integration
GOOGLE_CLIENT_ID=your-google-client-id
GOOGLE_CLIENT_SECRET=your-google-client-secret
```

### Configuration notes

- Never commit `.env`, API keys, OAuth secrets, or production secrets.
- Use a stable, unpredictable `FLASK_SECRET_KEY` outside local development.
- `FLASK_DEBUG=1` is intended only for local development.
- In production, serve the application over HTTPS and set `FLASK_ENV=production`.
- USDA search is unavailable when `USDA_API_KEY` is not configured; local INDB
  search continues to work.

## Database setup and migrations

NutriTrack is distributed with a populated SQLite database. Do not run schema
initialization, seed scripts, or destructive database commands against that
database.

Apply migrations only when the corresponding tables are not already present:

```bash
sqlite3 nutritrack_v2.db < migrations/001_usda_meal_items.sql
sqlite3 nutritrack_v2.db < migrations/002_google_identities.sql
```

Before applying a migration:

1. Back up `nutritrack_v2.db`.
2. Check whether the target table already exists.
3. Apply the migration once.
4. Verify that existing users and meals are still present.

The migrations are additive. Existing meal records and historical nutrition
snapshots must not be deleted or rebuilt.

## Google sign-in setup

Google sign-in uses OpenID Connect and requests only the `openid`, `email`, and
`profile` scopes. It does not access Gmail.

1. Create a Google OAuth web client in Google Cloud Console.
2. Add the callback URL below as an authorized redirect URI:

   ```text
   http://127.0.0.1:5000/auth/google/callback
   ```

3. Set `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` in `.env`.
4. Apply `migrations/002_google_identities.sql` if the table is not present.
5. Start the application and test Google sign-in.

An existing password account must be signed into before Google can be linked
from the profile page. This prevents accounts from being merged solely because
their email addresses match.

## Running the application

From the project root:

```bash
python app.py
```

Open the local application at:

```text
http://127.0.0.1:5000
```

The application uses `nutritrack_v2.db` by default. It does not initialize or
seed the database automatically during startup.

## Security behavior

The application includes:

- Parameterized SQLite queries
- Password hashing and verification
- CSRF tokens for POST, PUT, PATCH, and DELETE requests
- HTTP-only session cookies
- SameSite session cookies
- Secure cookies in production
- Security response headers
- No-store caching for non-static pages
- Ownership checks for meals and user data
- Server-side validation for profile and meal inputs
- Dietary and allergy verification before meal logging
- Historical nutrition snapshots for logged meals

## Testing and validation

Run Python compilation checks:

```bash
python -m compileall -q app.py scripts seed_data.py
```

The application can also be validated through Flask's test client for:

- Registration and login
- CSRF rejection
- Profile completion
- Protected route access
- Local food search
- USDA search behavior when configured
- Meal logging and dietary validation
- Meal history and suggestions
- Logout

## Development safety

- Do not reset or recreate the populated database.
- Do not run `seed_data.py` against the submission database.
- Do not modify existing migration history.
- Do not commit credentials or secrets.
- Preserve historical meal nutrition snapshots.
- Keep external API keys server-side; never expose them in frontend code.

## License and data attribution

This project is intended for educational use. Review the terms and attribution
requirements of the Indian Nutrient Databank and USDA FoodData Central before
redistributing datasets or deploying the application publicly.
