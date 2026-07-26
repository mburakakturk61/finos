"""
Milestone 4.3C (Benchmark Engine) / Adım 2: `app/engines/common/
company_size_classifier.py` için birim testleri.
"""

from decimal import Decimal

from app.engines.common.company_size_classifier import (
    DISCLAIMER,
    VALID_COMPANY_SIZE_BUCKETS,
    classify_company_size,
)


def test_both_none_returns_not_calculable_no_fabrication():
    result = classify_company_size(None, None)
    assert result.bucket is None
    assert result.reliability == "not_calculable"
    assert result.employee_count_available is False


def test_micro_bucket():
    result = classify_company_size(Decimal("5000000"), Decimal("3000000"))
    assert result.bucket == "micro"


def test_small_bucket():
    result = classify_company_size(Decimal("50000000"), Decimal("20000000"))
    assert result.bucket == "small"


def test_medium_bucket():
    result = classify_company_size(Decimal("200000000"), Decimal("150000000"))
    assert result.bucket == "medium"


def test_large_bucket():
    result = classify_company_size(Decimal("900000000"), Decimal("700000000"))
    assert result.bucket == "large"


def test_boundary_exactly_at_threshold_goes_to_next_bucket():
    # indicator < threshold kurali -- esitlikte bir SONRAKI bucket'a duser.
    result = classify_company_size(Decimal("10000000"), None)
    assert result.bucket == "small"


def test_uses_larger_of_the_two_indicators():
    result = classify_company_size(Decimal("5000000"), Decimal("900000000"))
    assert result.bucket == "large"


def test_only_net_sales_available():
    result = classify_company_size(Decimal("50000000"), None)
    assert result.bucket == "small"
    assert result.reliability == "medium"


def test_only_total_assets_available():
    result = classify_company_size(None, Decimal("600000000"))
    assert result.bucket == "large"


def test_reliability_never_high():
    for net_sales, total_assets in (
        (Decimal("1"), None),
        (None, Decimal("1")),
        (Decimal("1000000000"), Decimal("1000000000")),
        (Decimal("0"), Decimal("0")),
    ):
        result = classify_company_size(net_sales, total_assets)
        assert result.reliability != "high"


def test_employee_count_availability_always_explicit_false():
    result = classify_company_size(Decimal("1"), Decimal("1"))
    assert result.employee_count_available is False


def test_not_presented_as_official_sme_classification():
    result = classify_company_size(Decimal("1"), Decimal("1"))
    assert result.is_official_sme_classification is False
    assert "resmi" in result.disclaimer.lower() or "KOBİ" in result.disclaimer


def test_disclaimer_constant_mentions_employee_count_gap():
    assert "çalışan sayısı" in DISCLAIMER


def test_valid_buckets_tuple_has_four_entries_in_order():
    assert VALID_COMPANY_SIZE_BUCKETS == ("micro", "small", "medium", "large")


def test_zero_values_not_confused_with_none():
    # Decimal("0") GERCEK bir deger -- None (eksik) ile karistirilmamali;
    # sinif hesaplanmalidir (micro), not_calculable DEGIL.
    result = classify_company_size(Decimal("0"), Decimal("0"))
    assert result.bucket == "micro"
    assert result.reliability == "medium"
