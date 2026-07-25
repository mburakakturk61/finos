def _create_company(client, tax_number="9999999999"):
    payload = {
        "legal_name": "Test Firma",
        "tax_number": tax_number,
        "currency": "TRY",
    }
    response = client.post("/api/v1/companies", json=payload)
    assert response.status_code == 201
    return response.json()


def test_create_period_success(client):
    company = _create_company(client)

    payload = {
        "year": 2024,
        "period_type": "year_end",
        "period_number": 4,
        "start_date": "2024-01-01",
        "end_date": "2024-12-31",
        "months_covered": 12,
        "is_year_end": True,
        "status": "draft",
    }

    response = client.post(
        f"/api/v1/companies/{company['id']}/periods",
        json=payload,
    )

    assert response.status_code == 201
    body = response.json()
    assert body["company_id"] == company["id"]
    assert body["year"] == 2024
    assert body["period_type"] == "year_end"


def test_create_period_company_not_found(client):
    random_id = "00000000-0000-0000-0000-000000000000"
    payload = {
        "year": 2024,
        "period_type": "year_end",
        "period_number": 4,
        "start_date": "2024-01-01",
        "end_date": "2024-12-31",
        "months_covered": 12,
    }

    response = client.post(
        f"/api/v1/companies/{random_id}/periods",
        json=payload,
    )

    assert response.status_code == 404


def test_create_period_duplicate_conflict(client):
    company = _create_company(client, tax_number="8888888888")
    payload = {
        "year": 2024,
        "period_type": "year_end",
        "period_number": 4,
        "start_date": "2024-01-01",
        "end_date": "2024-12-31",
        "months_covered": 12,
    }

    first = client.post(
        f"/api/v1/companies/{company['id']}/periods",
        json=payload,
    )
    assert first.status_code == 201

    second = client.post(
        f"/api/v1/companies/{company['id']}/periods",
        json=payload,
    )
    assert second.status_code == 409


def test_create_period_invalid_date_range_rejected(client):
    company = _create_company(client, tax_number="7777777777")
    payload = {
        "year": 2024,
        "period_type": "year_end",
        "period_number": 4,
        "start_date": "2024-12-31",
        "end_date": "2024-01-01",
        "months_covered": 12,
    }

    response = client.post(
        f"/api/v1/companies/{company['id']}/periods",
        json=payload,
    )

    assert response.status_code == 422


def test_get_period_not_found(client):
    random_id = "00000000-0000-0000-0000-000000000000"

    response = client.get(f"/api/v1/periods/{random_id}")

    assert response.status_code == 404


def test_list_periods_for_company(client):
    company = _create_company(client, tax_number="6666666666")

    for period_number in range(1, 4):
        client.post(
            f"/api/v1/companies/{company['id']}/periods",
            json={
                "year": 2024,
                "period_type": "quarter",
                "period_number": period_number,
                "start_date": "2024-01-01",
                "end_date": "2024-03-31",
                "months_covered": 3,
            },
        )

    response = client.get(f"/api/v1/companies/{company['id']}/periods")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert len(body["items"]) == 3


def test_get_period_success(client):
    company = _create_company(client, tax_number="5555555555")
    created = client.post(
        f"/api/v1/companies/{company['id']}/periods",
        json={
            "year": 2025,
            "period_type": "temporary_tax",
            "period_number": 1,
            "start_date": "2025-01-01",
            "end_date": "2025-03-31",
            "months_covered": 3,
        },
    ).json()

    response = client.get(f"/api/v1/periods/{created['id']}")

    assert response.status_code == 200
    assert response.json()["id"] == created["id"]
