import argparse
import csv
from pathlib import Path


RANGE_COLUMNS = ["d0_cm", "d1_cm", "d2_cm", "d3_cm"]


def corrected_value(value, bias_cm):
    if value is None or value == "":
        return value
    distance = int(float(value))
    if distance < 0:
        return str(distance)
    return str(distance + bias_cm)


def apply_bias(input_csv, output_csv, bias_cm):
    input_path = Path(input_csv)
    output_path = Path(output_csv)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with input_path.open("r", newline="", encoding="utf-8-sig") as src:
        reader = csv.DictReader(src)
        fieldnames = reader.fieldnames
        if not fieldnames:
            raise ValueError(f"{input_path} has no CSV header")

        missing = [col for col in RANGE_COLUMNS if col not in fieldnames]
        if missing:
            raise ValueError(f"missing range columns: {', '.join(missing)}")

        with output_path.open("w", newline="", encoding="utf-8") as dst:
            writer = csv.DictWriter(dst, fieldnames=fieldnames)
            writer.writeheader()
            count = 0
            for row in reader:
                for col in RANGE_COLUMNS:
                    row[col] = corrected_value(row.get(col), bias_cm)
                writer.writerow(row)
                count += 1

    print(f"wrote {count} rows to {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Apply a constant centimeter bias to UWB d0-d3 range columns.")
    parser.add_argument("--input", required=True, help="input CSV path")
    parser.add_argument("--output", required=True, help="output CSV path")
    parser.add_argument("--bias-cm", type=int, default=-30, help="bias added to d0-d3, default -30")
    args = parser.parse_args()
    apply_bias(args.input, args.output, args.bias_cm)


if __name__ == "__main__":
    main()
