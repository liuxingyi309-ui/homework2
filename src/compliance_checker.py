import re
from datetime import datetime
from typing import Any, Dict, List

import pycountry
import stdnum.lei

from .models import ComplianceFinding, ComplianceResult
from .parser import ISO_8601_UTC_RE


UTI_RE = re.compile(r"^[A-Z0-9-]{1,52}$")
UTI_SUFFIX_RE = re.compile(r"^[A-Z0-9-]{1,32}$")

COMMON_REQUIRED_FIELDS = [
    "uti",
    "reporting_counterparty_lei",
    "other_counterparty_lei",
    "execution_timestamp",
    "action_type",
    "cleared",
    "notional_currency",
]

CFTC_REQUIRED_FIELDS = COMMON_REQUIRED_FIELDS

EMIR_REQUIRED_FIELDS = COMMON_REQUIRED_FIELDS + [
    "collateral_portfolio_code",
    "initial_margin_posted",
    "variation_margin_posted",
]

ASSET_CLASS_REQUIRED_FIELD_GROUPS = {
    "Rates": [["reference_rate", "reference_rate_leg1", "reference_rate_leg2", "strike_rate"]],
    "Credit": [["reference_entity_lei", "reference_entity_isin", "index_name"]],
    "FX": [["underlying_currency_pair", "settlement_currency"]],
    "Equity": [["underlying_isin", "underlying_index"]],
    "Commodities": [["underlying_commodity"]],
    "EventContract": [["event_type"], ["platform"]],
}


def _finding(code: str, severity: str, message: str, field: str = None) -> ComplianceFinding:
    return ComplianceFinding(code=code, severity=severity, message=message, field=field)


def _is_missing(value: Any) -> bool:
    return value is None or value == ""


def _trade_value(raw_trade: Dict[str, Any], field: str) -> Any:
    if field == "notional_currency":
        return raw_trade.get("notional_currency") or raw_trade.get("notional_currency_leg1")
    return raw_trade.get(field)


def validate_lei(raw_trade: Dict[str, Any]) -> List[ComplianceFinding]:
    findings: List[ComplianceFinding] = []

    for field in ("reporting_counterparty_lei", "other_counterparty_lei"):
        value = raw_trade.get(field)
        if _is_missing(value):
            findings.append(_finding("MISSING_LEI", "NONCOMPLIANT", f"{field} is missing.", field))
            continue
        try:
            stdnum.lei.validate(str(value))
        except Exception as exc:
            findings.append(_finding("INVALID_LEI", "NONCOMPLIANT", f"{field}={value} is not a valid LEI: {exc}", field))

    return findings


def validate_uti(raw_trade: Dict[str, Any]) -> List[ComplianceFinding]:
    findings: List[ComplianceFinding] = []
    uti = raw_trade.get("uti")
    reporting_lei = raw_trade.get("reporting_counterparty_lei")

    if _is_missing(uti):
        findings.append(_finding("MISSING_UTI", "NONCOMPLIANT", "UTI is missing.", "uti"))
        return findings

    uti = str(uti)
    if not UTI_RE.match(uti):
        findings.append(_finding("INVALID_UTI_FORMAT", "NONCOMPLIANT", "UTI must be at most 52 chars using uppercase letters, digits, or hyphens.", "uti"))

    if len(uti) < 21:
        findings.append(_finding("INVALID_UTI_LENGTH", "NONCOMPLIANT", "UTI is too short to contain a 20-character LEI namespace plus suffix.", "uti"))
        return findings

    namespace = uti[:20]
    suffix = uti[20:]

    if reporting_lei and namespace != reporting_lei:
        findings.append(_finding("UTI_NAMESPACE_MISMATCH", "NONCOMPLIANT", "First 20 characters of UTI must match reporting_counterparty_lei.", "uti"))

    if not suffix or not UTI_SUFFIX_RE.match(suffix):
        findings.append(_finding("INVALID_UTI_SUFFIX", "NONCOMPLIANT", "UTI suffix must be 1-32 chars using uppercase letters, digits, or hyphens.", "uti"))

    return findings


def validate_timestamp(raw_trade: Dict[str, Any]) -> List[ComplianceFinding]:
    value = raw_trade.get("execution_timestamp")
    if _is_missing(value):
        return [_finding("MISSING_TIMESTAMP", "NONCOMPLIANT", "execution_timestamp is missing.", "execution_timestamp")]
    if not isinstance(value, str) or not ISO_8601_UTC_RE.match(value):
        return [_finding("INVALID_TIMESTAMP", "NONCOMPLIANT", "execution_timestamp must be ISO 8601 UTC, e.g. 2025-01-15T14:22:00Z.", "execution_timestamp")]
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return [_finding("INVALID_TIMESTAMP", "NONCOMPLIANT", "execution_timestamp is not a real UTC timestamp.", "execution_timestamp")]
    return []


def validate_currency(raw_trade: Dict[str, Any]) -> List[ComplianceFinding]:
    value = _trade_value(raw_trade, "notional_currency")
    if _is_missing(value):
        return [_finding("MISSING_NOTIONAL_CURRENCY", "NONCOMPLIANT", "notional_currency is missing.", "notional_currency")]

    currency = str(value)
    if currency == "XAU":
        return []
    if pycountry.currencies.get(alpha_3=currency) is None:
        return [_finding("INVALID_CURRENCY", "NONCOMPLIANT", f"{currency} is not a valid ISO 4217 currency code.", "notional_currency")]
    return []


def validate_notional_amount(raw_trade: Dict[str, Any]) -> List[ComplianceFinding]:
    value = raw_trade.get("notional_amount") or raw_trade.get("notional_amount_leg1")
    if _is_missing(value):
        return [_finding("MISSING_NOTIONAL_AMOUNT", "NONCOMPLIANT", "notional_amount is missing.", "notional_amount")]

    try:
        amount = float(value)
    except (TypeError, ValueError):
        return [_finding("INVALID_NOTIONAL_AMOUNT", "NONCOMPLIANT", f"notional_amount={value} is not numeric.", "notional_amount")]

    if amount <= 0:
        return [_finding("INVALID_NOTIONAL_AMOUNT", "NONCOMPLIANT", "notional_amount must be greater than zero.", "notional_amount")]
    return []


def validate_date_order(raw_trade: Dict[str, Any]) -> List[ComplianceFinding]:
    effective_date = raw_trade.get("effective_date")
    maturity_date = raw_trade.get("maturity_date")
    if _is_missing(effective_date) or _is_missing(maturity_date):
        return []

    try:
        effective = datetime.strptime(str(effective_date), "%Y-%m-%d")
        maturity = datetime.strptime(str(maturity_date), "%Y-%m-%d")
    except ValueError:
        return []

    if maturity < effective:
        return [_finding("INVALID_DATE_ORDER", "NONCOMPLIANT", "maturity_date cannot be earlier than effective_date.", "maturity_date")]
    return []


def validate_clearing_fields(raw_trade: Dict[str, Any]) -> List[ComplianceFinding]:
    if raw_trade.get("cleared") is True and _is_missing(raw_trade.get("clearing_house")):
        return [_finding("MISSING_CLEARING_HOUSE", "NONCOMPLIANT", "clearing_house is required when cleared is true.", "clearing_house")]
    return []


def validate_asset_class_fields(raw_trade: Dict[str, Any]) -> List[ComplianceFinding]:
    findings: List[ComplianceFinding] = []
    asset_class = raw_trade.get("asset_class")
    required_field_groups = ASSET_CLASS_REQUIRED_FIELD_GROUPS.get(asset_class, [])

    for field_group in required_field_groups:
        if any(not _is_missing(raw_trade.get(field)) for field in field_group):
            continue
        field_label = " or ".join(field_group)
        findings.append(_finding("MISSING_ASSET_CLASS_FIELD", "NONCOMPLIANT", f"{field_label} is expected for asset_class={asset_class}.", field_group[0]))

    return findings


def validate_required_fields(raw_trade: Dict[str, Any], regime: str) -> List[ComplianceFinding]:
    findings: List[ComplianceFinding] = []
    required_fields = EMIR_REQUIRED_FIELDS if regime == "EMIR" else CFTC_REQUIRED_FIELDS

    for field in required_fields:
        value = _trade_value(raw_trade, field)
        if _is_missing(value):
            findings.append(_finding("MISSING_REQUIRED_FIELD", "NONCOMPLIANT", f"{field} is required for {regime}.", field))

    return findings


def validate_upi(raw_trade: Dict[str, Any], upi_result: Dict[str, Any]) -> List[ComplianceFinding]:
    if upi_result.get("status") == "NO_PRODUCT_DEFINITION":
        return [_finding("NO_PRODUCT_DEFINITION", "WARNING", upi_result.get("classification_note") or "No UPI product definition.", "upi")]

    if upi_result.get("status") == "FOUND_WITH_VALIDATION_ERRORS":
        return [
            _finding("UPI_ATTRIBUTE_VALIDATION_ERROR", "NONCOMPLIANT", message, "upi")
            for message in upi_result.get("validation_errors", [])
        ]

    if upi_result.get("status") not in {"FOUND"}:
        return [_finding("UPI_TEMPLATE_NOT_FOUND", "NONCOMPLIANT", f"UPI template lookup status is {upi_result.get('status')}.", "upi")]

    return []


def _dedupe_findings(findings: List[ComplianceFinding]) -> List[ComplianceFinding]:
    seen = set()
    unique: List[ComplianceFinding] = []
    for finding in findings:
        key = (finding.code, finding.field, finding.message)
        if key in seen:
            continue
        seen.add(key)
        unique.append(finding)
    return unique


def check_trade_for_regime(raw_trade: Dict[str, Any], upi_result: Dict[str, Any], regime: str) -> ComplianceResult:
    findings: List[ComplianceFinding] = []

    findings.extend(validate_required_fields(raw_trade, regime))
    findings.extend(validate_lei(raw_trade))
    findings.extend(validate_uti(raw_trade))
    findings.extend(validate_timestamp(raw_trade))
    findings.extend(validate_currency(raw_trade))
    findings.extend(validate_notional_amount(raw_trade))
    findings.extend(validate_date_order(raw_trade))
    findings.extend(validate_clearing_fields(raw_trade))
    findings.extend(validate_asset_class_fields(raw_trade))
    findings.extend(validate_upi(raw_trade, upi_result))

    if regime == "CFTC" and raw_trade.get("asset_class") == "EventContract":
        platform = raw_trade.get("platform")
        if platform == "Kalshi":
            findings.append(_finding("EVENT_CONTRACT_CFTC_CONDITIONAL", "WARNING", "Kalshi event contract is treated as conditional CFTC scope for the written analysis.", "asset_class"))
        else:
            findings.append(_finding("EVENT_CONTRACT_CFTC_NOT_APPLICABLE", "WARNING", "Non-DCM event contract is treated as not applicable for CFTC OTC reporting.", "asset_class"))

    if regime == "EMIR" and raw_trade.get("asset_class") == "EventContract":
        findings.append(_finding("EVENT_CONTRACT_EMIR_NOT_APPLICABLE", "WARNING", "EventContract is outside EMIR OTC derivative taxonomy in this project.", "asset_class"))

    findings = _dedupe_findings(findings)

    has_noncompliant = any(finding.severity == "NONCOMPLIANT" for finding in findings)
    has_warning = any(finding.severity == "WARNING" for finding in findings)
    status = "NONCOMPLIANT" if has_noncompliant else "WARNING" if has_warning else "PASS"

    return ComplianceResult(
        trade_id=str(raw_trade.get("trade_id", "UNKNOWN")),
        regime=regime,
        status=status,
        findings=findings,
    )


def check_compliance(raw_trades: List[Dict[str, Any]], upi_results: List[Dict[str, Any]], regimes: List[str]) -> List[ComplianceResult]:
    upi_by_trade_id = {result["trade_id"]: result for result in upi_results}
    results: List[ComplianceResult] = []

    for raw_trade in raw_trades:
        trade_id = str(raw_trade.get("trade_id", "UNKNOWN"))
        upi_result = upi_by_trade_id.get(trade_id, {})
        for regime in regimes:
            results.append(check_trade_for_regime(raw_trade, upi_result, regime))

    return results
