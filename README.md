# Smart Textile Production Management System

Created by **Chaitanya Sutrave**.

A Django web application for running a textile mill floor: raw material and yarn inventory, production orders that move
from spinning to weaving to finishing, daily targets, machine downtime, defect and rejection tracking, and printable reports.

**Stack:** HTML, CSS, JavaScript, Bootstrap 5, Python Django 5, PostgreSQL, Chart.js
(Bootstrap, Bootstrap Icons, Chart.js and the IBM Plex Sans font are bundled in `static/`, so the app works offline.)

## Features

| Area | What you can do |
|---|---|
| Dashboard | Today's output vs target per stage, machines running/down, rejection rate, low-stock alerts, 14-day output trend, downtime by reason, defects by type |
| Inventory | Yarn, fabric and raw materials with reorder levels, stock in/out movements with history, stock value |
| Orders | Production orders with yarn requirement, due date, stage-wise progress, "move to next stage" button |
| Production log | Shift-wise output and waste per order, stage and machine |
| Daily targets | One target per stage per day, compared automatically with logged output |
| Machines and downtime | Machine register, log a stoppage, mark it resolved, downtime hours per machine and per reason |
| Defects | Defect type, severity, action taken (rework, downgrade, reject), metres affected |
| Reports | Production summary, target vs actual, downtime, defects, inventory valuation. Date range, print, CSV export |

## Setup

```bash
# 1. Create a virtual environment and install dependencies
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # macOS / Linux
pip install -r requirements.txt

# 2. Configure the database
copy .env.example .env         # Windows   (cp .env.example .env on macOS / Linux)
```

### PostgreSQL

Create the database once, then keep the `DB_*` values in `.env` matching it:

```sql
CREATE DATABASE textile_pms;
```

If you delete the `DB_NAME` line from `.env` (or have no `.env`), the project uses SQLite instead, which is handy for a quick look.

```bash
# 3. Create tables and load demo data
python manage.py migrate
python manage.py seed_demo          # creates the login admin / admin123 and about three weeks of sample data

# 4. Run
python manage.py runserver
```

Open http://127.0.0.1:8000 and sign in with **admin / admin123**.

To start with an empty system instead, skip `seed_demo` and run `python manage.py createsuperuser`.
Re-run `python manage.py seed_demo --reset` any time to rebuild the demo data.

> **Demo account:** `seed_demo` creates the local demo login `admin / admin123`. This fixed password is for local evaluation only; never use it on a publicly accessible deployment.

## Tests

```bash
python manage.py test
```

## Project layout

```
config/            settings, root URLs
core/models.py     Material, StockMovement, Machine, ProductionOrder, StageLog, DailyTarget, DowntimeRecord, DefectRecord
core/views.py      dashboard, CRUD views, reports (with CSV export)
core/forms.py      Bootstrap-styled model forms
core/management/   seed_demo command
templates/         base layout, login, one template per page, shared partials
static/css/app.css interface styles
static/js/         dashboard charts (Chart.js) and small UI helpers
```

## Notes

- Units: spinning output is in kg of yarn; weaving and finishing output is in metres of fabric. Order progress compares each stage against the yarn required (spinning) or the fabric planned (weaving, finishing).
- Before deploying, set `DEBUG=False`, a long random `SECRET_KEY`, your host in `ALLOWED_HOSTS`, and production database credentials. Do not deploy the demo account or its fixed password. Run `python manage.py collectstatic` and serve static files with your web server or WhiteNoise.
