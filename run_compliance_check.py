import argparse
import json
from pathlib import Path

from src.pipeline import run_pipeline


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the OTC derivatives compliance engine.")
    parser.add_argument("--input", default="trades.json", help="Path to input trades.json")
    parser.add_argument("--regimes", default="CFTC,EMIR", help="Comma-separated regulatory regimes")
    parser.add_argument("--output", default="outputs/result.json", help="Output JSON path")
    parser.add_argument(
        "--product-definitions",
        default="data/product_definitions",
        help="Path to ANNA-DSB Product-Definitions repository",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    regimes = [regime.strip().upper() for regime in args.regimes.split(",") if regime.strip()]
    result = run_pipeline(args.input, args.product_definitions, regimes)
    result["regimes"] = regimes

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2), encoding="utf-8")

    summary = result["summary"]
    print(f"Loaded {summary['total_trades']} trades")
    print(f"Parse statuses: {summary['parse_status_counts']}")
    print(f"Classifications: {summary['classification_counts']}")
    print(f"Novel instrument trades: {summary['novel_instrument_trade_ids']}")
    print(f"UPI statuses: {summary['upi_status_counts']}")
    print(f"Compliance statuses: {summary['compliance_status_counts']}")
    print(f"Wrote report: {output_path}")


if __name__ == "__main__":
    main()
