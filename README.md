# MH6822 OTC Derivatives Compliance Engine

This repository contains a Python compliance engine for Homework 2. It reads a portfolio of OTC derivative trade records, classifies each trade, performs ANNA-DSB template lookup, and checks CFTC and EMIR reporting compliance.

## Quick Start

```bash
pip install -r requirements.txt
python run_compliance_check.py --input trades.json --regimes CFTC,EMIR
```

The main reproducible compliance report is:

```text
outputs/result.json
```

This is the file to use as the baseline compliance report for submission. It is generated without live network dependencies.

## Data and Reports

- `trades.json` contains the final 33-trade portfolio: the original 28 records plus five designed records, T029 to T033.
- `data/new originated trade data/5 new trade raw data.json` contains the five additional raw trade records before they were merged into `trades.json`.
- `data/new originated trade data/5 new trade data.json` contains the teammate's design/expected-output reference for the five additional trades; it is not the formal engine output.
- `outputs/result.json` is the main compliance report generated from the full 33-trade portfolio.
- `outputs/result_gleif.json` is an optional enrichment report generated with live GLEIF lookup enabled.

## Engineer Scope

- Built the modular pipeline connecting parsing, UPI template lookup, compliance checking and JSON report generation.
- Module 1 parses all 33 trades: the original 28 records plus five additional designed trades.
- Conventional derivatives are classified as `CONVENTIONAL_DERIVATIVE`.
- EventContract trades T026, T027, T028, and T030 are classified as `NOVEL_INSTRUMENT_NO_TAXONOMY`.
- Invalid timestamps, dates and ambiguous taxonomies are reported without stopping the pipeline.
- Module 2 matches conventional trades to ANNA-DSB UPI templates and returns `NO_PRODUCT_DEFINITION` for EventContract trades.

## Validation Specialist Scope

Module 3 is implemented in `src/compliance_checker.py`. The validation layer performs:

- LEI validation using `python-stdnum`, including 20-character format and ISO
  7064 MOD 97-10 check digits.
- UTI validation for maximum length, 20-character LEI namespace, namespace match
  with the reporting counterparty LEI, and suffix format.
- ANNA-DSB codeset and UPI-result handling, including template match errors,
  value normalisation warnings and missing product definitions.
- CFTC and EMIR compliance checks with structured `ComplianceFinding` outputs.
- Conventional OTC derivative validation for required fields, timestamps,
  currency codes, notional amount, clearing fields, EMIR collateral/margin
  fields and UPI lookup results.
- EventContract branching before normal OTC derivative validation:
  - T026, T028, and T030: CFTC `CONDITIONAL`, EMIR `NOT_APPLICABLE`
  - T027: CFTC `NOT_APPLICABLE`, EMIR `NOT_APPLICABLE`
- EMIR collateral and margin field checks, including zero-value margin reporting.
- Warning-level findings for review items such as historical reference rates,
  ANNA-DSB value normalisation, offshore EventContract access risk, and uncleared
  cross-border CDS review.

Optional live GLEIF LEI lookup is available as an extension. It is disabled by
default so the baseline engine remains reproducible without network access. To
generate the optional enriched report:

```powershell
$env:ENABLE_GLEIF_LOOKUP="true"
python run_compliance_check.py --input trades.json --regimes CFTC,EMIR --output outputs/result_gleif.json
```

`outputs/result_gleif.json` adds GLEIF active-status findings for LEIs that pass
local syntax and check-digit validation. Because it depends on external API
availability, it is not used as the baseline reproducible report.

To check whether the live lookup succeeded, search the enriched report for:

```text
GLEIF_LEI_ACTIVE
```

If the local environment blocks external API access, the report may instead
contain `GLEIF_LOOKUP_UNAVAILABLE`; this does not affect the baseline
`outputs/result.json` report.

## UPI Scope Note

The engine uses the public ANNA-DSB Product Definitions repository for template
matching and codeset validation. This repository provides schemas, templates and
codesets, but not issued production UPI reference data. Therefore `upi_code`
remains `null` unless supplied in the raw trade input; the engine reports
template match status and validation findings rather than retrieving live issued
UPI identifiers.

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
  result.json
  result_gleif.json
data/
  Product-Definitions-master/
  new originated trade data/
trades.json
```
