import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, List, Union

from .models import ParsedTrade


CONVENTIONAL_ASSET_CLASSES = {"Rates", "Credit", "FX", "Equity", "Commodities"}
NOVEL_ASSET_CLASSES = {"EventContract"}

ISO_8601_UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

#读取json
def load_trades(path: Union[str, Path]) -> list:
    with Path(path).open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, list):
        raise ValueError("Input JSON is not a list.")
    return data

#给交易分类，判断一笔交易是常规衍生品、特殊新型产品，还是信息不足
def classify_instrument(trade: dict) -> str:
    asset_class = trade.get("asset_class") #module2找到UPI文件要看这三个字段
    instrument_type = trade.get("instrument_type")
    use_case = trade.get("use_case")

    if not asset_class or not instrument_type or not use_case:
        return "CLASSIFICATION_AMBIGUOUS"
    if asset_class in CONVENTIONAL_ASSET_CLASSES:
        return "CONVENTIONAL_DERIVATIVE"
    if asset_class in NOVEL_ASSET_CLASSES:
        return "NOVEL_INSTRUMENT_NO_TAXONOMY"
    return "CLASSIFICATION_AMBIGUOUS"


def _valid_utc_timestamp(value: Any) -> bool:
    if not isinstance(value, str) or not ISO_8601_UTC_RE.match(value):
        return False
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return False
    return True


def _valid_date(value: Any) -> bool:
    if not isinstance(value, str) or not DATE_RE.match(value):
        return False
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return False
    return True


def parse_trade(trade: dict) -> ParsedTrade:
    errors: List[str] = []

    trade_id = trade.get("trade_id")
    asset_class = trade.get("asset_class")
    instrument_type = trade.get("instrument_type")
    use_case = trade.get("use_case")
  #检查有无缺失关键字段，有就添加到error[]里
    if not trade_id:
        errors.append("Missing trade_id")
        trade_id = "UNKNOWN"
    if not asset_class:
        errors.append("Missing asset_class")
    if not instrument_type:
        errors.append("Missing instrument_type")
    if not use_case:
        errors.append("Missing use_case")
 
    classification_flag = classify_instrument(trade)
    if classification_flag == "CLASSIFICATION_AMBIGUOUS":
        errors.append("Could not determine regulatory taxonomy classification")

    if not _valid_utc_timestamp(trade.get("execution_timestamp")):
        errors.append("execution_timestamp must be ISO 8601 UTC, e.g. 2025-05-10T14:22:00Z")

    for date_field in ("effective_date", "maturity_date"):
        if date_field in trade and not _valid_date(trade.get(date_field)):
            errors.append(f"{date_field} must be a valid YYYY-MM-DD date")

    if classification_flag == "NOVEL_INSTRUMENT_NO_TAXONOMY":
        parse_status = "SUCCESS" if not errors else "PARTIAL"#交易能识别，但数据有问题
    elif not asset_class or not instrument_type:
        parse_status = "FAILED"#缺少关键字段
    else:
        parse_status = "SUCCESS" if not errors else "PARTIAL"

    classified_fields = {
        "notional_currency": trade.get("notional_currency"),
        "notional_amount": trade.get("notional_amount"),
        "cleared": trade.get("cleared"),
        "uti": trade.get("uti"),
        "upi": trade.get("upi"),
        "reporting_counterparty_lei": trade.get("reporting_counterparty_lei"),
        "other_counterparty_lei": trade.get("other_counterparty_lei"),
        "execution_timestamp": trade.get("execution_timestamp"),
        "effective_date": trade.get("effective_date"),
        "maturity_date": trade.get("maturity_date"),
    }

    return ParsedTrade(
        trade_id=str(trade_id),
        parse_status=parse_status,
        asset_class=asset_class,
        instrument_type=instrument_type,
        use_case=use_case,
        classification_flag=classification_flag,
        parse_errors=errors,
        classified_fields=classified_fields,
    )


def parse_trades(trades: list) -> list:
    return [parse_trade(trade) for trade in trades]
