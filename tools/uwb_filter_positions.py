import argparse
import csv
import math
from pathlib import Path


POSITION_KEYS = ["x_m", "y_m", "z_m"]


def distance(a, b):
    return math.sqrt(sum((a[k] - b[k]) ** 2 for k in POSITION_KEYS))


def read_rows(path):
    rows = []
    with Path(path).open("r", newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            try:
                for key in POSITION_KEYS:
                    row[key] = float(row[key])
                row["rms_error_m"] = float(row.get("rms_error_m", 0.0))
                row["raw_rms_error_m"] = row["rms_error_m"]
                row["seq_int"] = int(row.get("seq", len(rows)))
                row["pc_ms_int"] = int(float(row.get("pc_ms", len(rows) * 100)))
            except ValueError:
                continue
            row["filtered_flag"] = ""
            rows.append(row)
    return rows


def drop_z_floor_rows(rows, z_floor_epsilon):
    kept = []
    dropped = 0
    for row in rows:
        if row["z_m"] <= z_floor_epsilon:
            dropped += 1
            continue
        kept.append(row)
    return kept, dropped


def append_flag(row, reason):
    row["filtered_flag"] = (row.get("filtered_flag", "") + "|" + reason).strip("|")


def mark_absolute_rms_outliers(rows, max_rms_m):
    valid = [True] * len(rows)
    for i, row in enumerate(rows):
        if row["rms_error_m"] > max_rms_m:
            valid[i] = False
            append_flag(row, "rms_abs")
    return valid


def mark_local_rms_outliers(rows, seed_valid, neighborhood, ratio, delta_m, min_rms_m):
    valid = [True] * len(rows)
    for i, row in enumerate(rows):
        if not seed_valid[i]:
            valid[i] = False
            continue

        lo = max(0, i - neighborhood)
        hi = min(len(rows), i + neighborhood + 1)
        neighbors = [rows[j]["rms_error_m"] for j in range(lo, hi) if j != i and seed_valid[j]]
        if len(neighbors) < 4:
            continue

        local_median = median(neighbors)
        if (
            row["rms_error_m"] >= min_rms_m
            and row["rms_error_m"] - local_median >= delta_m
            and row["rms_error_m"] >= local_median * ratio
        ):
            valid[i] = False
            append_flag(row, "rms_local")
    return valid


def mark_outliers(rows, max_step_m, z_floor_epsilon, z_drop_step_m, neighborhood, filter_z_floor, seed_valid):
    valid = [True] * len(rows)

    for i, row in enumerate(rows):
        if not seed_valid[i]:
            valid[i] = False
            continue
        reasons = []
        lo = max(0, i - neighborhood)
        hi = min(len(rows), i + neighborhood + 1)
        neighbors = [rows[j] for j in range(lo, hi) if j != i and seed_valid[j]]
        if len(neighbors) < 2:
            continue

        median_pos = {
            key: median([n[key] for n in neighbors])
            for key in POSITION_KEYS
        }
        local_step = distance(row, median_pos)

        if local_step > max_step_m:
            reasons.append("isolated_jump")

        neighbor_z = median([n["z_m"] for n in neighbors])
        if filter_z_floor and row["z_m"] <= z_floor_epsilon and neighbor_z > z_drop_step_m:
            reasons.append("isolated_z_floor")

        if reasons:
            valid[i] = False
            for reason in reasons:
                append_flag(row, reason)

    return valid


def dt_seconds(a, b, fallback_dt):
    dt_ms = b["pc_ms_int"] - a["pc_ms_int"]
    if dt_ms <= 0:
        return fallback_dt
    return dt_ms / 1000.0


def previous_valid_index(valid, start):
    i = start
    while i >= 0:
        if valid[i]:
            return i
        i -= 1
    return None


def next_valid_index(valid, start):
    i = start
    while i < len(valid):
        if valid[i]:
            return i
        i += 1
    return None


def mark_motion_outliers(rows, max_speed_mps, max_accel_mps2, z_floor_epsilon, z_drop_step_m, fallback_dt, filter_z_floor, seed_valid):
    valid = [True] * len(rows)
    if len(rows) < 3:
        return valid

    for i in range(1, len(rows) - 1):
        if not seed_valid[i]:
            valid[i] = False
            continue
        prev_i = previous_valid_index(seed_valid, i - 1)
        next_i = next_valid_index(seed_valid, i + 1)
        if prev_i is None or next_i is None:
            continue

        prev_row = rows[prev_i]
        row = rows[i]
        next_row = rows[next_i]
        reasons = []

        dt_prev = dt_seconds(prev_row, row, fallback_dt)
        dt_next = dt_seconds(row, next_row, fallback_dt)
        v_prev = distance(prev_row, row) / max(dt_prev, 1e-6)
        v_next = distance(row, next_row) / max(dt_next, 1e-6)
        v_bridge = distance(prev_row, next_row) / max(dt_prev + dt_next, 1e-6)

        # A spike is a point that requires unrealistic speed into and out of it,
        # while its two neighbors remain physically close to each other.
        if v_prev > max_speed_mps and v_next > max_speed_mps and v_bridge <= max_speed_mps:
            reasons.append("speed_spike")

        accel = abs(v_next - v_prev) / max((dt_prev + dt_next) / 2.0, 1e-6)
        if accel > max_accel_mps2 and v_bridge <= max_speed_mps:
            reasons.append("accel_spike")

        neighbor_z = (prev_row["z_m"] + next_row["z_m"]) / 2.0
        if filter_z_floor and row["z_m"] <= z_floor_epsilon and neighbor_z > z_drop_step_m:
            reasons.append("z_floor_spike")

        if reasons:
            valid[i] = False
            for reason in dict.fromkeys(reasons):
                append_flag(row, reason)

    return valid


def repair_invalid(rows, valid, max_interp_run):
    n = len(rows)
    i = 0
    repaired_count = 0
    long_repaired_count = 0

    while i < n:
        if valid[i]:
            i += 1
            continue
        start = i
        while i < n and not valid[i]:
            i += 1
        end = i
        if (end - start) > max_interp_run:
            for j in range(start, end):
                append_flag(rows[j], "long_interp")
                interpolate_one(rows, valid, j)
                long_repaired_count += 1
                repaired_count += 1
            continue

        for j in range(start, end):
            interpolate_one(rows, valid, j)
            repaired_count += 1

    return rows, repaired_count, long_repaired_count


def interpolate_one(rows, valid, i):
        n = len(rows)
        left = i - 1
        while left >= 0 and not valid[left]:
            left -= 1
        right = i + 1
        while right < n and not valid[right]:
            right += 1

        if left >= 0 and right < n:
            span = right - left
            ratio = (i - left) / span
            for key in POSITION_KEYS:
                rows[i][key] = rows[left][key] * (1.0 - ratio) + rows[right][key] * ratio
            rows[i]["rms_error_m"] = rows[left]["rms_error_m"] * (1.0 - ratio) + rows[right]["rms_error_m"] * ratio
            append_flag(rows[i], "interp")
        elif left >= 0:
            for key in POSITION_KEYS:
                rows[i][key] = rows[left][key]
            rows[i]["rms_error_m"] = rows[left]["rms_error_m"]
            append_flag(rows[i], "hold_prev")
        elif right < n:
            for key in POSITION_KEYS:
                rows[i][key] = rows[right][key]
            rows[i]["rms_error_m"] = rows[right]["rms_error_m"]
            append_flag(rows[i], "hold_next")


def median(values):
    values = sorted(values)
    mid = len(values) // 2
    if len(values) % 2:
        return values[mid]
    return (values[mid - 1] + values[mid]) / 2.0


def smooth_rows(rows, window):
    if window <= 1:
        return
    radius = window // 2
    original = [{key: row[key] for key in POSITION_KEYS} for row in rows]

    for i, row in enumerate(rows):
        lo = max(0, i - radius)
        hi = min(len(rows), i + radius + 1)
        for key in POSITION_KEYS:
            row[key] = median([original[j][key] for j in range(lo, hi)])


def alpha_beta_smooth(rows, alpha, beta):
    if not rows:
        return
    pos = {key: rows[0][key] for key in POSITION_KEYS}
    vel = {key: 0.0 for key in POSITION_KEYS}
    last_t = rows[0]["pc_ms_int"]

    for row in rows:
        dt = max((row["pc_ms_int"] - last_t) / 1000.0, 0.05)
        last_t = row["pc_ms_int"]

        for key in POSITION_KEYS:
            pred = pos[key] + vel[key] * dt
            residual = row[key] - pred
            pos[key] = pred + alpha * residual
            vel[key] = vel[key] + (beta * residual / dt)
            row[key] = pos[key]


def clamp_z(rows, z_min):
    for row in rows:
        if row["z_m"] < z_min:
            row["z_m"] = z_min


def write_rows(rows, output_path):
    if not rows:
        raise ValueError("no rows to write")

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [k for k in rows[0].keys() if k != "seq_int"]
    fieldnames = [k for k in fieldnames if k != "pc_ms_int"]
    for extra in ["filtered_flag"]:
        if extra not in fieldnames:
            fieldnames.append(extra)

    with output.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            out = row.copy()
            out.pop("seq_int", None)
            out.pop("pc_ms_int", None)
            for key in POSITION_KEYS:
                out[key] = f"{out[key]:.4f}"
            if isinstance(out.get("rms_error_m"), float):
                out["rms_error_m"] = f"{out['rms_error_m']:.4f}"
            if isinstance(out.get("raw_rms_error_m"), float):
                out["raw_rms_error_m"] = f"{out['raw_rms_error_m']:.4f}"
            writer.writerow(out)


def merge_valid_masks(*masks):
    if not masks:
        return []
    merged = [True] * len(masks[0])
    for mask in masks:
        for i, value in enumerate(mask):
            merged[i] = merged[i] and value
    return merged


def mark_z_floor_outliers(rows, z_floor_epsilon):
    valid = [True] * len(rows)
    for i, row in enumerate(rows):
        if row["z_m"] <= z_floor_epsilon:
            valid[i] = False
            row["filtered_flag"] = (row.get("filtered_flag", "") + "|z_floor").strip("|")
    return valid


def filter_positions(input_csv, output_csv, max_step_m, max_rms_m, smooth_window, z_floor_epsilon, z_drop_step_m, neighborhood, max_interp_run, max_speed_mps, max_accel_mps2, fallback_dt, alpha, beta, filter_z_floor, drop_z_floor, rms_local_neighborhood, rms_local_ratio, rms_local_delta_m, rms_local_min_m):
    rows = read_rows(input_csv)
    dropped_count = 0
    if drop_z_floor:
        rows, dropped_count = drop_z_floor_rows(rows, z_floor_epsilon)

    rms_valid = mark_absolute_rms_outliers(rows, max_rms_m)
    rms_local_valid = mark_local_rms_outliers(rows, rms_valid, rms_local_neighborhood, rms_local_ratio, rms_local_delta_m, rms_local_min_m)
    rms_seed_valid = merge_valid_masks(rms_valid, rms_local_valid)
    local_valid = mark_outliers(rows, max_step_m, z_floor_epsilon, z_drop_step_m, neighborhood, filter_z_floor, rms_seed_valid)
    local_seed_valid = merge_valid_masks(rms_seed_valid, local_valid)
    motion_valid = mark_motion_outliers(rows, max_speed_mps, max_accel_mps2, z_floor_epsilon, z_drop_step_m, fallback_dt, filter_z_floor, local_seed_valid)
    motion_seed_valid = merge_valid_masks(local_seed_valid, motion_valid)
    rms_second_valid = mark_local_rms_outliers(rows, motion_seed_valid, rms_local_neighborhood, rms_local_ratio, rms_local_delta_m, rms_local_min_m)
    masks = [rms_valid, rms_local_valid, local_valid, motion_valid, rms_second_valid]
    if filter_z_floor:
        masks.append(mark_z_floor_outliers(rows, z_floor_epsilon))
    valid = merge_valid_masks(*masks)
    rows, repaired_count, long_repaired_count = repair_invalid(rows, valid, max_interp_run)
    smooth_rows(rows, smooth_window)
    if alpha > 0.0:
        alpha_beta_smooth(rows, alpha, beta)
    clamp_z(rows, 0.0)
    write_rows(rows, output_csv)
    print(f"wrote {len(rows)} rows to {output_csv}; repaired {repaired_count} outliers; long_repaired {long_repaired_count}; dropped_z_floor {dropped_count}")


def main():
    parser = argparse.ArgumentParser(description="Filter reconstructed UWB 3D positions for smoother visualization.")
    parser.add_argument("--input", required=True, help="input 3D position CSV")
    parser.add_argument("--output", required=True, help="filtered output CSV")
    parser.add_argument("--max-step-m", type=float, default=0.45, help="maximum allowed frame-to-frame step")
    parser.add_argument("--max-rms-m", type=float, default=0.30, help="maximum allowed reconstruction RMS")
    parser.add_argument("--rms-local-neighborhood", type=int, default=10, help="neighbor radius for local RMS outlier detection")
    parser.add_argument("--rms-local-ratio", type=float, default=3.0, help="mark RMS as local outlier when it is this many times local median")
    parser.add_argument("--rms-local-delta-m", type=float, default=0.08, help="minimum RMS increase over local median")
    parser.add_argument("--rms-local-min-m", type=float, default=0.12, help="minimum RMS to consider local RMS outlier")
    parser.add_argument("--smooth-window", type=int, default=5, help="median smoothing window size")
    parser.add_argument("--z-floor-epsilon", type=float, default=0.02, help="z values below this are treated as floor")
    parser.add_argument("--z-drop-step-m", type=float, default=0.12, help="mark sudden drops to floor from above this z")
    parser.add_argument("--neighborhood", type=int, default=4, help="neighbor radius for isolated outlier detection")
    parser.add_argument("--max-interp-run", type=int, default=3, help="only repair isolated runs up to this length")
    parser.add_argument("--max-speed-mps", type=float, default=3.0, help="speed gate for walk mode")
    parser.add_argument("--max-accel-mps2", type=float, default=18.0, help="acceleration gate for walk mode")
    parser.add_argument("--fallback-dt", type=float, default=0.1, help="fallback sample interval in seconds")
    parser.add_argument("--alpha", type=float, default=0.45, help="alpha-beta smoothing position gain; 0 disables")
    parser.add_argument("--beta", type=float, default=0.08, help="alpha-beta smoothing velocity gain")
    parser.add_argument("--filter-z-floor", action="store_true", help="treat z close to 0 as invalid and repair it")
    parser.add_argument("--drop-z-floor", action="store_true", help="drop every row with z close to 0 before smoothing")
    args = parser.parse_args()

    filter_positions(
        args.input,
        args.output,
        args.max_step_m,
        args.max_rms_m,
        args.smooth_window,
        args.z_floor_epsilon,
        args.z_drop_step_m,
        args.neighborhood,
        args.max_interp_run,
        args.max_speed_mps,
        args.max_accel_mps2,
        args.fallback_dt,
        args.alpha,
        args.beta,
        args.filter_z_floor,
        args.drop_z_floor,
        args.rms_local_neighborhood,
        args.rms_local_ratio,
        args.rms_local_delta_m,
        args.rms_local_min_m,
    )


if __name__ == "__main__":
    main()
