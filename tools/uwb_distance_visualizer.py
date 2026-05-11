import argparse
import csv
import sys
from pathlib import Path

from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
import pyqtgraph as pg


RANGE_COLUMNS = ["d0_cm", "d1_cm", "d2_cm", "d3_cm"]
GAP_COLUMNS = ["gap0_cdb", "gap1_cdb", "gap2_cdb", "gap3_cdb"]
COLORS = ["#f4d35e", "#4cc9f0", "#90be6d", "#f94144"]


def parse_int(row, key, default=None):
    value = row.get(key, "")
    if value == "" or value is None:
        return default
    try:
        return int(float(value))
    except ValueError:
        return default


def read_rows(csv_path):
    rows = []
    with Path(csv_path).open("r", newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if row.get("type") not in ("RANGE4", "RANGE4D"):
                continue
            seq = parse_int(row, "seq")
            if seq is None:
                continue
            ranges = [parse_int(row, col, -1) for col in RANGE_COLUMNS]
            gaps = [parse_int(row, col, 0) / 100.0 for col in GAP_COLUMNS]
            rows.append({
                "seq": seq,
                "pc_time": row.get("pc_time", ""),
                "pc_ms": parse_int(row, "pc_ms", 0),
                "status": row.get("status_hex", ""),
                "ranges": ranges,
                "gaps": gaps,
            })
    return rows


class DistanceVisualizer(QMainWindow):
    def __init__(self, csv_path):
        super().__init__()
        self.csv_path = str(csv_path)
        self.rows = []
        self.cursor = 0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.advance_frame)
        self.timer.setInterval(100)

        self.setWindowTitle("BU01 UWB 距离诊断可视化")
        self.resize(1280, 760)
        self.init_ui()
        self.load_csv(self.csv_path)
        self.timer.start()

    def init_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)

        top = QHBoxLayout()
        self.status_label = QLabel("未加载数据")
        self.open_btn = QPushButton("打开 CSV")
        self.open_btn.clicked.connect(self.open_csv)
        self.pause_btn = QPushButton("暂停")
        self.pause_btn.setCheckable(True)
        self.pause_btn.toggled.connect(self.toggle_pause)
        top.addWidget(self.open_btn)
        top.addWidget(self.pause_btn)
        top.addStretch()
        top.addWidget(self.status_label)
        layout.addLayout(top)

        plots = QHBoxLayout()
        self.distance_plot = pg.PlotWidget(title="四路距离 d0-d3，单位 cm")
        self.distance_plot.setLabel("left", "distance", units="cm")
        self.distance_plot.setLabel("bottom", "sample")
        self.distance_plot.addLegend()
        self.distance_plot.showGrid(x=True, y=True, alpha=0.3)
        self.distance_curves = []
        for idx, color in enumerate(COLORS):
            curve = self.distance_plot.plot([], [], pen=pg.mkPen(color, width=2), name=f"A{idx}")
            self.distance_curves.append(curve)
        plots.addWidget(self.distance_plot, stretch=3)

        self.gap_plot = pg.PlotWidget(title="多径/NLOS 指标 gap，单位 dB")
        self.gap_plot.setLabel("left", "gap", units="dB")
        self.gap_plot.setLabel("bottom", "sample")
        self.gap_plot.addLegend()
        self.gap_plot.showGrid(x=True, y=True, alpha=0.3)
        self.gap_plot.addLine(y=10.0, pen=pg.mkPen("#ff7b00", width=1, style=Qt.PenStyle.DashLine))
        self.gap_curves = []
        for idx, color in enumerate(COLORS):
            curve = self.gap_plot.plot([], [], pen=pg.mkPen(color, width=2), name=f"gap{idx}")
            self.gap_curves.append(curve)
        plots.addWidget(self.gap_plot, stretch=2)
        layout.addLayout(plots)

        self.table = QTableWidget(0, 12)
        self.table.setHorizontalHeaderLabels([
            "seq", "pc_time", "pc_ms", "status",
            "d0", "d1", "d2", "d3",
            "gap0", "gap1", "gap2", "gap3",
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table, stretch=1)

    def open_csv(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择 UWB CSV", str(Path(self.csv_path).parent), "CSV Files (*.csv)")
        if path:
            self.load_csv(path)

    def toggle_pause(self, checked):
        if checked:
            self.timer.stop()
            self.pause_btn.setText("继续")
        else:
            self.timer.start()
            self.pause_btn.setText("暂停")

    def load_csv(self, path):
        self.csv_path = path
        self.rows = read_rows(path)
        self.cursor = len(self.rows)
        self.refresh_all()

    def advance_frame(self):
        latest = read_rows(self.csv_path)
        if len(latest) != len(self.rows):
            self.rows = latest
            self.cursor = len(self.rows)
            self.refresh_all()

    def refresh_all(self):
        x = list(range(len(self.rows)))
        for idx, curve in enumerate(self.distance_curves):
            values = [row["ranges"][idx] if row["ranges"][idx] >= 0 else None for row in self.rows]
            curve.setData(x, values)

        for idx, curve in enumerate(self.gap_curves):
            values = [row["gaps"][idx] for row in self.rows]
            curve.setData(x, values)

        self.table.setRowCount(0)
        for row in self.rows[-200:]:
            self.append_table_row(row)

        if self.rows:
            last = self.rows[-1]
            self.status_label.setText(
                f"{Path(self.csv_path).name} | {len(self.rows)} rows | "
                f"last seq={last['seq']} d={last['ranges']} gap={['%.1f' % g for g in last['gaps']]}"
            )
        else:
            self.status_label.setText(f"{Path(self.csv_path).name} | no RANGE4/RANGE4D rows")

    def append_table_row(self, row):
        idx = self.table.rowCount()
        self.table.insertRow(idx)
        values = [
            row["seq"], row["pc_time"], row["pc_ms"], row["status"],
            *row["ranges"],
            *[f"{gap:.2f}" for gap in row["gaps"]],
        ]
        for col, value in enumerate(values):
            item = QTableWidgetItem(str(value))
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(idx, col, item)
        self.table.scrollToBottom()


def main():
    parser = argparse.ArgumentParser(description="Visualize BU01 RANGE4/RANGE4D distance and multipath diagnostics.")
    parser.add_argument("--csv", default="data/a0_tag_diag_test6_bias_minus30.csv", help="CSV file to visualize")
    args = parser.parse_args()

    app = QApplication(sys.argv)
    window = DistanceVisualizer(args.csv)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
