# MH6822 OTC Derivatives Compliance Engine

This repository contains a Python compliance engine for Homework 2. It reads a portfolio of OTC derivative trade records, classifies each trade, and will be extended with UPI lookup and multi-jurisdiction compliance checks.

## Quick Start

```bash
python run_compliance_check.py --input trades.json --regimes CFTC,EMIR --product-definitions data/Product-Definitions-master/Product-Definitions-master
```

The command writes:

```text
outputs/result.json
```

## Current Engineer Scope

- Module 1 parser runs on all 28 trades.
- Conventional derivatives are flagged as `CONVENTIONAL_DERIVATIVE`.
- Event contracts T026 to T028 are flagged as `NOVEL_INSTRUMENT_NO_TAXONOMY`.
- Invalid timestamps and dates are reported as parse errors without crashing the engine.
- Module 2 matches conventional trades to ANNA-DSB UPI templates.
- T026 to T028 return `NO_PRODUCT_DEFINITION`.
- Module 3 checks CFTC and EMIR required fields, LEI, UTI, timestamps, currencies, UPI results, and the event-contract jurisdiction differences.

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

## Next Steps

- Add Module 4 classification notes for T026 to T028.
