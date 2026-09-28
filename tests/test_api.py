import pytest

from app import create_app


@pytest.fixture
def client(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "test.sqlite3")})
    return app.test_client()


def make_transaction(client, **overrides):
    payload = {"type": "expense", "amount": "1250.00", "category": "Transport", "description": "Bus fare", "date": "2026-09-28"}
    payload.update(overrides)
    return client.post("/api/transactions", json=payload)


def test_health_check(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json == {"status": "ok"}


def test_create_read_and_list_transaction(client):
    created = make_transaction(client)
    assert created.status_code == 201
    assert created.json["amount"] == "1250.00"
    assert client.get(created.headers["Location"]).json["category"] == "Transport"
    assert len(client.get("/api/transactions?type=expense").json["items"]) == 1


@pytest.mark.parametrize("amount", ["0", "-1", "1.239", "not-money"])
def test_create_rejects_invalid_amounts(client, amount):
    response = make_transaction(client, amount=amount)
    assert response.status_code == 400
    assert "amount" in response.json["error"]


def test_filter_and_date_range(client):
    make_transaction(client, date="2026-09-01", category="Food")
    make_transaction(client, date="2026-09-15", category="Transport")
    result = client.get("/api/transactions?category=Transport&start_date=2026-09-10&end_date=2026-09-20")
    assert len(result.json["items"]) == 1
    assert result.json["items"][0]["category"] == "Transport"


def test_patch_updates_only_supplied_fields(client):
    created = make_transaction(client)
    updated = client.patch(created.headers["Location"], json={"description": "Train ticket"})
    assert updated.status_code == 200
    assert updated.json["description"] == "Train ticket"
    assert updated.json["amount"] == "1250.00"


def test_delete_and_missing_record(client):
    created = make_transaction(client)
    url = created.headers["Location"]
    assert client.delete(url).status_code == 204
    assert client.get(url).status_code == 404


def test_monthly_report_uses_cents_and_groups_categories(client):
    make_transaction(client, amount="2000.00", type="income", category="Sales")
    make_transaction(client, amount="500.50", type="expense", category="Food")
    report = client.get("/api/reports/monthly?month=2026-09")
    assert report.status_code == 200
    assert report.json["income_total"] == "2000.00"
    assert report.json["expense_total"] == "500.50"
    assert report.json["net_total"] == "1499.50"
    assert len(report.json["by_category"]) == 2


def test_report_requires_valid_month(client):
    assert client.get("/api/reports/monthly?month=2026-13").status_code == 400


def test_unknown_route_returns_json(client):
    response = client.get("/missing")
    assert response.status_code == 404
    assert "error" in response.json
