# Flask Expense Tracker API

A small REST API for recording personal income and expenses, filtering transactions, and producing a monthly summary. Flask serves the endpoints; SQLite stores data; pytest covers the main request paths and validation rules.

## Features

- Create, view, filter, update, and delete transactions.
- Filter transactions by type, category, and date range, with limit/offset pagination.
- Produce monthly income, expense, net, and category totals.
- Validate dates, transaction types, and positive amounts; store amounts as integer kobo to avoid floating-point arithmetic in the database.
- Use parameterized SQL queries.

This is a local learning project. It does not implement user authentication, authorization, or production deployment controls. Do not use it to store real financial information.

## Endpoints

| Method | Route | Purpose |
| --- | --- | --- |
| GET | `/health` | Health check |
| GET | `/api/transactions` | List/filter transactions |
| POST | `/api/transactions` | Create a transaction |
| GET | `/api/transactions/<id>` | Retrieve one transaction |
| PATCH | `/api/transactions/<id>` | Update selected fields |
| DELETE | `/api/transactions/<id>` | Delete a transaction |
| GET | `/api/reports/monthly?month=YYYY-MM` | Monthly totals |

## Setup

```bash
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
python -m pip install -r requirements-dev.txt
```

## Run

```bash
flask --app app:create_app run --debug
```

By default, the database is created at `instance/expenses.sqlite3`. Override it with the `DATABASE` Flask configuration when using the app factory in tests or another WSGI setup.

## Example request

```bash
curl -X POST http://127.0.0.1:5000/api/transactions \
  -H 'Content-Type: application/json' \
  -d '{"type":"expense","amount":"1250.00","category":"Transport","description":"Bus fare","date":"2026-09-28"}'
```

```bash
curl 'http://127.0.0.1:5000/api/reports/monthly?month=2026-09'
```

## Tests

```bash
pytest
```

## Resume-ready description

Built a Flask and SQLite expense tracker API with 7 endpoints for transaction creation, retrieval, filtering, updates, deletion, and monthly summaries; added request validation and automated tests.
