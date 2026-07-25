"""
Türkiye Vergi Kimlik Numarası (VKN) checksum doğrulaması.

ÖNEMLİ: Bu yalnızca bir GÜVEN SİNYALİDİR. Checksum'dan geçmeyen bir VKN
sessizce atılmaz/null'lanmaz -- CompanyIdentityResolver, checksum
başarısız olsa bile tespit edilen değeri döndürür, yalnızca o bileşenin
confidence'ını düşürür ve bir warning ekler (bkz.
company_identity_resolver.py).
"""

import re


VKN_PATTERN = re.compile(r"\b\d{10}\b")


def is_well_formed_vkn(candidate: str) -> bool:
    """10 haneli, yalnızca rakamlardan oluşan bir aday mı?"""

    return bool(re.fullmatch(r"\d{10}", candidate))


def is_valid_vkn(candidate: str) -> bool:
    """
    Standart VKN checksum algoritması. 10 haneli olmayan veya rakam
    olmayan girdilerde False döner (exception fırlatmaz).
    """

    if not is_well_formed_vkn(candidate):
        return False

    digits = [int(character) for character in candidate]
    total = 0

    for index in range(9):
        tmp = (digits[index] + 9 - index) % 10
        if tmp != 0:
            tmp = (tmp * (2 ** (9 - index))) % 9
            if tmp == 0:
                tmp = 9
        total += tmp

    check_digit = (10 - (total % 10)) % 10
    return check_digit == digits[9]


def find_candidate_vkns(text: str) -> list[str]:
    """Metindeki tüm 10 haneli, bağımsız (başka rakamlara bitişik olmayan)
    sayı dizilerini döndürür -- sıra korunur, tekrarlar elenir."""

    seen: list[str] = []
    for match in VKN_PATTERN.finditer(text):
        candidate = match.group()
        if candidate not in seen:
            seen.append(candidate)
    return seen
