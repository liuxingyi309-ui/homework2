import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from .models import ParsedTrade, UpiLookupResult


NO_PRODUCT_DEFINITION_CLASSES = {"EventContract"}
CODESET_CACHE: Dict[Path, Set[str]] = {}

# The homework trades use shorter names than the ANNA-DSB template files.
# This table keeps the mapping visible instead of hiding it in fuzzy matching.
TEMPLATE_NAME_OVERRIDES = {
    ("FX", "Forward", "NDF"): "Foreign_Exchange.Forward.NDF.UPI.V1.json",
    ("FX", "Forward", "Deliverable"): "Foreign_Exchange.Forward.Forward.UPI.V1.json",
    ("FX", "Option", "Vanilla"): "Foreign_Exchange.Option.Vanilla_Option.UPI.V1.json",
    ("FX", "Option", "Barrier"): "Foreign_Exchange.Option.Barrier_Option.UPI.V1.json",
    ("FX", "Swap", "Standard"): "Foreign_Exchange.Swap.FX_Swap.UPI.V1.json",
    ("Equity", "Option", "SingleName_Put"): "Equity.Option.Single_Name.UPI.V1.json",
    ("Equity", "Swap", "TotalReturn_SingleIndex"): "Equity.Swap.Total_Return_Swap_Single_Index.UPI.V1.json",
    ("Equity", "Swap", "Variance"): "Equity.Swap.Parameter_Return_Variance_Single_Name.UPI.V1.json",
    ("Equity", "Forward", "SingleName"): "Equity.Forward.Price_Return_Basic_Performance_Single_Name.UPI.V1.json",
    ("Commodities", "Swap", "SingleName"): "Commodities.Swap.Swap.UPI.V1.json",
    ("Commodities", "Option", "SingleName"): "Commodities.Option.Option.UPI.V1.json",
    ("Rates", "Swap", "CrossCurrency"): "Rates.Swap.Cross_Currency_Fixed_Float.UPI.V1.json",
    ("Rates", "Swap", "Inflation"): "Rates.Swap.Inflation_Swap.UPI.V1.json",
    ("Rates", "Swap", "OIS"): "Rates.Swap.Fixed_Float_OIS.UPI.V1.json",
    ("Rates", "Cap_Floor", "Cap"): "Rates.Option.CapFloor.UPI.V1.json",
}

ATTRIBUTE_FIELD_MAP = {
    "NotionalCurrency": ["notional_currency", "notional_currency_leg1"],
    "OtherNotionalCurrency": ["notional_currency_leg2"],
    "SettlementCurrency": ["settlement_currency"],
    "ReferenceRate": ["reference_rate", "reference_rate_leg1"],
    "OtherReferenceRate": ["reference_rate_leg2"],
    "ReferenceRateTermValue": ["reference_rate_term_value", "reference_rate_term_leg1_value"],
    "ReferenceRateTermUnit": ["reference_rate_term_unit", "reference_rate_term_leg1_unit"],
    "OtherReferenceRateTermValue": ["reference_rate_term_leg2_value"],
    "OtherReferenceRateTermUnit": ["reference_rate_term_leg2_unit"],
    "DeliveryType": ["delivery_type"],
    "DebtSeniority": ["debt_seniority"],
    "ReturnType": ["return_type"],
    "OptionType": ["option_type"],
}

VALUE_ALIASES = {
    ("OptionType", "PUT"): "PUTO",
    ("OptionType", "PAYER"): "CALL",
    ("OptionType", "RECEIVER"): "PUTO",
    ("ReferenceRate", "GBP-RPI"): "UK-RPI",
    ("ReferenceRate", "EUR-ESTR"): "EUR-EuroSTR",
}

#ANNA-DSB模板文件名|asset_class + instrument_type + use_case  映射表有直接拿，没有就拼接
def expected_template_name(parsed_trade: ParsedTrade) -> Optional[str]:
    if not parsed_trade.asset_class or not parsed_trade.instrument_type or not parsed_trade.use_case:
        return None
    key = (parsed_trade.asset_class, parsed_trade.instrument_type, parsed_trade.use_case)
    if key in TEMPLATE_NAME_OVERRIDES:
        return TEMPLATE_NAME_OVERRIDES[key]
    return (
        f"{parsed_trade.asset_class}."
        f"{parsed_trade.instrument_type}."
        f"{parsed_trade.use_case}.UPI.V1.json"
    )


def display_template_name(template_name: Optional[str]) -> Optional[str]:
    if not template_name:
        return None
    for suffix in (".UPI.V1.json", ".UPI.V1M2.json", ".UPI.V2.json", ".UPI.json"):
        if template_name.endswith(suffix):
            return template_name[: -len(suffix)]
    return template_name

#找模板文件
def find_product_template(product_definitions_root: Path, template_name: str) -> Optional[Path]:
    if not product_definitions_root.exists():
        return None

    asset_class = template_name.split(".")[0]
    likely_paths = [
        product_definitions_root / "PROD" / "OTC-Products" / "UPI" / asset_class / template_name,
        product_definitions_root / "PROD" / "OTCProducts" / "UPI" / asset_class / template_name,
    ]

    for path in likely_paths:
        if path.exists():
            return path

    matches = list(product_definitions_root.rglob(template_name))
    return matches[0] if matches else None


def _load_codeset(product_definitions_root: Path, codeset_name: str) -> Optional[Set[str]]:
    codeset_file = codeset_name.split("/")[-1]
    codeset_paths = list(product_definitions_root.rglob(codeset_file))
    if not codeset_paths:
        return None

    path = codeset_paths[0]
    if path in CODESET_CACHE:
        return CODESET_CACHE[path]

    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    values: Set[str] = set()
    if isinstance(data, list):
        for item in data:
            if isinstance(item, str):
                values.add(item)
            elif isinstance(item, dict):
                values.update(str(v) for v in item.values() if isinstance(v, str))
    elif isinstance(data, dict):
        enum_values = data.get("enum")
        if isinstance(enum_values, list):
            values.update(str(item) for item in enum_values)
        for value in data.values():
            if isinstance(value, str):
                values.add(value)
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, str):
                        values.add(item)
                    elif isinstance(item, dict):
                        values.update(str(v) for v in item.values() if isinstance(v, str))

    CODESET_CACHE[path] = values
    return values

#检查哪些属性
def _extract_template_attributes(template: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    direct_attributes = template.get("Attributes") or template.get("attributes")
    if isinstance(direct_attributes, dict):
        return direct_attributes

    schema_attributes = (
        template.get("properties", {})
        .get("Attributes", {})
        .get("properties", {})
    )
    return schema_attributes if isinstance(schema_attributes, dict) else {}

#trades.json找对应的值
def _trade_value_for_attribute(raw_trade: Dict[str, Any], attribute_name: str) -> Any:
    candidates = ATTRIBUTE_FIELD_MAP.get(attribute_name, [])
    for field_name in candidates:
        value = raw_trade.get(field_name)
        if value is not None:
            return value
    snake_name = []
    for index, char in enumerate(attribute_name):
        if char.isupper() and index > 0:
            snake_name.append("_")
        snake_name.append(char.lower())
    return raw_trade.get("".join(snake_name))


def _normalise_value(attribute_name: str, value: Any) -> Any:
    return VALUE_ALIASES.get((attribute_name, str(value)), value)


def validate_codesets(
    raw_trade: Dict[str, Any],
    product_definitions_root: Path,
    template: Dict[str, Any],
) -> Tuple[List[str], List[str]]:
    errors: List[str] = []
    warnings: List[str] = []
    attributes = _extract_template_attributes(template)

    for attribute_name, spec in attributes.items():
        if not isinstance(spec, dict):
            continue
        codeset_name = spec.get("codeset") or spec.get("codeSet") or spec.get("$ref")
        enum_values = spec.get("enum")
        if not codeset_name and not enum_values:
            continue

        value = _trade_value_for_attribute(raw_trade, attribute_name)
        if value is None:
            continue

        normalised_value = _normalise_value(attribute_name, value)

        if isinstance(enum_values, list):
            if str(normalised_value) not in {str(item) for item in enum_values}:
                errors.append(f"{attribute_name}={value} is not one of {enum_values}")
            elif normalised_value != value:
                warnings.append(f"{attribute_name}={value} mapped to ANNA-DSB value {normalised_value}")
            continue

        codeset_values = _load_codeset(product_definitions_root, str(codeset_name))
        if codeset_values is None:
            warnings.append(f"Codeset {codeset_name} not found for {attribute_name}")
            continue

        if str(normalised_value) not in codeset_values:
            errors.append(f"{attribute_name}={value} is not in codeset {codeset_name}")
        elif normalised_value != value:
            warnings.append(f"{attribute_name}={value} mapped to ANNA-DSB value {normalised_value}")

        if attribute_name in {"ReferenceRate", "OtherReferenceRate"} and "LIBOR" in str(value):
            warnings.append(f"{attribute_name}={value} is historical LIBOR; kept as a warning, not a hard error")

    return errors, warnings


def lookup_upi_for_trade(
    raw_trade: Dict[str, Any],
    parsed_trade: ParsedTrade,
    product_definitions_root: str,
) -> UpiLookupResult:
    template_name = expected_template_name(parsed_trade)
    root = Path(product_definitions_root)

    if parsed_trade.asset_class in NO_PRODUCT_DEFINITION_CLASSES:
        return UpiLookupResult(
            trade_id=parsed_trade.trade_id,
            status="NO_PRODUCT_DEFINITION",
            template_path=None,
            matched_template=None,
            upi_code=None,
            classification_note=(
                f"Instrument type '{parsed_trade.instrument_type}' under asset class "
                f"'{parsed_trade.asset_class}' has no product definition in the ANNA-DSB OTC UPI taxonomy."
            ),
        )

    if parsed_trade.classification_flag == "CLASSIFICATION_AMBIGUOUS" or not template_name:
        return UpiLookupResult(
            trade_id=parsed_trade.trade_id,
            status="SKIPPED_AMBIGUOUS_CLASSIFICATION",
            template_path=None,
            matched_template=display_template_name(template_name),
            upi_code=raw_trade.get("upi"),
            classification_note="Cannot build UPI template name from incomplete classification fields.",
            validation_errors=["Cannot build UPI template name from incomplete classification fields."],
        )

    if not root.exists():
        return UpiLookupResult(
            trade_id=parsed_trade.trade_id,
            status="PRODUCT_DEFINITIONS_NOT_FOUND",
            template_path=None,
            matched_template=display_template_name(template_name),
            upi_code=raw_trade.get("upi"),
            classification_note=None,
            validation_errors=[f"Product definitions root does not exist: {root}"],
        )

    template_path = find_product_template(root, template_name)
    if template_path is None:
        return UpiLookupResult(
            trade_id=parsed_trade.trade_id,
            status="TEMPLATE_NOT_FOUND",
            template_path=None,
            matched_template=display_template_name(template_name),
            upi_code=raw_trade.get("upi"),
            classification_note=None,
            validation_errors=[f"Expected ANNA-DSB template was not found: {template_name}"],
        )

    with template_path.open("r", encoding="utf-8") as handle:
        template = json.load(handle)

    validation_errors, validation_warnings = validate_codesets(raw_trade, root, template)
    status = "FOUND" if not validation_errors else "FOUND_WITH_VALIDATION_ERRORS"

    return UpiLookupResult(
        trade_id=parsed_trade.trade_id,
        status=status,
        template_path=str(template_path),
        matched_template=display_template_name(template_path.name),
        upi_code=raw_trade.get("upi"),
        classification_note=None,
        validation_errors=validation_errors,
        warnings=validation_warnings,
    )


def lookup_upis(
    raw_trades: List[Dict[str, Any]],
    parsed_trades: List[ParsedTrade],
    product_definitions_root: str,
) -> List[UpiLookupResult]:
    return [
        lookup_upi_for_trade(raw_trade, parsed_trade, product_definitions_root)
        for raw_trade, parsed_trade in zip(raw_trades, parsed_trades)
    ]
