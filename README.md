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