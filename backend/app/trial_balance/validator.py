from decimal import Decimal


BALANCE_TOLERANCE = Decimal("0.01")


def validate_balance(
    total_debit: Decimal,
    total_credit: Decimal,
) -> dict:
    difference = total_debit - total_credit
    balanced = abs(difference) <= BALANCE_TOLERANCE

    errors: list[str] = []

    if not balanced:
        errors.append(
            "Mizan dengede değil. "
            f"Borç-alacak farkı: {difference.quantize(Decimal('0.01'))}"
        )

    return {
        "balanced": balanced,
        "difference": difference,
        "errors": errors,
    }
