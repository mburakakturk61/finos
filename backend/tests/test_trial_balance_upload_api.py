"""
POST /api/v1/periods/{period_id}/trial-balances ve okuma endpointleri için
SQLite tabanlı API testleri (Milestone 2 / Adım 2).

Hiçbir testte gerçek tests/data/generic/2024_detay_mizan.xlsx fixture'ı
KULLANILMAZ -- tüm dosyalar bellek içinde, kurgusal veriyle üretilir.
"""

import io

import pandas as pd


def _synthetic_balanced_xlsx(seed: int = 0) -> bytes:
    """Denk (debit == credit), tamamen kurgusal, geçerli bir mizan."""

    debit = 50000 + seed
    rows = [
        {"Hesap Kodu": "100", "Hesap Adı": "KASA", "Borç Tutarı": debit, "Alacak Tutarı": 0},
        {"Hesap Kodu": "320", "Hesap Adı": "SATICILAR", "Borç Tutarı": 0, "Alacak Tutarı": debit},
    ]
    dataframe = pd.DataFrame(rows)
    buffer = io.BytesIO()
    dataframe.to_excel(buffer, index=False, engine="openpyxl")
    buffer.seek(0)
    return buffer.read()


def _synthetic_missing_columns_xlsx() -> bytes:
    """Zorunlu 'Alacak Tutarı' kolonu eksik -- motor exception fırlatmaz,
    normal biçimde status='INVALID' döner."""

    rows = [{"Hesap Kodu": "100", "Hesap Adı": "KASA", "Borç Tutarı": 50000}]
    dataframe = pd.DataFrame(rows)
    buffer = io.BytesIO()
    dataframe.to_excel(buffer, index=False, engine="openpyxl")
    buffer.seek(0)
    return buffer.read()


def _synthetic_empty_dataframe_xlsx() -> bytes:
    """Yalnızca başlık satırı, hiç veri satırı yok -- motor ValueError fırlatır."""

    dataframe = pd.DataFrame(
        columns=["Hesap Kodu", "Hesap Adı", "Borç Tutarı", "Alacak Tutarı"]
    )
    buffer = io.BytesIO()
    dataframe.to_excel(buffer, index=False, engine="openpyxl")
    buffer.seek(0)
    return buffer.read()


CORRUPT_BYTES = b"bu gecerli bir xlsx dosyasi degil, sadece rastgele byte'lar"

XLSX_MIME = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)


def _create_company_and_period(client, tax_number_suffix: str = "0001"):
    company = client.post(
        "/api/v1/companies",
        json={
            "legal_name": "Upload Test A.Ş.",
            "tax_number": f"UPLD-{tax_number_suffix}",
            "currency": "TRY",
        },
    ).json()

    period = client.post(
        f"/api/v1/companies/{company['id']}/periods",
        json={
            "year": 2024,
            "period_type": "year_end",
            "period_number": 4,
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
            "months_covered": 12,
            "is_year_end": True,
        },
    ).json()

    return company, period


def _upload(client, period_id, content, filename="mizan.xlsx", mime=XLSX_MIME):
    return client.post(
        f"/api/v1/periods/{period_id}/trial-balances",
        files={"file": (filename, content, mime)},
    )


# --- POST /periods/{period_id}/trial-balances --------------------------


def test_upload_trial_balance_success(client):
    _, period = _create_company_and_period(client, "0001")
    content = _synthetic_balanced_xlsx(seed=0)

    response = _upload(client, period["id"], content)

    assert response.status_code == 201
    body = response.json()
    assert body["document"]["period_id"] == period["id"]
    assert body["document"]["document_type"] == "trial_balance"
    assert body["document"]["processing_status"] == "completed"
    assert body["document"]["error_message"] is None
    assert body["analysis"]["status"] == "completed"
    assert body["analysis"]["analysis_type"] == "trial_balance"
    assert body["analysis"]["result_json"]["status"] == "VALID"
    assert body["analysis"]["result_json"]["totals"]["balanced"] is True


def test_upload_trial_balance_period_not_found(client):
    random_id = "00000000-0000-0000-0000-000000000000"
    content = _synthetic_balanced_xlsx()

    response = _upload(client, random_id, content)

    assert response.status_code == 404


def test_upload_trial_balance_wrong_extension_returns_400(client):
    _, period = _create_company_and_period(client, "0002")

    response = _upload(
        client, period["id"], b"a,b,c", filename="mizan.csv", mime="text/csv"
    )

    assert response.status_code == 400


def test_upload_trial_balance_duplicate_checksum_same_period_409(client):
    _, period = _create_company_and_period(client, "0003")
    content = _synthetic_balanced_xlsx(seed=3)

    first = _upload(client, period["id"], content)
    assert first.status_code == 201

    second = _upload(client, period["id"], content, filename="mizan_v2.xlsx")
    assert second.status_code == 409


def test_upload_trial_balance_same_checksum_different_period_allowed(client):
    company, period_a = _create_company_and_period(client, "0004")
    period_b = client.post(
        f"/api/v1/companies/{company['id']}/periods",
        json={
            "year": 2025,
            "period_type": "year_end",
            "period_number": 4,
            "start_date": "2025-01-01",
            "end_date": "2025-12-31",
            "months_covered": 12,
            "is_year_end": True,
        },
    ).json()

    content = _synthetic_balanced_xlsx(seed=4)

    first = _upload(client, period_a["id"], content)
    assert first.status_code == 201

    second = _upload(client, period_b["id"], content)
    assert second.status_code == 201


def test_upload_trial_balance_corrupt_file_returns_422_with_safe_message(client):
    _, period = _create_company_and_period(client, "0005")

    response = _upload(
        client,
        period["id"],
        CORRUPT_BYTES,
        filename="bozuk.xlsx",
        mime="application/octet-stream",
    )

    assert response.status_code == 422
    assert response.json()["detail"] == (
        "Excel dosyası okunamadı veya ayrıştırılamadı. Dosya bozuk ya da "
        "beklenen mizan formatında olmayabilir."
    )


def test_upload_trial_balance_empty_dataframe_returns_422(client):
    _, period = _create_company_and_period(client, "0006")
    content = _synthetic_empty_dataframe_xlsx()

    response = _upload(client, period["id"], content, filename="bos.xlsx")

    assert response.status_code == 422


def test_upload_trial_balance_invalid_result_is_still_201(client):
    """Motorun kendi iş kuralı gereği ürettiği status='INVALID' bir
    exception DEĞİLDİR -- işlem başarıyla tamamlanmıştır (201)."""

    _, period = _create_company_and_period(client, "0007")
    content = _synthetic_missing_columns_xlsx()

    response = _upload(client, period["id"], content, filename="eksik.xlsx")

    assert response.status_code == 201
    body = response.json()
    assert body["document"]["processing_status"] == "completed"
    assert body["analysis"]["status"] == "completed"
    assert body["analysis"]["result_json"]["status"] == "INVALID"


# --- Okuma endpointleri --------------------------------------------------


def test_list_period_documents_pagination(client):
    _, period = _create_company_and_period(client, "0008")

    for seed in range(3):
        content = _synthetic_balanced_xlsx(seed=100 + seed)
        response = _upload(client, period["id"], content, filename=f"m{seed}.xlsx")
        assert response.status_code == 201

    response = client.get(
        f"/api/v1/periods/{period['id']}/documents",
        params={"limit": 2, "offset": 0},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert len(body["items"]) == 2


def test_list_period_documents_period_not_found(client):
    random_id = "00000000-0000-0000-0000-000000000000"
    response = client.get(f"/api/v1/periods/{random_id}/documents")
    assert response.status_code == 404


def test_get_document_not_found(client):
    random_id = "00000000-0000-0000-0000-000000000000"
    response = client.get(f"/api/v1/documents/{random_id}")
    assert response.status_code == 404


def test_get_document_success(client):
    _, period = _create_company_and_period(client, "0009")
    content = _synthetic_balanced_xlsx(seed=200)
    upload = _upload(client, period["id"], content).json()

    response = client.get(f"/api/v1/documents/{upload['document']['id']}")

    assert response.status_code == 200
    assert response.json()["id"] == upload["document"]["id"]


def test_list_document_analyses_summary_excludes_result_json(client):
    _, period = _create_company_and_period(client, "0010")
    content = _synthetic_balanced_xlsx(seed=201)
    upload = _upload(client, period["id"], content).json()

    response = client.get(
        f"/api/v1/documents/{upload['document']['id']}/analyses"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert "result_json" not in body["items"][0]


def test_list_document_analyses_document_not_found(client):
    random_id = "00000000-0000-0000-0000-000000000000"
    response = client.get(f"/api/v1/documents/{random_id}/analyses")
    assert response.status_code == 404


def test_get_analysis_detail_includes_result_json(client):
    _, period = _create_company_and_period(client, "0011")
    content = _synthetic_balanced_xlsx(seed=202)
    upload = _upload(client, period["id"], content).json()

    response = client.get(f"/api/v1/analyses/{upload['analysis']['id']}")

    assert response.status_code == 200
    body = response.json()
    assert "result_json" in body
    assert body["result_json"]["status"] == "VALID"


def test_get_analysis_not_found(client):
    random_id = "00000000-0000-0000-0000-000000000000"
    response = client.get(f"/api/v1/analyses/{random_id}")
    assert response.status_code == 404
