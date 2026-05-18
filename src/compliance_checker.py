import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from typing import Any, Dict, List, Optional

import pycountry
try:
    from stdnum.iso import lei
except ImportError:
    from stdnum import lei

from .models import ComplianceFinding, ComplianceResult
from .parser import ISO_8601_UTC_RE


COMPLIANT = "COMPLIANT"
NONCOMPLIANT = "NONCOMPLIANT"
CONDITIONAL = "CONDITIONAL"
NOT_APPLICABLE = "NOT_APPLICABLE"

GLEIF_LOOKUP_ENV = "ENABLE_GLEIF_LOOKUP"
GLEIF_LEI_RECORD_URL = "https://api.gleif.org/api/v1/lei-records/{lei}"

# UTI suffix comes after the 20-character LEI namespace.
UTI_SUFFIX_RE = re.compile(r"^[A-Z0-9-]+$")

# These required fields are not already covered by specialised validators below.
# LEI, UTI, timestamp, currency, notional amount, and UPI each have their own
# validation functions so their error messages stay specific.
COMMON_REQUIRED_FIELDS = [
    "effective_date",
    "maturity_or_expiry_date",
    "action_type",
    "cleared",
]

CFTC_REQUIRED_FIELDS = COMMON_REQUIRED_FIELDS

EMIR_MARGIN_FIELDS = [
    "collateral_portfolio_code",
    "initial_margin_posted",
    "variation_margin_posted",
]

EMIR_REQUIRED_FIELDS = COMMON_REQUIRED_FIELDS + EMIR_MARGIN_FIELDS

ASSET_CLASS_REQUIRED_FIELD_GROUPS = {
    "Rates": [["reference_rate", "reference_rate_leg1", "reference_rate_leg2", "strike_rate"]],
    "Credit": [["reference_entity_lei", "reference_entity_isin", "index_name"]],
    "FX": [["underlying_currency_pair", "settlement_currency"]],
    "Equity": [["underlying_isin", "underlying_index"]],
    "Commodities": [["underlying_commodity"]],
    "EventContract": [["event_type"], ["platform"]],
}

OFFSHORE_EVENT_RISK_FACTORS = {
    "platform_type": {
        "DECENTRALISED_BLOCKCHAIN_PLATFORM": "decentralised blockchain platform",
    },
    "platform_jurisdiction": {
        "OFFSHORE_UNREGULATED": "offshore unregulated platform jurisdiction",
    },
    "access_method": {
        "VPN_BYPASS_GGL_BLOCK": "VPN bypass of geo-blocking",
    },
    "notional_currency": {
        "USDC": "USDC settlement",
        "USDT": "USDT settlement",
        "DAI": "DAI settlement",
    },
}

# GLEIF lookup.
@dataclass
class GleifLookupResult:
    lei: str
    status: str
    entity_status: Optional[str] = None
    registration_status: Optional[str] = None
    legal_name: Optional[str] = None
    error: Optional[str] = None

# Small helpers used by the validation pipeline.
def _finding(code: str, severity: str, message: str, field: str = None) -> ComplianceFinding:
    return ComplianceFinding(code=code, severity=severity, message=message, field=field)

def _is_missing(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")

def _trade_value(raw_trade: Dict[str, Any], field: str) -> Any:
    # Some asset classes use leg-specific field names; this keeps validators
    # focused on the regulatory concept rather than every raw JSON variant.
    if field == "notional_currency":
        return raw_trade.get("notional_currency") or raw_trade.get("notional_currency_leg1")
    if field == "notional_amount":
        return raw_trade.get("notional_amount") or raw_trade.get("notional_amount_leg1")
    if field == "maturity_or_expiry_date":
        return raw_trade.get("maturity_date") or raw_trade.get("expiry_date")
    return raw_trade.get(field)



def _lei_error_code(error_message: str) -> str:
    if error_message == "Missing LEI":
        return "MISSING_LEI"
    if "exactly 20 characters" in error_message:
        return "INVALID_LEI_LENGTH"
    if "checksum" in error_message or "check digit" in error_message:
        return "INVALID_LEI_CHECK_DIGIT"
    return "INVALID_LEI_FORMAT"


def _uti_error_code(error_message: str) -> str:
    if error_message == "Missing UTI":
        return "MISSING_UTI"
    if "must not exceed" in error_message:
        return "UTI_TOO_LONG"
    if "namespace LEI" in error_message and "Invalid" in error_message:
        return "UTI_NAMESPACE_LEI_INVALID"
    if "namespace LEI must match" in error_message:
        return "UTI_NAMESPACE_MISMATCH"
    if "suffix" in error_message:
        return "UTI_SUFFIX_INVALID"
    return "INVALID_UTI"


def _upi_warning_code(warning: str) -> str:
    if "historical LIBOR" in warning:
        return "HISTORICAL_REFERENCE_RATE_WARNING"
    if "mapped to ANNA-DSB value" in warning:
        return "VALUE_NORMALISED_TO_DSB_CODESET"
    return "UPI_WARNING"


def _upi_attribute_error_code(message: str) -> str:
    if "not in codeset" in message:
        return "INVALID_UPI_CODESET_VALUE"
    if "not one of" in message:
        return "INVALID_UPI_ENUM_VALUE"
    return "UPI_ATTRIBUTE_VALIDATION_ERROR"


def _required_field_code(field: str, regime: str) -> str:
    if regime == "EMIR" and field in EMIR_MARGIN_FIELDS:
        return "MISSING_EMIR_MARGIN_FIELD"
    if field == "maturity_or_expiry_date":
        return "MISSING_MATURITY_OR_EXPIRY_DATE"
    return f"MISSING_{field.upper()}"


def validate_uti(uti: Optional[str], reporting_lei: Optional[str]) -> tuple[bool, str]:
    """
    Validate a UTI under ISO 23897-style rules used in the assignment.

    Rules: max 52 chars, first 20 chars are a valid LEI namespace, namespace
    equals the reporting counterparty LEI, and suffix is uppercase
    alphanumeric/hyphen only.
    """
    if _is_missing(uti):
        return False, "Missing UTI"

    value = str(uti).strip()
    if len(value) > 52:
        return False, "UTI must not exceed 52 characters"
    if len(value) <= 20:
        return False, "UTI must contain a 20-character LEI namespace and a suffix"

    namespace = value[:20]
    suffix = value[20:]

    namespace_valid, namespace_error = validate_lei(namespace)
    if not namespace_valid:
        return False, f"Invalid UTI namespace LEI: {namespace_error}"

    if _is_missing(reporting_lei):
        return False, "Cannot validate UTI namespace without reporting counterparty LEI"
    if namespace != str(reporting_lei).strip():
        return False, "UTI namespace LEI must match reporting counterparty LEI"

    if not UTI_SUFFIX_RE.match(suffix):
        return False, "UTI suffix must contain only A-Z, 0-9, and hyphen"

    return True, ""

def validate_trade_uti(raw_trade: Dict[str, Any]) -> List[ComplianceFinding]:
    # A valid UTI must be anchored to the reporting counterparty LEI.
    is_valid, error_message = validate_uti(
        raw_trade.get("uti"),
        raw_trade.get("reporting_counterparty_lei"),
    )
    if is_valid:
        return []

    return [_finding(_uti_error_code(error_message), NONCOMPLIANT, error_message, "uti")]

def validate_upi(raw_trade: Dict[str, Any], upi_result: Dict[str, Any]) -> List[ComplianceFinding]:
    # For conventional derivatives, no product definition is a hard reporting
    # problem. Event contracts never reach this function because they are
    # scoped before normal OTC validation.
    if not upi_result:
        return [_finding("MISSING_UPI_LOOKUP_RESULT", NONCOMPLIANT, "UPI lookup result is missing.", "upi")]

    warnings = [
        _finding(_upi_warning_code(warning), "WARNING", warning, "upi")
        for warning in upi_result.get("warnings", [])
    ]

    if upi_result.get("status") == "FOUND":
        return warnings

    if upi_result.get("status") == "NO_PRODUCT_DEFINITION":
        return [_finding("NO_PRODUCT_DEFINITION", NONCOMPLIANT, upi_result.get("classification_note") or "No UPI product definition.", "upi")]

    if upi_result.get("status") == "FOUND_WITH_VALIDATION_ERRORS":
        return [
            _finding(_upi_attribute_error_code(message), NONCOMPLIANT, message, "upi")
            for message in upi_result.get("validation_errors", [])
        ] + warnings

    return [_finding("UPI_TEMPLATE_NOT_FOUND", NONCOMPLIANT, f"UPI template lookup status is {upi_result.get('status')}.", "upi")]

def validate_lei(lei_value: Optional[str]) -> tuple[bool, str]:
    """
    Validate a Legal Entity Identifier using ISO 17442 / ISO 7064 MOD 97-10.

    Returns (is_valid, error_message), matching the assignment stub.
    """
    if _is_missing(lei_value):
        return False, "Missing LEI"

    value = str(lei_value).strip()
    if len(value) != 20:
        return False, "LEI must be exactly 20 characters"

    try:
        lei.validate(value)
    except Exception as exc:
        return False, f"Invalid LEI: {exc}"

    return True, ""

def gleif_lookup_enabled() -> bool:
    # Disabled by default so network availability does not affect the baseline
    # assignment run. Set ENABLE_GLEIF_LOOKUP=true to enable this extension.
    return os.getenv(GLEIF_LOOKUP_ENV, "").lower() in {"1", "true", "yes", "on"}

def lookup_lei_gleif(lei_value: Optional[str], timeout: float = 5.0) -> GleifLookupResult:
    """
    Optional live lookup against the GLEIF LEI API.

    This is an enrichment step, not the baseline LEI syntax/check-digit
    validation required by the assignment. It checks whether the LEI appears in
    the GLEIF reference data and extracts entity/registration statuses.
    """
    if _is_missing(lei_value):
        return GleifLookupResult(lei="", status="INVALID_INPUT", error="Missing LEI")

    value = str(lei_value).strip()
    local_valid, local_error = validate_lei(value)
    if not local_valid:
        return GleifLookupResult(lei=value, status="INVALID_INPUT", error=local_error)

    url = GLEIF_LEI_RECORD_URL.format(lei=value)
    request = Request(url, headers={"Accept": "application/vnd.api+json"})

    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        if exc.code == 404:
            return GleifLookupResult(lei=value, status="NOT_FOUND", error="LEI not found in GLEIF")
        return GleifLookupResult(lei=value, status="LOOKUP_UNAVAILABLE", error=f"GLEIF HTTP error {exc.code}")
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        return GleifLookupResult(lei=value, status="LOOKUP_UNAVAILABLE", error=str(exc))

    attributes = payload.get("data", {}).get("attributes", {})
    entity = attributes.get("entity", {})
    registration = attributes.get("registration", {})
    legal_name = entity.get("legalName", {})
    legal_name_value = legal_name.get("name") if isinstance(legal_name, dict) else None
    entity_status = entity.get("status")
    registration_status = registration.get("status")

    if entity_status == "ACTIVE" and registration_status == "ISSUED":
        status = "ACTIVE"
        error = None
    else:
        status = "INACTIVE"
        error = f"GLEIF entity_status={entity_status}, registration_status={registration_status}"

    return GleifLookupResult(
        lei=value,
        status=status,
        entity_status=entity_status,
        registration_status=registration_status,
        legal_name=legal_name_value,
        error=error,
    )

def validate_trade_leis(raw_trade: Dict[str, Any]) -> List[ComplianceFinding]:
    # Trade-level wrapper: convert the assignment-style tuple result into
    # structured ComplianceFinding objects used by the pipeline output.
    findings: List[ComplianceFinding] = []

    for field in ("reporting_counterparty_lei", "other_counterparty_lei"):
        value = raw_trade.get(field)
        is_valid, error_message = validate_lei(value)
        if not is_valid:
            findings.append(_finding(_lei_error_code(error_message), NONCOMPLIANT, f"{field}: {error_message}", field))
            continue

        if gleif_lookup_enabled():
            gleif_result = lookup_lei_gleif(value)
            if gleif_result.status == "ACTIVE":
                findings.append(
                    _finding(
                        "GLEIF_LEI_ACTIVE",
                        "INFO",
                        f"{field} is active in GLEIF"
                        + (f" for {gleif_result.legal_name}" if gleif_result.legal_name else ""),
                        field,
                    )
                )
            elif gleif_result.status in {"NOT_FOUND", "INACTIVE"}:
                findings.append(
                    _finding(
                        "GLEIF_LEI_NOT_ACTIVE",
                        NONCOMPLIANT,
                        f"{field}: {gleif_result.error}",
                        field,
                    )
                )
            else:
                findings.append(
                    _finding(
                        "GLEIF_LOOKUP_UNAVAILABLE",
                        "WARNING",
                        f"{field}: optional GLEIF lookup unavailable ({gleif_result.error})",
                        field,
                    )
                )

    return findings

def validate_timestamp(raw_trade: Dict[str, Any]) -> List[ComplianceFinding]:
    value = raw_trade.get("execution_timestamp")
    if _is_missing(value):
        return [_finding("MISSING_TIMESTAMP", NONCOMPLIANT, "execution_timestamp is missing.", "execution_timestamp")]
    if not isinstance(value, str) or not ISO_8601_UTC_RE.match(value):
        return [_finding("INVALID_TIMESTAMP", NONCOMPLIANT, "execution_timestamp must be ISO 8601 UTC, e.g. 2025-01-15T14:22:00Z.", "execution_timestamp")]
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return [_finding("INVALID_TIMESTAMP", NONCOMPLIANT, "execution_timestamp is not a real UTC timestamp.", "execution_timestamp")]
    return []

def validate_required_fields(raw_trade: Dict[str, Any], regime: str) -> List[ComplianceFinding]:
    findings: List[ComplianceFinding] = []
    required_fields = EMIR_REQUIRED_FIELDS if regime == "EMIR" else CFTC_REQUIRED_FIELDS

    for field in required_fields:
        value = _trade_value(raw_trade, field)
        if _is_missing(value):
            if field == "maturity_or_expiry_date":
                message = f"maturity_date or expiry_date is required for {regime}."
            else:
                message = f"{field} is required for {regime}."
            findings.append(_finding(_required_field_code(field, regime), NONCOMPLIANT, message, field))

    return findings

def validate_date_order(raw_trade: Dict[str, Any]) -> List[ComplianceFinding]:
    effective_date = raw_trade.get("effective_date")
    end_date = raw_trade.get("maturity_date") or raw_trade.get("expiry_date")
    end_date_field = "maturity_date" if not _is_missing(raw_trade.get("maturity_date")) else "expiry_date"
    if _is_missing(effective_date) or _is_missing(end_date):
        return []

    try:
        effective = datetime.strptime(str(effective_date), "%Y-%m-%d")
    except ValueError:
        return [_finding("INVALID_EFFECTIVE_DATE", NONCOMPLIANT, "effective_date must be a real YYYY-MM-DD date.", "effective_date")]

    try:
        maturity = datetime.strptime(str(end_date), "%Y-%m-%d")
    except ValueError:
        return [_finding("INVALID_MATURITY_OR_EXPIRY_DATE", NONCOMPLIANT, f"{end_date_field} must be a real YYYY-MM-DD date.", end_date_field)]

    if maturity < effective:
        return [_finding("INVALID_DATE_ORDER", NONCOMPLIANT, f"{end_date_field} cannot be earlier than effective_date.", end_date_field)]
    return []

def validate_currency(raw_trade: Dict[str, Any]) -> List[ComplianceFinding]:
    value = _trade_value(raw_trade, "notional_currency")
    if _is_missing(value):
        return [_finding("MISSING_NOTIONAL_CURRENCY", NONCOMPLIANT, "notional_currency is missing.", "notional_currency")]

    currency = str(value)
    if currency == "XAU":
        return []
    if pycountry.currencies.get(alpha_3=currency) is None:
        return [_finding("INVALID_CURRENCY", NONCOMPLIANT, f"{currency} is not a valid ISO 4217 currency code.", "notional_currency")]
    return []

def validate_notional_amount(raw_trade: Dict[str, Any]) -> List[ComplianceFinding]:
    value = _trade_value(raw_trade, "notional_amount")
    if _is_missing(value):
        return [_finding("MISSING_NOTIONAL_AMOUNT", NONCOMPLIANT, "notional_amount is missing.", "notional_amount")]

    try:
        amount = float(value)
    except (TypeError, ValueError):
        return [_finding("INVALID_NOTIONAL_AMOUNT", NONCOMPLIANT, f"notional_amount={value} is not numeric.", "notional_amount")]

    if amount <= 0:
        return [_finding("INVALID_NOTIONAL_AMOUNT", NONCOMPLIANT, "notional_amount must be greater than zero.", "notional_amount")]
    return []

def validate_clearing_fields(raw_trade: Dict[str, Any]) -> List[ComplianceFinding]:
    if raw_trade.get("cleared") is True and _is_missing(raw_trade.get("clearing_house")):
        return [_finding("MISSING_CLEARING_HOUSE", NONCOMPLIANT, "clearing_house is required when cleared is true.", "clearing_house")]
    return []

def validate_asset_class_fields(raw_trade: Dict[str, Any]) -> List[ComplianceFinding]:
    findings: List[ComplianceFinding] = []
    asset_class = raw_trade.get("asset_class")
    required_field_groups = ASSET_CLASS_REQUIRED_FIELD_GROUPS.get(asset_class, [])

    for field_group in required_field_groups:
        if any(not _is_missing(raw_trade.get(field)) for field in field_group):
            continue
        field_label = " or ".join(field_group)
        findings.append(_finding("MISSING_ASSET_CLASS_FIELD", NONCOMPLIANT, f"{field_label} is expected for asset_class={asset_class}.", field_group[0]))

    return findings

def _is_event_contract(raw_trade: Dict[str, Any], parsed_trade: Any = None) -> bool:
    # Module 1 flags T026-T028 as NOVEL_INSTRUMENT_NO_TAXONOMY, but the current
    # pipeline only passes raw_trade here. Support both signals for compatibility.
    if raw_trade.get("asset_class") == "EventContract":
        return True
    return getattr(parsed_trade, "classification_flag", None) == "NOVEL_INSTRUMENT_NO_TAXONOMY"

def _is_cftc_dcm_event_contract(raw_trade: Dict[str, Any]) -> bool:
    # EventContracts on a CFTC DCM are CONDITIONAL in this project; non-DCM
    # event contracts such as Polymarket are NOT_APPLICABLE for CFTC OTC rules.
    return raw_trade.get("platform_type") == "CFTC_REGULATED_DCM"

def _offshore_event_contract_findings(raw_trade: Dict[str, Any]) -> List[ComplianceFinding]:
    risk_factors = [
        label
        for field, value_labels in OFFSHORE_EVENT_RISK_FACTORS.items()
        for value, label in value_labels.items()
        if raw_trade.get(field) == value
    ]

    if not risk_factors:
        return []

    return [
        _finding(
            "EVENT_CONTRACT_OFFSHORE_ACCESS_RISK",
            "INFO",
            "EventContract is outside CFTC DCM reporting scope but presents regulatory perimeter risk: "
            + ", ".join(risk_factors)
            + ".",
            "platform_type",
        )
    ]

def _uncleared_cross_border_cds_findings(raw_trade: Dict[str, Any]) -> List[ComplianceFinding]:
    if (
        raw_trade.get("asset_class") == "Credit"
        and raw_trade.get("instrument_type") == "Swap"
        and raw_trade.get("counterparty_jurisdiction") == "US-EU_CROSS_BORDER"
        and raw_trade.get("cleared") is False
    ):
        return [
            _finding(
                "UNCLEARED_CROSS_BORDER_CDS_REVIEW",
                "WARNING",
                "Cross-border CDS is reported as uncleared; review clearing obligation, bilateral margin, and collateral reporting requirements.",
                "cleared",
            )
        ]
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

def _check_conventional_derivative(
    raw_trade: Dict[str, Any],
    upi_result: Dict[str, Any],
    regime: str,
) -> ComplianceResult:
    # Only conventional OTC derivatives should reach this path. EventContract
    # trades are classification-frontier cases and are handled before this step.
    findings: List[ComplianceFinding] = []

    findings.extend(validate_required_fields(raw_trade, regime))
    findings.extend(validate_trade_leis(raw_trade))
    findings.extend(validate_trade_uti(raw_trade))
    findings.extend(validate_timestamp(raw_trade))
    findings.extend(validate_currency(raw_trade))
    findings.extend(validate_notional_amount(raw_trade))
    findings.extend(validate_date_order(raw_trade))
    findings.extend(validate_clearing_fields(raw_trade))
    findings.extend(validate_asset_class_fields(raw_trade))
    findings.extend(validate_upi(raw_trade, upi_result))
    if regime == "CFTC":
        findings.extend(_uncleared_cross_border_cds_findings(raw_trade))

    findings = _dedupe_findings(findings)
    status = NONCOMPLIANT if any(finding.severity == NONCOMPLIANT for finding in findings) else COMPLIANT

    return ComplianceResult(
        trade_id=str(raw_trade.get("trade_id", "UNKNOWN")),
        regime=regime,
        status=status,
        findings=findings,
    )

def check_cftc_compliance(parsed_trade: Any, upi_result: Dict[str, Any], raw_trade: Dict[str, Any]) -> ComplianceResult:
    """
    CFTC reporting decision.

    Event contracts on a CFTC-regulated DCM are conditional classification-frontier
    cases. Event contracts outside a CFTC DCM are not applicable to CFTC OTC
    reporting in this assignment. Conventional derivatives go through normal
    field, identifier, timestamp, currency, and UPI validation.
    """
    if _is_event_contract(raw_trade, parsed_trade):
        if _is_cftc_dcm_event_contract(raw_trade):
            return ComplianceResult(
                trade_id=str(raw_trade.get("trade_id", "UNKNOWN")),
                regime="CFTC",
                status=CONDITIONAL,
                findings=[
                    _finding(
                        "EVENT_CONTRACT_CFTC_CONDITIONAL",
                        "INFO",
                        "EventContract has no ANNA-DSB OTC UPI product definition; because it is traded on a CFTC-regulated DCM, CFTC treatment is CONDITIONAL pending classification.",
                        "asset_class",
                    )
                ],
            )

        findings = [
            _finding(
                "EVENT_CONTRACT_CFTC_NOT_APPLICABLE",
                "INFO",
                "EventContract has no ANNA-DSB OTC UPI product definition; because it is not traded on a CFTC-regulated DCM, CFTC OTC reporting is NOT_APPLICABLE in this project.",
                "asset_class",
            )
        ] + _offshore_event_contract_findings(raw_trade)

        return ComplianceResult(
            trade_id=str(raw_trade.get("trade_id", "UNKNOWN")),
            regime="CFTC",
            status=NOT_APPLICABLE,
            findings=findings,
        )

    return _check_conventional_derivative(raw_trade, upi_result, "CFTC")

def check_emir_compliance(parsed_trade: Any, upi_result: Dict[str, Any], raw_trade: Dict[str, Any]) -> ComplianceResult:
    """
    EMIR Refit reporting decision.

    Event contracts are not applicable under the assignment's EU gambling
    classification analysis. Conventional derivatives are validated against
    common reporting fields plus EMIR collateral and margin fields.
    """
    if _is_event_contract(raw_trade, parsed_trade):
        return ComplianceResult(
            trade_id=str(raw_trade.get("trade_id", "UNKNOWN")),
            regime="EMIR",
            status=NOT_APPLICABLE,
            findings=[
                _finding(
                    "EVENT_CONTRACT_EMIR_NOT_APPLICABLE",
                    "INFO",
                    "EventContract is treated as outside EMIR OTC derivative reporting scope due to gambling classification under European national frameworks; normal EMIR field validation is not applied.",
                    "asset_class",
                )
            ],
        )

    return _check_conventional_derivative(raw_trade, upi_result, "EMIR")

def check_trade_for_regime(raw_trade: Dict[str, Any], upi_result: Dict[str, Any], regime: str) -> ComplianceResult:
    if regime == "CFTC":
        return check_cftc_compliance(None, upi_result, raw_trade)
    if regime == "EMIR":
        return check_emir_compliance(None, upi_result, raw_trade)

    return ComplianceResult(
        trade_id=str(raw_trade.get("trade_id", "UNKNOWN")),
        regime=regime,
        status=NOT_APPLICABLE,
        findings=[
            _finding(
                "UNSUPPORTED_REGIME",
                "INFO",
                f"{regime} compliance is not implemented in this project.",
                "regime",
            )
        ],
    )

def check_compliance(raw_trades: List[Dict[str, Any]], upi_results: List[Dict[str, Any]], regimes: List[str]) -> List[ComplianceResult]:
    upi_by_trade_id = {result["trade_id"]: result for result in upi_results}
    results: List[ComplianceResult] = []

    for raw_trade in raw_trades:
        trade_id = str(raw_trade.get("trade_id", "UNKNOWN"))
        upi_result = upi_by_trade_id.get(trade_id, {})
        for regime in regimes:
            results.append(check_trade_for_regime(raw_trade, upi_result, regime.upper()))

    return results
