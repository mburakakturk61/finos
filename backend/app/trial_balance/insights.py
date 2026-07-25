from typing import Any


def add_insight(
    insights: list[dict[str, Any]],
    *,
    code: str,
    title: str,
    message: str,
    severity: str,
    category: str,
    metric: str | None = None,
    value: float | None = None,
    threshold: float | None = None,
    confidence: str = "high",
) -> None:
    insights.append(
        {
            "code": code,
            "title": title,
            "message": message,
            "severity": severity,
            "category": category,
            "metric": metric,
            "value": value,
            "threshold": threshold,
            "confidence": confidence,
        }
    )


def build_insights(
    financial_statements: dict[str, Any],
    financial_ratios: dict[str, Any],
) -> dict[str, Any]:
    insights: list[dict[str, Any]] = []
    missing_data: list[str] = []

    liquidity = financial_ratios["liquidity"]
    leverage = financial_ratios["leverage"]
    profitability = financial_ratios["profitability"]
    coverage = financial_ratios["coverage"]
    data_quality = financial_ratios["data_quality"]

    current_ratio = liquidity["current_ratio"]
    net_working_capital = liquidity["net_working_capital"]

    debt_to_equity = leverage["debt_to_equity"]
    debt_ratio = leverage["debt_ratio"]
    equity_ratio = leverage["equity_ratio"]
    short_term_debt_ratio = leverage["short_term_debt_ratio"]

    financing_expense_coverage = coverage[
        "financing_expense_coverage"
    ]

    if current_ratio is None:
        missing_data.append(
            "Cari oran hesaplanamadı; kısa vadeli yükümlülük verisi sıfır veya eksik."
        )
    elif current_ratio < 1:
        add_insight(
            insights,
            code="LIQUIDITY_CRITICAL",
            title="Kısa vadeli likidite baskısı",
            message=(
                "Cari oran 1,00 seviyesinin altında. "
                "Dönen varlıklar kısa vadeli yükümlülükleri karşılamıyor."
            ),
            severity="critical",
            category="liquidity",
            metric="current_ratio",
            value=current_ratio,
            threshold=1.0,
        )
    elif current_ratio < 1.5:
        add_insight(
            insights,
            code="LIQUIDITY_WATCH",
            title="Likidite yakından izlenmeli",
            message=(
                "Cari oran kabul edilebilir alt banda yakın. "
                "Tahsilat ve kısa vadeli borç vadesi dikkatle yönetilmeli."
            ),
            severity="warning",
            category="liquidity",
            metric="current_ratio",
            value=current_ratio,
            threshold=1.5,
        )
    else:
        add_insight(
            insights,
            code="LIQUIDITY_POSITIVE",
            title="Pozitif kısa vadeli ödeme kapasitesi",
            message=(
                "Cari oran 1,50 seviyesinin üzerinde. "
                "Şirketin kısa vadeli yükümlülüklerini karşılama kapasitesi olumludur."
            ),
            severity="positive",
            category="liquidity",
            metric="current_ratio",
            value=current_ratio,
            threshold=1.5,
        )

    if net_working_capital < 0:
        add_insight(
            insights,
            code="NWC_NEGATIVE",
            title="Negatif net işletme sermayesi",
            message=(
                "Dönen varlıklar kısa vadeli yükümlülüklerden düşüktür. "
                "İşletme sermayesi açığı bulunmaktadır."
            ),
            severity="critical",
            category="liquidity",
            metric="net_working_capital",
            value=net_working_capital,
            threshold=0,
        )
    else:
        add_insight(
            insights,
            code="NWC_POSITIVE",
            title="Pozitif net işletme sermayesi",
            message=(
                "Şirket pozitif net işletme sermayesine sahiptir."
            ),
            severity="positive",
            category="liquidity",
            metric="net_working_capital",
            value=net_working_capital,
            threshold=0,
        )

    if debt_to_equity is None:
        missing_data.append(
            "Borç/özkaynak oranı hesaplanamadı; özkaynak verisi sıfır veya eksik."
        )
    elif debt_to_equity > 3:
        add_insight(
            insights,
            code="LEVERAGE_CRITICAL",
            title="Çok yüksek borçluluk",
            message=(
                "Toplam borçların özkaynaklara oranı 3,00 seviyesinin üzerindedir. "
                "Finansman yapısı belirgin biçimde borç ağırlıklıdır."
            ),
            severity="critical",
            category="leverage",
            metric="debt_to_equity",
            value=debt_to_equity,
            threshold=3.0,
        )
    elif debt_to_equity > 2:
        add_insight(
            insights,
            code="LEVERAGE_HIGH",
            title="Yüksek borçluluk",
            message=(
                "Borç/özkaynak oranı 2,00 seviyesinin üzerindedir. "
                "Borç servis kapasitesi ve özkaynak güçlendirme ihtiyacı izlenmelidir."
            ),
            severity="warning",
            category="leverage",
            metric="debt_to_equity",
            value=debt_to_equity,
            threshold=2.0,
        )
    else:
        add_insight(
            insights,
            code="LEVERAGE_MODERATE",
            title="Borçluluk seviyesi yönetilebilir",
            message=(
                "Borç/özkaynak oranı 2,00 seviyesinin altındadır."
            ),
            severity="positive",
            category="leverage",
            metric="debt_to_equity",
            value=debt_to_equity,
            threshold=2.0,
        )

    if debt_ratio is not None and debt_ratio > 0.70:
        add_insight(
            insights,
            code="DEBT_RATIO_HIGH",
            title="Varlık finansmanında yüksek borç payı",
            message=(
                "Toplam varlıkların yüzde 70'inden fazlası yabancı kaynaklarla finanse edilmektedir."
            ),
            severity="warning",
            category="leverage",
            metric="debt_ratio",
            value=debt_ratio,
            threshold=0.70,
        )

    if equity_ratio is not None and equity_ratio < 0.30:
        add_insight(
            insights,
            code="EQUITY_RATIO_LOW",
            title="Özkaynak tamponu zayıf",
            message=(
                "Özkaynakların toplam varlıklara oranı yüzde 30'un altındadır."
            ),
            severity="warning",
            category="leverage",
            metric="equity_ratio",
            value=equity_ratio,
            threshold=0.30,
        )

    if (
        short_term_debt_ratio is not None
        and short_term_debt_ratio > 0.75
    ):
        add_insight(
            insights,
            code="SHORT_TERM_DEBT_CONCENTRATION",
            title="Borçlar kısa vadede yoğunlaşıyor",
            message=(
                "Toplam borçların yüzde 75'inden fazlası kısa vadelidir. "
                "Refinansman ve nakit akışı riski izlenmelidir."
            ),
            severity="warning",
            category="leverage",
            metric="short_term_debt_ratio",
            value=short_term_debt_ratio,
            threshold=0.75,
        )

    if not data_quality["income_statement_available"]:
        missing_data.append(
            "Gelir tablosu hesapları bulunmadığı için kârlılık analizi yapılamadı."
        )
        add_insight(
            insights,
            code="INCOME_STATEMENT_MISSING",
            title="Kârlılık analizi eksik",
            message=(
                "İncelenen dosyada gelir tablosu hesapları bulunmadığı için "
                "satış, kâr marjı ve faaliyet performansı değerlendirilemedi."
            ),
            severity="info",
            category="data_quality",
            confidence="high",
        )
    else:
        gross_margin = profitability["gross_profit_margin"]

        if gross_margin is not None and gross_margin < 0:
            add_insight(
                insights,
                code="NEGATIVE_GROSS_MARGIN",
                title="Negatif brüt kâr marjı",
                message=(
                    "Satışların maliyeti net satışları aşmaktadır."
                ),
                severity="critical",
                category="profitability",
                metric="gross_profit_margin",
                value=gross_margin,
                threshold=0,
            )

    if financing_expense_coverage is not None:
        if financing_expense_coverage < 1:
            add_insight(
                insights,
                code="FINANCE_COVERAGE_CRITICAL",
                title="Finansman gideri karşılanamıyor",
                message=(
                    "Faaliyet kârı finansman giderlerini karşılamaya yetmemektedir."
                ),
                severity="critical",
                category="coverage",
                metric="financing_expense_coverage",
                value=financing_expense_coverage,
                threshold=1.0,
            )
        elif financing_expense_coverage < 2:
            add_insight(
                insights,
                code="FINANCE_COVERAGE_WEAK",
                title="Finansman gideri karşılama gücü zayıf",
                message=(
                    "Faaliyet kârının finansman giderlerini karşılama kapasitesi sınırlıdır."
                ),
                severity="warning",
                category="coverage",
                metric="financing_expense_coverage",
                value=financing_expense_coverage,
                threshold=2.0,
            )

    severity_order = {
        "critical": 0,
        "warning": 1,
        "info": 2,
        "positive": 3,
    }

    insights.sort(
        key=lambda item: severity_order.get(
            item["severity"],
            99,
        )
    )

    critical_count = sum(
        1 for item in insights
        if item["severity"] == "critical"
    )
    warning_count = sum(
        1 for item in insights
        if item["severity"] == "warning"
    )

    if critical_count:
        overall_risk = "high"
    elif warning_count >= 2:
        overall_risk = "medium_high"
    elif warning_count == 1:
        overall_risk = "medium"
    else:
        overall_risk = "low"

    return {
        "overall_risk": overall_risk,
        "insight_count": len(insights),
        "critical_count": critical_count,
        "warning_count": warning_count,
        "missing_data": missing_data,
        "insights": insights,
    }