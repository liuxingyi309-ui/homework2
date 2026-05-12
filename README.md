# MH6822 OTC Derivatives Compliance Engine

This repository contains a Python compliance engine for Homework 2. It reads a portfolio of OTC derivative trade records, classifies each trade, and will be extended with UPI lookup and multi-jurisdiction compliance checks.

## Quick Start

```bash
python run_compliance_check.py --input trades.json --regimes CFTC,EMIR --product-definitions data/Product-Definitions-master/Product-Definitions-master
```

The output file is:

```text
outputs/result.json
```

## Running Tests

```bash
python -m unittest discover -s tests
```

The Module 3 tests cover LEI validation, UTI namespace validation, and the
EventContract CFTC/EMIR jurisdictional outcomes for T026 to T028.

## Current Engineer Scope

- Module 1 parser runs on all 28 trades.
- Conventional derivatives are flagged as `CONVENTIONAL_DERIVATIVE`.
- Event contracts T026 to T028 are flagged as `NOVEL_INSTRUMENT_NO_TAXONOMY`.
- Invalid timestamps and dates are reported as parse errors without crashing the engine.
- Module 2 matches conventional trades to ANNA-DSB UPI templates.
- T026 to T028 return `NO_PRODUCT_DEFINITION`.

## Module 3 Validation Specialist Updates

Module 3 is implemented in `src/compliance_checker.py`. It now performs:

- LEI validation using `python-stdnum`, including 20-character format and ISO
  7064 MOD 97-10 check digits.
- UTI validation for maximum length, 20-character LEI namespace, namespace match
  with the reporting counterparty LEI, and suffix format.
- CFTC and EMIR compliance checks with structured `ComplianceFinding` outputs.
- Conventional OTC derivative validation for required fields, timestamps,
  currency codes, notional amount, clearing fields, asset-class-specific fields,
  and UPI lookup results.
- EventContract branching before normal OTC derivative validation:
  - T026 and T028: CFTC `CONDITIONAL`, EMIR `NOT_APPLICABLE`
  - T027: CFTC `NOT_APPLICABLE`, EMIR `NOT_APPLICABLE`

Optional live GLEIF LEI lookup is available as an extension. It is disabled by
default so the engine remains reproducible without network access. To enable it:

```bash
ENABLE_GLEIF_LOOKUP=true python run_compliance_check.py --input trades.json --regimes CFTC,EMIR --product-definitions data/Product-Definitions-master/Product-Definitions-master
```

## Project Layout

```text
run_compliance_check.py
src/
  parser.py
  pipeline.py
  models.py
  upi_lookup.py
  compliance_checker.py
outputs/
tests/
trades.json
```
