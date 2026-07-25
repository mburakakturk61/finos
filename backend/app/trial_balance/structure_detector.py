import re


SEPARATORS = (".", "-", "/", " ")


def account_is_parent(
    candidate_parent: str,
    candidate_child: str,
) -> bool:
    parent = candidate_parent.strip()
    child = candidate_child.strip()

    if not parent or not child or parent == child:
        return False

    for separator in SEPARATORS:
        if child.startswith(parent + separator):
            return True

    if (
        parent.isdigit()
        and child.isdigit()
        and len(child) > len(parent)
        and child.startswith(parent)
    ):
        return True

    return False


def detect_account_structure(
    account_codes: list[str],
) -> dict:
    unique_codes = sorted(
        {
            code.strip()
            for code in account_codes
            if code and code.strip()
        },
        key=lambda value: (len(value), value),
    )

    parent_codes: set[str] = set()

    for index, parent in enumerate(unique_codes):
        for child in unique_codes[index + 1:]:
            if account_is_parent(parent, child):
                parent_codes.add(parent)
                break

    leaf_codes = set(unique_codes) - parent_codes

    hierarchical = bool(parent_codes)

    return {
        "type": (
            "hierarchical_trial_balance"
            if hierarchical
            else "flat_trial_balance"
        ),
        "hierarchical": hierarchical,
        "parent_codes": parent_codes,
        "leaf_codes": leaf_codes,
        "parent_count": len(parent_codes),
        "leaf_count": len(leaf_codes),
    }


def is_total_row(
    account_code: str,
    account_name: str,
) -> bool:
    combined = f"{account_code} {account_name}".strip().lower()

    patterns = [
        r"\bgenel toplam\b",
        r"\btoplam\b",
        r"\bgrand total\b",
        r"\bsubtotal\b",
    ]

    return any(
        re.search(pattern, combined)
        for pattern in patterns
    )
