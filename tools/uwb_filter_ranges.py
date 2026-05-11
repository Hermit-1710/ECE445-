import argparse
import csv
from pathlib import Path


RANGE_KEYS = ["d0_cm", "d1_cm", "d2_cm", "d3_cm"]


def parse_range(value):
    if value is None or value == "":
        return None
    try:
        distance = int(float(value))
    except ValueError:
        return None
    return distance if distance >= 0 else None


def median(values):
    values = sorted(values)
    mid = len(values) // 2
    if len(values) % 2:
        return values[mid]
    return round((values[mid - 1] + values[mid]) / 2)


def read_rows(path):
    with Path(path).open("r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        return list(reader), reader.fieldnames or []


def mark_range_outliers(values, max_jump_cm, neighborhood):
    valid = [v is not None for v in values]
    for i, value in enumerate(values):
        if value is None:
            continue
        lo = max(0, i - neighborhood)
        hi = min(len(values), i + neighborhood + 1)
        local = [values[j] for j in range(lo, hi) if j != i and values[j] is not None]
        if len(local) < 2:
            continue
        baseline = median(local)
        if abs(value - baseline) > max_jump_cm:
            valid[i] = False
    return valid


def restore_long_invalid_runs(valid, max_interp_run):
    restored = valid[:]
    n = len(restored)
    i = 0
    while i < n:
        if restored[i]:
            i += 1
            continue
        start = i
        while i < n and not restored[i]:
            i += 1
        if (i - start) > max_interp_run:
            for j in range(start, i):
                restored[j] = True
    return restored


def interpolate_values(values, valid):
    repaired = values[:]
    n = len(values)
    for i in range(n):
        if valid[i]:
            continue

        left = i - 1
        while left >= 0 and not valid[left]:
            left -= 1
        right = i + 1
        while right < n and not valid[right]:
            right += 1

        if left >= 0 and right < n:
            ratio = (i - left) / (right - left)
            repaired[i] = round(repaired[left] * (1.0 - ratio) + repaired[right] * ratio)
        elif left >= 0:
            repaired[i] = repaired[left]
        elif right < n:
            repaired[i] = repaired[right]
        else:
            repaired[i] = None
    return repaired


def smooth_values(values, window):
    if window <= 1:
        return values
    radius = window // 2
    smoothed = values[:]
    for i in range(len(values)):
        lo = max(0, i - radius)
        hi = min(len(values), i + radius + 1)
        local = [v for v in values[lo:hi] if v is not None]
        if local:
            smoothed[i] = median(local)
    return smoothed


def filter_ranges(input_csv, output_csv, max_jump_cm, smooth_window, neighborhood, max_interp_run):
    rows, fieldnames = read_rows(input_csv)
    if not rows:
        raise ValueError("input CSV has no data rows")

    missing = [key for key in RANGE_KEYS if key not in fieldnames]
    if missing:
        raise ValueError(f"missing range columns: {', '.join(missing)}")

    if "range_filter_flag" not in fieldnames:
        fieldnames.append("range_filter_flag")

    stats = {}
    for key in RANGE_KEYS:
        values = [parse_range(row.get(key)) for row in rows]
        candidate_valid = mark_range_outliers(values, max_jump_cm, neighborhood)
        valid = restore_long_invalid_runs(candidate_valid, max_interp_run)
        repaired_count = sum(1 for v in valid if not v)
        repaired = interpolate_values(values, valid)
        smoothed = smooth_values(repaired, smooth_window)
        stats[key] = repaired_count

        for row, old, new, is_valid in zip(rows, values, smoothed, valid):
            flags = []
            if row.get("range_filter_flag"):
                flags.append(row["range_filter_flag"])
            if not is_valid:
                flags.append(f"{key}_jump")
            if old is None:
                flags.append(f"{key}_missing")
            row[key] = str(new) if new is not None else "-1"
            row["range_filter_flag"] = "|".join(flags)

    output = Path(output_csv)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    stat_text = ", ".join(f"{key}:{count}" for key, count in stats.items())
    print(f"wrote {len(rows)} rows to {output_csv}; repaired jumps {stat_text}")


def main():
    parser = argparse.ArgumentParser(description="Filter per-anchor UWB range columns before 3D reconstruction.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--max-jump-cm", type=int, default=120, help="maximum allowed jump per anchor range")
    parser.add_argument("--smooth-window", type=int, default=3, help="median smoothing window per range")
    parser.add_argument("--neighborhood", type=int, default=4, help="neighbor radius for local median outlier detection")
    parser.add_argument("--max-interp-run", type=int, default=3, help="only repair isolated range outlier runs up to this length")
    args = parser.parse_args()
    filter_ranges(args.input, args.output, args.max_jump_cm, args.smooth_window, args.neighborhood, args.max_interp_run)


if __name__ == "__main__":
    main()
