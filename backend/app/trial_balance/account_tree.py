from app.trial_balance.models import TrialBalanceAccount


SEPARATORS = (".", "-", "/", " ")


def detect_level(account_code: str) -> int:
    for separator in SEPARATORS:
        if separator in account_code:
            return len(
                [
                    part
                    for part in account_code.split(separator)
                    if part
                ]
            )

    return 1


def detect_parent_code(
    account_code: str,
    available_codes: set[str],
) -> str | None:
    candidates = [
        code
        for code in available_codes
        if code != account_code
        and (
            account_code.startswith(code + ".")
            or account_code.startswith(code + "-")
            or account_code.startswith(code + "/")
            or account_code.startswith(code + " ")
        )
    ]

    if not candidates:
        return None

    return max(candidates, key=len)


def build_account_tree(
    rows: list[dict],
    parent_codes: set[str],
    leaf_codes: set[str],
) -> list[TrialBalanceAccount]:
    available_codes = {
        row["account_code"]
        for row in rows
        if row["account_code"]
    }

    accounts: list[TrialBalanceAccount] = []

    for row in rows:
        account_code = row["account_code"]
        debit = row["debit"]
        credit = row["credit"]

        accounts.append(
            TrialBalanceAccount(
                row_number=row["row_number"],
                account_code=account_code,
                account_name=row["account_name"],
                debit=debit,
                credit=credit,
                balance=debit - credit,
                level=detect_level(account_code),
                parent_code=detect_parent_code(
                    account_code,
                    available_codes,
                ),
                is_leaf=account_code in leaf_codes,
                is_summary=account_code in parent_codes,
            )
        )

    return accounts