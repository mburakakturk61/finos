"""
Milestone 4.1 (Analysis Foundation): Türk Tekdüzen Hesap Planı sınıf-öneki
eşlemesi.

BİLİNÇLİ OLARAK app/trial_balance/financial_statements.py içindeki AYNI
eşlemenin BAĞIMSIZ bir kopyasıdır -- oradan import EDİLMEZ ve app/trial_balance/**
paketine bu milestone'da (ve bu adımda) hiçbir şekilde dokunulmaz/bağımlılık
kurulmaz (Milestone 4 mimari kararı B.5, onaylanan karar #4).

Neden kopya, neden import değil: app/trial_balance/**'e "asla dokunma"
kuralının ruhu yalnızca yazmayı değil, ondan kırılgan/gizli bir bağımlılık
kurmayı da kapsıyor -- trial_balance içindeki bir sabitin şekli ileride
(başka bir nedenle) değişirse, ondan import eden motorlar sessizce
kırılabilir. Bu ~20 satırlık sabit sözlüğün küçük bir kopyası, bu riske
karşı ucuz bir sigorta.

Drift riski (iki kopyanın zamanla birbirinden sapması) BİLİNÇLİ OLARAK kabul
edildi ve tests/test_chart_of_accounts_parity.py ile her test koşusunda
otomatik doğrulanıyor -- bu iki tanım birbirinden SAPARSA o test kırılır.
"""

BALANCE_SHEET_SECTIONS: dict[str, str] = {
    "1": "current_assets",
    "2": "non_current_assets",
    "3": "short_term_liabilities",
    "4": "long_term_liabilities",
    "5": "equity",
}


INCOME_STATEMENT_SECTIONS: dict[str, str] = {
    "60": "gross_sales",
    "61": "sales_deductions",
    "62": "cost_of_sales",
    "63": "operating_expenses",
    "64": "other_operating_income",
    "65": "other_operating_expenses",
    "66": "financing_expenses",
    "67": "extraordinary_income",
    "68": "extraordinary_expenses",
    "69": "period_profit_loss_accounts",
}


def get_numeric_prefix(account_code: str) -> str:
    """Bir hesap kodundaki yalnızca rakamları, sırasıyla, birleştirip döner
    (ör. '120.01' -> '12001', '6.00.01' -> '60001'). app/trial_balance/
    financial_statements.py::get_numeric_prefix ile AYNI mantık -- bağımsız
    kopya (bkz. modül docstring'i)."""

    return "".join(character for character in account_code if character.isdigit())


def classify_balance_sheet_section(account_code: str) -> str | None:
    """Hesap kodunun ilk rakamına göre bilanço bölümünü döner (ör. '120...' ->
    'current_assets'). Eşleşme yoksa None -- eksik/tanınmayan sınıflandırma
    asla bir bölüme fabrikasyon edilerek atanmaz."""

    prefix = get_numeric_prefix(account_code)
    if not prefix:
        return None
    return BALANCE_SHEET_SECTIONS.get(prefix[0])


def classify_income_statement_section(account_code: str) -> str | None:
    """Hesap kodunun ilk iki rakamına göre gelir tablosu bölümünü döner (ör.
    '600...' -> 'gross_sales'). Eşleşme yoksa None."""

    prefix = get_numeric_prefix(account_code)
    if len(prefix) < 2:
        return None
    return INCOME_STATEMENT_SECTIONS.get(prefix[:2])
