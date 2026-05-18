from pathlib import Path
from typing import Union

from .compliance_checker import check_compliance
from .parser import load_trades, parse_trades
from .upi_lookup import lookup_upis


def run_pipeline(
    input_path: Union[str, Path],
    product_definitions_root: str = "data/product_definitions",
    regimes: list = None,
) -> dict:
    if regimes is None:
        regimes = ["CFTC", "EMIR"]

    raw_trades = load_trades(input_path)
    parsed_trades = parse_trades(raw_trades)
    upi_results = lookup_upis(raw_trades, parsed_trades, product_definitions_root)
    upi_result_dicts = [upi_result.to_dict() for upi_result in upi_results]
    compliance_results = check_compliance(raw_trades, upi_result_dicts, regimes)

    summary = {
        "total_trades": len(parsed_trades),
        "parse_status_counts": {},
        "classification_counts": {},
        "upi_status_counts": {},
        "compliance_status_counts": {},
        "novel_instrument_trade_ids": [],
    }

    for parsed in parsed_trades:
        summary["parse_status_counts"][parsed.parse_status] = (
            summary["parse_status_counts"].get(parsed.parse_status, 0) + 1
        )
        summary["classification_counts"][parsed.classification_flag] = (
            summary["classification_counts"].get(parsed.classification_flag, 0) + 1
        )
        if parsed.classification_flag == "NOVEL_INSTRUMENT_NO_TAXONOMY":
            summary["novel_instrument_trade_ids"].append(parsed.trade_id)

    for upi_result in upi_results:
        summary["upi_status_counts"][upi_result.status] = (
            summary["upi_status_counts"].get(upi_result.status, 0) + 1
        )

    for compliance_result in compliance_results:
        key = f"{compliance_result.regime}:{compliance_result.status}"
        summary["compliance_status_counts"][key] = (
            summary["compliance_status_counts"].get(key, 0) + 1
        )

    return {
        "summary": summary,
        "parsed_trades": [parsed.to_dict() for parsed in parsed_trades],
        "upi_results": upi_result_dicts,
        "compliance_results": [result.to_dict() for result in compliance_results],
    }
