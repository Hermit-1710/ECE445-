import argparse
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONDA = Path(r"E:\Anaconda\Scripts\conda.exe")


def run_step(args, title):
    print(f"\n[{title}] {' '.join(str(a) for a in args)}")
    subprocess.run(args, cwd=ROOT, check=True)


def stem_without_csv(path):
    name = Path(path).name
    return name[:-4] if name.lower().endswith(".csv") else Path(path).stem


def rms_suffix(value):
    return f"rms{value:.2f}".replace(".", "p")


def build_paths(input_csv, filter_z_floor=False, drop_z_floor=False, max_rms_m=0.30):
    stem = stem_without_csv(input_csv)
    if drop_z_floor:
        z_suffix = "zfloor_drop"
    else:
        z_suffix = "zfloor_on" if filter_z_floor else "zfloor_off"
    stem = f"{stem}_{z_suffix}_{rms_suffix(max_rms_m)}"
    data_dir = ROOT / "data"
    return {
        "bias": data_dir / f"{stem}_bias_minus30.csv",
        "range_filtered": data_dir / f"{stem}_bias_minus30_range_filtered.csv",
        "position": data_dir / f"{stem}_position3d_range_filtered_z0_weighted.csv",
        "position_filtered": data_dir / f"{stem}_position3d_range_filtered_z0_weighted_filtered.csv",
    }


def process(args):
    input_csv = Path(args.input)
    if not input_csv.is_absolute():
        input_csv = ROOT / input_csv
    paths = build_paths(input_csv, args.filter_z_floor, args.drop_z_floor, args.position_max_rms_m)

    python = sys.executable

    run_step([
        python,
        str(ROOT / "tools" / "uwb_apply_range_bias.py"),
        "--input", str(input_csv),
        "--output", str(paths["bias"]),
        "--bias-cm", str(args.bias_cm),
    ], "1/4 apply range bias")

    run_step([
        python,
        str(ROOT / "tools" / "uwb_filter_ranges.py"),
        "--input", str(paths["bias"]),
        "--output", str(paths["range_filtered"]),
        "--max-jump-cm", str(args.range_max_jump_cm),
        "--smooth-window", str(args.range_smooth_window),
        "--neighborhood", str(args.range_neighborhood),
        "--max-interp-run", str(args.range_max_interp_run),
    ], "2/4 filter ranges")

    run_step([
        python,
        str(ROOT / "tools" / "uwb_trilateration_3d.py"),
        "--input", str(paths["range_filtered"]),
        "--anchors", str(args.anchors),
        "--output", str(paths["position"]),
        "--z-min", str(args.z_min),
    ], "3/4 reconstruct 3D")

    run_step([
        python,
        str(ROOT / "tools" / "uwb_filter_positions.py"),
        "--input", str(paths["position"]),
        "--output", str(paths["position_filtered"]),
        "--max-step-m", str(args.position_max_step_m),
        "--max-rms-m", str(args.position_max_rms_m),
        "--rms-local-neighborhood", str(args.rms_local_neighborhood),
        "--rms-local-ratio", str(args.rms_local_ratio),
        "--rms-local-delta-m", str(args.rms_local_delta_m),
        "--rms-local-min-m", str(args.rms_local_min_m),
        "--smooth-window", str(args.position_smooth_window),
        "--z-drop-step-m", str(args.z_drop_step_m),
        "--neighborhood", str(args.position_neighborhood),
        "--max-interp-run", str(args.position_max_interp_run),
        "--max-speed-mps", str(args.max_speed_mps),
        "--max-accel-mps2", str(args.max_accel_mps2),
        "--alpha", str(args.alpha),
        "--beta", str(args.beta),
    ] + (["--filter-z-floor"] if args.filter_z_floor else []) + (["--drop-z-floor"] if args.drop_z_floor else []), "4/4 filter 3D positions")

    print("\nOutputs:")
    for key, value in paths.items():
        print(f"  {key}: {value}")

    if args.no_view:
        print("\nVisualization command:")
        print(
            f"&{args.conda} run -n {args.env} python .\\tools\\uwb_trajectory_visualizer.py "
            f"--positions .\\data\\{paths['position_filtered'].name} "
            f"--anchors {args.anchors} --interval-ms {args.interval_ms}"
        )
        return

    run_step([
        str(args.conda),
        "run",
        "-n",
        args.env,
        "python",
        str(ROOT / "tools" / "uwb_trajectory_visualizer.py"),
        "--positions", str(paths["position_filtered"]),
        "--anchors", str(args.anchors),
        "--interval-ms", str(args.interval_ms),
    ], "open visualization")


def main():
    parser = argparse.ArgumentParser(description="One-click BU01 UWB CSV processing and trajectory visualization.")
    parser.add_argument("--input", required=True, help="raw RANGE4D CSV")
    parser.add_argument("--anchors", default=str(ROOT / "config" / "anchor_positions.csv"))
    parser.add_argument("--bias-cm", type=int, default=-30)
    parser.add_argument("--range-max-jump-cm", type=int, default=220)
    parser.add_argument("--range-smooth-window", type=int, default=1)
    parser.add_argument("--range-neighborhood", type=int, default=4)
    parser.add_argument("--range-max-interp-run", type=int, default=3)
    parser.add_argument("--z-min", type=float, default=0.0)
    parser.add_argument("--position-max-step-m", type=float, default=1.20)
    parser.add_argument("--position-max-rms-m", type=float, default=0.30)
    parser.add_argument("--rms-local-neighborhood", type=int, default=10)
    parser.add_argument("--rms-local-ratio", type=float, default=3.0)
    parser.add_argument("--rms-local-delta-m", type=float, default=0.08)
    parser.add_argument("--rms-local-min-m", type=float, default=0.12)
    parser.add_argument("--position-smooth-window", type=int, default=3)
    parser.add_argument("--position-neighborhood", type=int, default=4)
    parser.add_argument("--position-max-interp-run", type=int, default=3)
    parser.add_argument("--max-speed-mps", type=float, default=3.0)
    parser.add_argument("--max-accel-mps2", type=float, default=18.0)
    parser.add_argument("--alpha", type=float, default=0.45)
    parser.add_argument("--beta", type=float, default=0.08)
    parser.add_argument("--filter-z-floor", action="store_true")
    parser.add_argument("--drop-z-floor", action="store_true")
    parser.add_argument("--z-drop-step-m", type=float, default=0.20)
    parser.add_argument("--interval-ms", type=int, default=100)
    parser.add_argument("--env", default="uwb_vis")
    parser.add_argument("--conda", default=str(DEFAULT_CONDA))
    parser.add_argument("--no-view", action="store_true", help="process only; print visualization command")
    args = parser.parse_args()
    process(args)


if __name__ == "__main__":
    main()
