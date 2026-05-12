import unittest
from unittest.mock import patch

from src.compliance_checker import (
    CONDITIONAL,
    NOT_APPLICABLE,
    check_cftc_compliance,
    check_emir_compliance,
    gleif_lookup_enabled,
    lookup_lei_gleif,
    validate_lei,
    validate_trade_leis,
    validate_uti,
)


VALID_LEI = "5493001KJTIIGC8Y1R12"
OTHER_VALID_LEI = "VGRQXHF3J8VDLUA7XE92"


class IdentifierValidationTests(unittest.TestCase):
    def test_validate_lei_accepts_valid_check_digits(self):
        is_valid, message = validate_lei(VALID_LEI)

        self.assertTrue(is_valid)
        self.assertEqual(message, "")

    def test_validate_lei_rejects_invalid_check_digits(self):
        is_valid, message = validate_lei("5493001KJTIIGC8Y1R99")

        self.assertFalse(is_valid)
        self.assertIn("Invalid LEI", message)

    def test_validate_uti_accepts_valid_namespace_and_suffix(self):
        is_valid, message = validate_uti(f"{VALID_LEI}20260301EVT00001", VALID_LEI)

        self.assertTrue(is_valid)
        self.assertEqual(message, "")

    def test_validate_uti_rejects_namespace_mismatch(self):
        is_valid, message = validate_uti(f"{VALID_LEI}20260301EVT00001", OTHER_VALID_LEI)

        self.assertFalse(is_valid)
        self.assertEqual(message, "UTI namespace LEI must match reporting counterparty LEI")

    def test_validate_uti_rejects_bad_suffix_characters(self):
        is_valid, message = validate_uti(f"{VALID_LEI}bad_suffix", VALID_LEI)

        self.assertFalse(is_valid)
        self.assertEqual(message, "UTI suffix must contain only A-Z, 0-9, and hyphen")


class GleifLookupTests(unittest.TestCase):
    def test_gleif_lookup_is_disabled_by_default(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertFalse(gleif_lookup_enabled())

    def test_trade_lei_validation_does_not_call_gleif_when_disabled(self):
        raw_trade = {
            "reporting_counterparty_lei": VALID_LEI,
            "other_counterparty_lei": OTHER_VALID_LEI,
        }

        with patch.dict("os.environ", {}, clear=True):
            with patch("src.compliance_checker.lookup_lei_gleif") as mocked_lookup:
                validate_trade_leis(raw_trade)

        mocked_lookup.assert_not_called()

    def test_lookup_lei_gleif_parses_active_record(self):
        payload = (
            b'{"data":{"attributes":{"entity":{"status":"ACTIVE",'
            b'"legalName":{"name":"Example Bank"}},"registration":{"status":"ISSUED"}}}}'
        )

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def read(self):
                return payload

        with patch("src.compliance_checker.urlopen", return_value=FakeResponse()):
            result = lookup_lei_gleif(VALID_LEI)

        self.assertEqual(result.status, "ACTIVE")
        self.assertEqual(result.entity_status, "ACTIVE")
        self.assertEqual(result.registration_status, "ISSUED")
        self.assertEqual(result.legal_name, "Example Bank")


class EventContractComplianceTests(unittest.TestCase):
    def test_cftc_conditional_for_event_contract_on_cftc_dcm(self):
        raw_trade = {
            "trade_id": "T026",
            "asset_class": "EventContract",
            "platform_type": "CFTC_REGULATED_DCM",
        }

        result = check_cftc_compliance(None, {}, raw_trade)

        self.assertEqual(result.status, CONDITIONAL)
        self.assertEqual(result.regime, "CFTC")

    def test_cftc_not_applicable_for_event_contract_not_on_cftc_dcm(self):
        raw_trade = {
            "trade_id": "T027",
            "asset_class": "EventContract",
            "platform_type": "DECENTRALISED_BLOCKCHAIN_PLATFORM",
        }

        result = check_cftc_compliance(None, {}, raw_trade)

        self.assertEqual(result.status, NOT_APPLICABLE)
        self.assertEqual(result.regime, "CFTC")

    def test_emir_not_applicable_for_event_contract(self):
        raw_trade = {
            "trade_id": "T028",
            "asset_class": "EventContract",
            "platform_type": "CFTC_REGULATED_DCM",
        }

        result = check_emir_compliance(None, {}, raw_trade)

        self.assertEqual(result.status, NOT_APPLICABLE)
        self.assertEqual(result.regime, "EMIR")


if __name__ == "__main__":
    unittest.main()
