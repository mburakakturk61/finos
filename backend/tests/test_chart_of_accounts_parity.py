"""
app.engines.common.chart_of_accounts içindeki BAĞIMSIZ Tekdüzen Hesap Planı
kopyasının, app.trial_balance.financial_statements içindeki ORİJİNAL tanımla
birebir eşit kaldığını doğrular (Milestone 4.1 -- Analysis Foundation,
onaylanan karar #4: "eşleme kopyalanıyorsa drift riskine karşı
parity/regression testleri yazılmalı").

Bu test dosyası app.trial_balance.financial_statements'ı SALT-OKUNUR olarak
import eder -- bu bir PRODUCTION kod bağımlılığı DEĞİLDİR
(app/engines/common/chart_of_accounts.py bu modülden hiçbir şey import
etmiyor, bkz. o dosyanın docstring'i); yalnızca bu TEST, iki bağımsız
tanımın drift etmediğini kanıtlamak için ikisini de okuyor.
app/trial_balance/**'e bu dosyada da hiçbir yazma/değişiklik yapılmadı.

Bu dosya yalnızca stdlib'e bağımlıdır (sqlalchemy/fastapi/pydantic'e DEĞİL).
"""

from app.engines.common import chart_of_accounts
from app.trial_balance import financial_statements as trial_balance_financial_statements


def test_balance_sheet_sections_are_identical():
    assert (
        chart_of_accounts.BALANCE_SHEET_SECTIONS
        == trial_balance_financial_statements.BALANCE_SHEET_SECTIONS
    )


def test_income_statement_sections_are_identical():
    assert (
        chart_of_accounts.INCOME_STATEMENT_SECTIONS
        == trial_balance_financial_statements.INCOME_STATEMENT_SECTIONS
    )


def test_get_numeric_prefix_behaves_identically():
    samples = [
        "120", "120.01", "120-01", "120/01", "120 01",
        "600.01.01", "", "abc", "1a2b3", "69",
    ]
    for sample in samples:
        assert chart_of_accounts.get_numeric_prefix(
            sample
        ) == trial_balance_financial_statements.get_numeric_prefix(sample), sample


def test_balance_sheet_classification_matches_for_sample_codes():
    # 999 -> tanınmayan sınıf (6 diye bir BALANCE_SHEET_SECTIONS anahtarı
    # yok), her iki tarafta da None üretmeli -- fabrikasyon yok.
    samples = ["100", "120.01", "153", "254", "300", "320.05", "400", "421", "500", "540", "999"]
    for code in samples:
        prefix = chart_of_accounts.get_numeric_prefix(code)
        expected = (
            trial_balance_financial_statements.BALANCE_SHEET_SECTIONS.get(prefix[0])
            if prefix
            else None
        )
        assert chart_of_accounts.classify_balance_sheet_section(code) == expected, code


def test_income_statement_classification_matches_for_sample_codes():
    # 700 -> 70 diye bir INCOME_STATEMENT_SECTIONS anahtarı yok (yalnızca
    # 60-69 tanımlı), None beklenir.
    samples = [
        "600", "600.01", "610", "621", "631", "641", "651", "660",
        "670", "681", "690", "700",
    ]
    for code in samples:
        prefix = chart_of_accounts.get_numeric_prefix(code)
        expected = (
            trial_balance_financial_statements.INCOME_STATEMENT_SECTIONS.get(prefix[:2])
            if len(prefix) >= 2
            else None
        )
        assert chart_of_accounts.classify_income_statement_section(code) == expected, code
