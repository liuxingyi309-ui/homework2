from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ParsedTrade:
    trade_id: str
    parse_status: str
    asset_class: Optional[str]
    instrument_type: Optional[str]
    use_case: Optional[str]
    classification_flag: str
    parse_errors: List[str] = field(default_factory=list)
    classified_fields: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class UpiLookupResult:
    trade_id: str
    status: str
    template_path: Optional[str]
    matched_template: Optional[str] = None
    upi_code: Optional[str] = None
    classification_note: Optional[str] = None
    validation_errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ComplianceFinding:
    code: str
    severity: str
    message: str
    field: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ComplianceResult:
    trade_id: str
    regime: str
    status: str
    findings: List[ComplianceFinding] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["findings"] = [finding.to_dict() for finding in self.findings]
        return data
