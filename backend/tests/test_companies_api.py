def test_create_company_success(client):
    payload = {
        "legal_name": "Örnek Ticaret A.Ş.",
        "trade_name": "Örnek A.Ş.",
        "tax_number": "1234567890",
        "tax_office": "Kadıköy",
        "sector": "Perakende",
        "nace_code": "4711",
        "currency": "TRY",
    }

    response = client.post("/api/v1/companies", json=payload)

    assert response.status_code == 201
    body = response.json()
    assert body["legal_name"] == payload["legal_name"]
    assert body["tax_number"] == payload["tax_number"]
    assert "id" in body
    assert "created_at" in body
    assert "updated_at" in body


def test_create_company_duplicate_tax_number_conflict(client):
    payload = {
        "legal_name": "A Firması",
        "tax_number": "1111111111",
        "currency": "TRY",
    }

    first = client.post("/api/v1/companies", json=payload)
    assert first.status_code == 201

    second = client.post(
        "/api/v1/companies",
        json={**payload, "legal_name": "B Firması"},
    )
    assert second.status_code == 409


def test_get_company_not_found(client):
    random_id = "00000000-0000-0000-0000-000000000000"

    response = client.get(f"/api/v1/companies/{random_id}")

    assert response.status_code == 404


def test_get_company_success(client):
    payload = {
        "legal_name": "C Firması",
        "tax_number": "2222222222",
        "currency": "TRY",
    }
    created = client.post("/api/v1/companies", json=payload).json()

    response = client.get(f"/api/v1/companies/{created['id']}")

    assert response.status_code == 200
    assert response.json()["id"] == created["id"]


def test_list_companies_pagination(client):
    for index in range(5):
        client.post(
            "/api/v1/companies",
            json={
                "legal_name": f"Firma {index}",
                "tax_number": f"300000000{index}",
                "currency": "TRY",
            },
        )

    first_page = client.get(
        "/api/v1/companies",
        params={"limit": 2, "offset": 0},
    )
    assert first_page.status_code == 200
    first_body = first_page.json()
    assert first_body["total"] == 5
    assert first_body["limit"] == 2
    assert first_body["offset"] == 0
    assert len(first_body["items"]) == 2

    last_page = client.get(
        "/api/v1/companies",
        params={"limit": 2, "offset": 4},
    )
    assert len(last_page.json()["items"]) == 1
