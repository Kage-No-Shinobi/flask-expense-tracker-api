"""Flask API for a local personal expense tracker."""

from __future__ import annotations

import re
import sqlite3
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from flask import Flask, current_app, g, jsonify, request

FIELDS = {"type", "amount", "category", "description", "date"}


def parse_iso_date(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("expected YYYY-MM-DD")
    return date.fromisoformat(value).isoformat()


def format_money(amount_cents: int) -> str:
    return f"{Decimal(amount_cents) / Decimal(100):.2f}"


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        connection = sqlite3.connect(current_app.config["DATABASE"])
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        g.db = connection
    return g.db


def close_db(_error: BaseException | None = None) -> None:
    connection = g.pop("db", None)
    if connection is not None:
        connection.close()


def init_db() -> None:
    get_db().executescript(
        """
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT NOT NULL CHECK (type IN ('income', 'expense')),
            amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
            category TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            date TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_transactions_date ON transactions(date);
        CREATE INDEX IF NOT EXISTS idx_transactions_category ON transactions(category);
        """
    )
    get_db().commit()


def create_app(test_config: dict[str, Any] | None = None) -> Flask:
    app = Flask(__name__)
    default_database = Path(app.instance_path) / "expenses.sqlite3"
    app.config.from_mapping(DATABASE=str(default_database), TESTING=False)
    if test_config:
        app.config.update(test_config)
    Path(app.config["DATABASE"]).parent.mkdir(parents=True, exist_ok=True)
    app.teardown_appcontext(close_db)

    with app.app_context():
        init_db()

    def bad_request(message: str):
        return jsonify(error=message), 400

    def get_payload():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return None, bad_request("Request body must be a JSON object.")
        return payload, None

    def validate_payload(payload: dict[str, Any], *, partial: bool = False):
        unknown = set(payload) - FIELDS
        if unknown:
            return None, f"Unknown field(s): {', '.join(sorted(unknown))}."
        if partial and not payload:
            return None, "Provide at least one field to update."
        required = {"type", "amount", "category", "date"}
        if not partial:
            missing = required - set(payload)
            if missing:
                return None, f"Missing required field(s): {', '.join(sorted(missing))}."

        result: dict[str, Any] = {}
        if "type" in payload:
            kind = payload["type"]
            if not isinstance(kind, str) or kind.strip().lower() not in {"income", "expense"}:
                return None, "type must be 'income' or 'expense'."
            result["type"] = kind.strip().lower()
        if "amount" in payload:
            try:
                amount = Decimal(str(payload["amount"]))
                if (
                    not amount.is_finite()
                    or amount <= 0
                    or amount.quantize(Decimal("0.01")) != amount
                    or amount * 100 > 9_223_372_036_854_775_807
                ):
                    raise InvalidOperation
                result["amount_cents"] = int(amount * 100)
            except (InvalidOperation, ValueError, TypeError):
                return None, "amount must be positive, fit the database, and have at most two decimal places."
        if "category" in payload:
            category = payload["category"]
            if not isinstance(category, str) or not category.strip() or len(category.strip()) > 80:
                return None, "category must be a non-empty string of at most 80 characters."
            result["category"] = category.strip()
        if "description" in payload:
            description = payload["description"]
            if not isinstance(description, str) or len(description.strip()) > 240:
                return None, "description must be a string of at most 240 characters."
            result["description"] = description.strip()
        if "date" in payload:
            date_value = payload["date"]
            try:
                result["date"] = parse_iso_date(date_value)
            except (TypeError, ValueError):
                return None, "date must use YYYY-MM-DD format."
        return result, None

    def serialize(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "type": row["type"],
            "amount": format_money(row["amount_cents"]),
            "category": row["category"],
            "description": row["description"],
            "date": row["date"],
            "created_at": row["created_at"],
        }

    @app.get("/health")
    def health():
        return jsonify(status="ok")

    @app.route("/api/transactions", methods=["GET", "POST"])
    def transactions():
        if request.method == "POST":
            payload, error = get_payload()
            if error:
                return error
            values, message = validate_payload(payload)
            if message:
                return bad_request(message)
            values.setdefault("description", "")
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            cursor = get_db().execute(
                "INSERT INTO transactions (type, amount_cents, category, description, date, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (values["type"], values["amount_cents"], values["category"], values["description"], values["date"], now),
            )
            get_db().commit()
            row = get_db().execute("SELECT * FROM transactions WHERE id = ?", (cursor.lastrowid,)).fetchone()
            response = jsonify(serialize(row))
            response.status_code = 201
            response.headers["Location"] = f"/api/transactions/{cursor.lastrowid}"
            return response

        query = "SELECT * FROM transactions WHERE 1 = 1"
        params: list[Any] = []
        kind = request.args.get("type")
        if kind:
            if kind not in {"income", "expense"}:
                return bad_request("type must be 'income' or 'expense'.")
            query += " AND type = ?"
            params.append(kind)
        category = request.args.get("category")
        if category:
            query += " AND category = ?"
            params.append(category.strip())
        for key, operator in (("start_date", ">="), ("end_date", "<=")):
            value = request.args.get(key)
            if value:
                try:
                    value = parse_iso_date(value)
                except ValueError:
                    return bad_request(f"{key} must use YYYY-MM-DD format.")
                query += f" AND date {operator} ?"
                params.append(value)
        try:
            limit = int(request.args.get("limit", "50"))
            offset = int(request.args.get("offset", "0"))
        except ValueError:
            return bad_request("limit and offset must be integers.")
        if not 1 <= limit <= 100 or offset < 0:
            return bad_request("limit must be 1–100 and offset must be non-negative.")
        query += " ORDER BY date DESC, id DESC LIMIT ? OFFSET ?"
        params.extend((limit, offset))
        rows = get_db().execute(query, params).fetchall()
        return jsonify(items=[serialize(row) for row in rows], limit=limit, offset=offset)

    @app.route("/api/transactions/<int:transaction_id>", methods=["GET", "PATCH", "DELETE"])
    def transaction_detail(transaction_id: int):
        connection = get_db()
        row = connection.execute("SELECT * FROM transactions WHERE id = ?", (transaction_id,)).fetchone()
        if row is None:
            return jsonify(error="Transaction not found."), 404
        if request.method == "GET":
            return jsonify(serialize(row))
        if request.method == "DELETE":
            connection.execute("DELETE FROM transactions WHERE id = ?", (transaction_id,))
            connection.commit()
            return "", 204

        payload, error = get_payload()
        if error:
            return error
        values, message = validate_payload(payload, partial=True)
        if message:
            return bad_request(message)
        columns = {"type": "type", "amount_cents": "amount_cents", "category": "category", "description": "description", "date": "date"}
        assignments = ", ".join(f"{columns[key]} = ?" for key in values)
        connection.execute(
            f"UPDATE transactions SET {assignments} WHERE id = ?",
            (*values.values(), transaction_id),
        )
        connection.commit()
        updated = connection.execute("SELECT * FROM transactions WHERE id = ?", (transaction_id,)).fetchone()
        return jsonify(serialize(updated))

    @app.get("/api/reports/monthly")
    def monthly_report():
        month = request.args.get("month", "")
        if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
            return bad_request("month is required and must use YYYY-MM format.")
        year, month_number = (int(part) for part in month.split("-"))
        if year == 9999 and month_number == 12:
            return bad_request("month is outside the supported date range.")
        start = date(year, month_number, 1)
        end = date(year + (month_number == 12), 1 if month_number == 12 else month_number + 1, 1)
        rows = get_db().execute(
            "SELECT type, category, SUM(amount_cents) AS total_cents FROM transactions WHERE date >= ? AND date < ? GROUP BY type, category ORDER BY type, category",
            (start.isoformat(), end.isoformat()),
        ).fetchall()
        totals = {"income": 0, "expense": 0}
        by_category = []
        for row in rows:
            totals[row["type"]] += row["total_cents"]
            by_category.append({
                "type": row["type"],
                "category": row["category"],
                "total": format_money(row["total_cents"]),
            })
        return jsonify(
            month=month,
            income_total=format_money(totals["income"]),
            expense_total=format_money(totals["expense"]),
            net_total=format_money(totals["income"] - totals["expense"]),
            by_category=by_category,
        )

    @app.errorhandler(404)
    def not_found(_error):
        return jsonify(error="Route not found."), 404

    return app


if __name__ == "__main__":
    create_app().run(debug=True)
