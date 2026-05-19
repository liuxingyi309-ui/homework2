# Explanation of Orriginated Trade Data (T029-T033)

## Trade Scenarios Overview

The following five trades (T029-T033) represent edge cases and intentional compliance violations for testing derivatives regulatory validation logic:

| Trade ID | Scenario | Description | Asset Classification |
|----------|----------|-------------|----------------------|
| T029 | Missing mandatory reporting fields | Rates swap missing LEI and UTI, causing dual-regime noncompliance | Rates |
| T030 | Legitimate event contract on regulated platform | Sports binary event contract traded on a CFTC-regulated DCM | EventContract |
| T031 | FX forward with incomplete reporting | Missing reporting identifiers and partial margin data | FX |
| T032 | Cross-border uncleared CDS with missing margin | OTC credit derivative missing EMIR-mandated margin fields | Credit |
| T033 | Equity swap with clearing & margin violations | Cross-border OTC equity swap violating mandatory clearing rule | Equity |

## Expected Compliance Results

### T029: Rates Swap With Missing Reporting Fields
- **Asset Class:** Rates Swap
- **Use Case:** Fixed-Float
- **Parse Status:** PARTIAL
- **CFTC Status:** NONCOMPLIANT
  - Missing `reporting_counterparty_lei`
  - Missing `uti`
- **EMIR Status:** NONCOMPLIANT
  - Missing `reporting_counterparty_lei`
  - Missing `initial_margin_posted` and `variation_margin_posted`

### T030: Compliant Event Contract on CFTC DCM
- **Asset Class:** EventContract
- **Use Case:** SportsOutcome
- **CFTC Status:** CONDITIONAL
  - Traded on regulated DCM (Kalshi)
  - Full LEI and UTI provided
- **EMIR Status:** NOT_APPLICABLE

### T031: FX Forward With Reporting Deficiencies
- **Asset Class:** FX Forward
- **Use Case:** EURUSD
- **Parse Status:** PARTIAL
- **CFTC Status:** NONCOMPLIANT
  - Missing LEI and UTI
- **EMIR Status:** NONCOMPLIANT
  - Missing core reporting identifiers

### T032: Cross‑Border Uncleared CDS (Missing Margin)
- **Asset Class:** Credit Swap
- **Use Case:** Corporate
- **Cleared:** No
- **CFTC Status:** COMPLIANT
  - Warning:Missing margin data
- **EMIR Status:** NONCOMPLIANT
  - Missing mandatory margin fields

### T033: Equity Swap With Clearing & Margin Violations
- **Asset Class:** Equity Swap
- **Use Case:** IndexReturn (S&P 500)
- **Cleared:** No
- **CFTC Status:** NONCOMPLIANT
  - Failed mandatory clearing
  - Missing margin
- **EMIR Status:** NONCOMPLIANT
  - Unlawful uncleared trade
  - Missing margin fields

## Summary of Compliance Findings

| Trade | CFTC | EMIR | Primary Issue |
|-------|------|------|---------------|
| T029 | Noncompliant | Noncompliant | Missing LEI, UTI, and margin data |
| T030 | Conditional | Not Applicable | Valid event contract on regulated platform |
| T031 | Noncompliant | Noncompliant | Missing reporting identifiers |
| T032 | Compliant | Noncompliant | Uncleared CDS with no margin |
| T033 | Noncompliant | Noncompliant | Mandatory clearing + margin violations |

## Key Takeaways
1. Missing LEI and UTI cause immediate noncompliance across all regimes.
2. Only trades on fully regulated platforms achieve compliant status.
3. Uncleared cross‑border derivatives almost always violate both CFTC and EMIR.
4. Margin and clearing are the top failure points for OTC products.
