"""
Milestone 4.2: iki-seviyeli reconciliation (mutabakat) karşılaştırması
(onaylanan Milestone 4.2 kararı #2). `direct_document` ile aynı dönemin
`trial_balance` sonucu arasındaki farkı DEĞERLENDİRİR ama hiçbir zaman
otomatik olarak "düzeltmez" -- `direct_document` HER ZAMAN authoritative
kalır; `trial_balance` değeri asla sessizce üzerine yazmaz.

İki seviye:
  A) Rounding tolerance -- max(1.00, |referans| * %0.01). Bu sınırın
     ALTINDAKİ fark hiçbir warning üretmez (yuvarlama farkı sayılır).
  B) Material difference threshold -- max(100.00, |referans| * %0.5).
     Rounding tolerance'ın ÜSTÜNDE ama bu eşiğin ALTINDA:
     severity="warning", code=RECONCILIATION_DIFFERENCE. Bu eşiğin
     ÜSTÜNDE: severity="high", code=MATERIAL_RECONCILIATION_DIFFERENCE.

Referans değer 0 ise yüzde hesaplanmaz (yalnızca mutlak fark
değerlendirilir) -- sıfıra bölme veya sonsuz oran ASLA üretilmez.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.engines.common.ratio_formulas import decimal_to_json_safe


ROUNDING_TOLERANCE_ABS = Decimal("1.00")
ROUNDING_TOLERANCE_REL = Decimal("0.0001")  # referans değerin %0.01'i

MATERIAL_THRESHOLD_ABS = Decimal("100.00")
MATERIAL_THRESHOLD_REL = Decimal("0.005")  # referans değerin %0.5'i

RECONCILIATION_DIFFERENCE = "RECONCILIATION_DIFFERENCE"
MATERIAL_RECONCILIATION_DIFFERENCE = "MATERIAL_RECONCILIATION_DIFFERENCE"


@dataclass(frozen=True)
class ReconciliationFinding:
    compared_field: str
    direct_value: Decimal
    reference_value: Decimal
    absolute_difference: Decimal
    percentage_difference: Decimal | None
    applied_rounding_tolerance: Decimal
    applied_material_threshold: Decimal
    severity: str  # "warning" | "high"
    code: str


def compare_with_tolerance(
    *,
    compared_field: str,
    direct_value: Decimal | None,
    reference_value: Decimal | None,
) -> ReconciliationFinding | None:
    """
    `direct_value`/`reference_value` ikisi de doluysa karşılaştırır. Biri
    `None` ise karşılaştırma YAPILMAZ (`None` döner) -- eksik veri
    fabrikasyon edilmez. Fark rounding tolerance'ın altındaysa da `None`
    döner (yuvarlama farkı, warning değil).
    """

    if direct_value is None or reference_value is None:
        return None

    absolute_difference = abs(direct_value - reference_value)

    rounding_tolerance = max(
        ROUNDING_TOLERANCE_ABS, abs(reference_value) * ROUNDING_TOLERANCE_REL
    )
    material_threshold = max(
        MATERIAL_THRESHOLD_ABS, abs(reference_value) * MATERIAL_THRESHOLD_REL
    )

    if absolute_difference <= rounding_tolerance:
        return None

    if reference_value == 0:
        percentage_difference = None
    else:
        percentage_difference = (
            absolute_difference / abs(reference_value)
        ) * Decimal("100")

    if absolute_difference > material_threshold:
        severity = "high"
        code = MATERIAL_RECONCILIATION_DIFFERENCE
    else:
        severity = "warning"
        code = RECONCILIATION_DIFFERENCE

    return ReconciliationFinding(
        compared_field=compared_field,
        direct_value=direct_value,
        reference_value=reference_value,
        absolute_difference=absolute_difference,
        percentage_difference=percentage_difference,
        applied_rounding_tolerance=rounding_tolerance,
        applied_material_threshold=material_threshold,
        severity=severity,
        code=code,
    )


def finding_to_dict(finding: ReconciliationFinding) -> dict:
    return {
        "code": finding.code,
        "severity": finding.severity,
        "compared_field": finding.compared_field,
        "direct_value": decimal_to_json_safe(finding.direct_value),
        "reference_value": decimal_to_json_safe(finding.reference_value),
        "absolute_difference": decimal_to_json_safe(finding.absolute_difference),
        "percentage_difference": decimal_to_json_safe(finding.percentage_difference),
        "applied_rounding_tolerance": decimal_to_json_safe(finding.applied_rounding_tolerance),
        "applied_material_threshold": decimal_to_json_safe(finding.applied_material_threshold),
        "message": (
            f"'{finding.compared_field}' alanında doğrudan belge ile mizandan "
            f"türetilen değer arasında {finding.severity} seviyeli fark var."
        ),
    }


def build_reconciliation_summary(
    *,
    performed: bool,
    compared_against: str | None,
    findings: list[ReconciliationFinding],
) -> dict[str, Any]:
    """
    `result_json["reconciliation"]` sözleşmesinin TEK üretim noktası --
    hem Balance Sheet hem Income Statement motoru bunu kullanır (kullanıcı
    geri bildirimiyle netleştirilen özet sözleşme):

      - performed=False: karşılaştırılacak İKİNCİ bir kaynak (trial_balance)
        hiç YOKTU (ya doğrudan belge tek başına, ya trial_balance fallback
        TEK kaynak olarak kullanıldı -- bu bir karşılaştırma DEĞİL). Bu
        durumda within_tolerance/material_difference `None` (bilinmiyor,
        `False` DEĞİL -- "karşılaştırma hiç yapılmadı" ile "karşılaştırıldı
        ve fark yok" birbirine KARIŞTIRILMAZ), differences=[].
      - performed=True: iki kaynak karşılaştırıldı. within_tolerance,
        rounding tolerance'ın üstünde hiçbir fark yoksa `True`.
        material_difference yalnızca en az bir `high` severity'li (bkz.
        MATERIAL_RECONCILIATION_DIFFERENCE) fark varsa `True`; performed=True
        iken asla `None` değil, her zaman somut bir `bool`.
    """

    if not performed:
        return {
            "compared_against": None,
            "performed": False,
            "within_tolerance": None,
            "material_difference": None,
            "differences": [],
        }

    material_difference = any(f.code == MATERIAL_RECONCILIATION_DIFFERENCE for f in findings)

    return {
        "compared_against": compared_against,
        "performed": True,
        "within_tolerance": len(findings) == 0,
        "material_difference": material_difference,
        "differences": [finding_to_dict(f) for f in findings],
    }
