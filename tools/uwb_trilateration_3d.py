import argparse
import csv
import math


ANCHOR_KEYS = ["A0", "A1", "A2", "A3"]
RANGE_KEYS = ["d0_cm", "d1_cm", "d2_cm", "d3_cm"]
GAP_KEYS = ["gap0_cdb", "gap1_cdb", "gap2_cdb", "gap3_cdb"]


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def sub(a, b):
    return [x - y for x, y in zip(a, b)]


def norm(v):
    return math.sqrt(dot(v, v))


def solve_3x3(a, b):
    m = [row[:] + [rhs] for row, rhs in zip(a, b)]
    for col in range(3):
        pivot = max(range(col, 3), key=lambda r: abs(m[r][col]))
        if abs(m[pivot][col]) < 1e-12:
            raise ValueError("singular anchor geometry")
        if pivot != col:
            m[col], m[pivot] = m[pivot], m[col]
        div = m[col][col]
        for j in range(col, 4):
            m[col][j] /= div
        for r in range(3):
            if r == col:
                continue
            factor = m[r][col]
            for j in range(col, 4):
                m[r][j] -= factor * m[col][j]
    return [m[i][3] for i in range(3)]


def solve_normal(rows, values, weights=None):
    ata = [[0.0] * 3 for _ in range(3)]
    atb = [0.0] * 3
    if weights is None:
        weights = [1.0] * len(rows)
    for row, value, weight in zip(rows, values, weights):
        for i in range(3):
            atb[i] += weight * row[i] * value
            for j in range(3):
                ata[i][j] += weight * row[i] * row[j]
    return solve_3x3(ata, atb)


def read_anchors(path):
    anchors = {}
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            anchors[row["anchor_id"]] = [
                float(row["x_m"]),
                float(row["y_m"]),
                float(row["z_m"]),
            ]
    missing = [k for k in ANCHOR_KEYS if k not in anchors]
    if missing:
        raise ValueError(f"missing anchors: {', '.join(missing)}")
    return [anchors[k] for k in ANCHOR_KEYS]


def linear_initial_position(anchors, ranges_m):
    p0 = anchors[0]
    r0 = ranges_m[0]
    rows = []
    values = []
    for pi, ri in zip(anchors[1:], ranges_m[1:]):
        rows.append([2.0 * (pi[j] - p0[j]) for j in range(3)])
        values.append(r0 * r0 - ri * ri + dot(pi, pi) - dot(p0, p0))
    return solve_3x3(rows, values)


def quality_weights_from_row(row):
    weights = []
    for key in GAP_KEYS:
        value = row.get(key, "")
        if value == "":
            weights.append(1.0)
            continue
        gap_db = int(float(value)) / 100.0
        if gap_db <= 6.0:
            weights.append(1.0)
        elif gap_db >= 14.0:
            weights.append(0.10)
        else:
            t = (gap_db - 6.0) / 8.0
            weights.append(1.0 - 0.90 * t)
    return weights


def apply_constraints(pos, z_min):
    if z_min is not None and pos[2] < z_min:
        pos = pos[:]
        pos[2] = z_min
    return pos


def refine_position(anchors, ranges_m, x, weights=None, z_min=None):
    def cost(pos):
        if weights is None:
            local_weights = [1.0] * len(anchors)
        else:
            local_weights = weights
        return sum(
            weight * (norm(sub(pos, anchor)) - measured) ** 2
            for anchor, measured, weight in zip(anchors, ranges_m, local_weights)
        )

    x = apply_constraints(x, z_min)
    for _ in range(12):
        rows = []
        values = []
        for anchor, measured in zip(anchors, ranges_m):
            delta = sub(x, anchor)
            predicted = max(norm(delta), 1e-9)
            rows.append([delta[j] / predicted for j in range(3)])
            values.append(measured - predicted)
        try:
            step = solve_normal(rows, values, weights)
        except ValueError:
            break
        old_cost = cost(x)
        accepted = False
        for scale in [1.0, 0.5, 0.25, 0.1, 0.05, 0.01]:
            candidate = apply_constraints([x[j] + step[j] * scale for j in range(3)], z_min)
            if cost(candidate) <= old_cost:
                x = candidate
                accepted = True
                break
        if not accepted:
            break
        if norm([s * scale for s in step]) < 1e-5:
            break
    return x


def residual_stats(anchors, ranges_m, x):
    residuals = []
    for anchor, measured in zip(anchors, ranges_m):
        residuals.append(norm(sub(x, anchor)) - measured)
    rms = math.sqrt(sum(r * r for r in residuals) / len(residuals))
    return residuals, rms


def reconstruct(input_csv, anchors_csv, output_csv, z_min=0.0, use_gap_weights=True):
    anchors = read_anchors(anchors_csv)
    out_rows = []
    with open(input_csv, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if row.get("type", "RANGE4") not in ("RANGE4", "RANGE4D"):
                continue
            ranges_cm = [int(row[k]) for k in RANGE_KEYS]
            if any(v < 0 for v in ranges_cm):
                continue
            ranges_m = [v / 100.0 for v in ranges_cm]
            weights = quality_weights_from_row(row) if use_gap_weights else [1.0, 1.0, 1.0, 1.0]
            try:
                x0 = linear_initial_position(anchors, ranges_m)
                pos = refine_position(anchors, ranges_m, x0, weights=weights, z_min=z_min)
                residuals, rms = residual_stats(anchors, ranges_m, pos)
            except ValueError as exc:
                print(f"skip seq={row.get('seq')}: {exc}")
                continue
            out_rows.append({
                "pc_time": row.get("pc_time", ""),
                "seq": row.get("seq", ""),
                "x_m": f"{pos[0]:.4f}",
                "y_m": f"{pos[1]:.4f}",
                "z_m": f"{pos[2]:.4f}",
                "rms_error_m": f"{rms:.4f}",
                "res_a0_m": f"{residuals[0]:.4f}",
                "res_a1_m": f"{residuals[1]:.4f}",
                "res_a2_m": f"{residuals[2]:.4f}",
                "res_a3_m": f"{residuals[3]:.4f}",
                "w_a0": f"{weights[0]:.3f}",
                "w_a1": f"{weights[1]:.3f}",
                "w_a2": f"{weights[2]:.3f}",
                "w_a3": f"{weights[3]:.3f}",
                "status_hex": row.get("status_hex", ""),
                "pc_ms": row.get("pc_ms", ""),
            })

    fieldnames = [
        "pc_time", "seq", "x_m", "y_m", "z_m", "rms_error_m",
        "res_a0_m", "res_a1_m", "res_a2_m", "res_a3_m",
        "w_a0", "w_a1", "w_a2", "w_a3",
        "status_hex", "pc_ms",
    ]
    with open(output_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(out_rows)
    print(f"wrote {len(out_rows)} rows to {output_csv}")


def main():
    parser = argparse.ArgumentParser(description="Reconstruct 3D tag positions from BU01 RANGE4 distance CSV.")
    parser.add_argument("--input", required=True, help="RANGE4 CSV from uwb_realtime_reader.ps1")
    parser.add_argument("--anchors", default="config/anchor_positions.csv", help="anchor position CSV")
    parser.add_argument("--output", required=True, help="output position CSV")
    parser.add_argument("--z-min", type=float, default=0.0, help="minimum z constraint in meters; default 0.0")
    parser.add_argument("--no-gap-weights", action="store_true", help="disable RANGE4D gap-based quality weights")
    args = parser.parse_args()
    reconstruct(args.input, args.anchors, args.output, z_min=args.z_min, use_gap_weights=not args.no_gap_weights)


if __name__ == "__main__":
    main()
