import argparse
import csv
import subprocess
import sys
from pathlib import Path

import numpy as np
from PyQt6.QtCore import QEvent, QPointF, QTimer, Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
import pyqtgraph.opengl as gl
from pyqtgraph import Vector


ROOT = Path(__file__).resolve().parents[1]

FILTER_MODES = {
    "慢走: v<=2m/s, a<=3m/s^2": {"speed": 2.0, "accel": 3.0, "alpha": 0.42, "beta": 0.06},
    "跑步: v<=6m/s, a<=6m/s^2": {"speed": 6.0, "accel": 6.0, "alpha": 0.45, "beta": 0.08},
    "快跑: v<=8m/s, a<=8m/s^2": {"speed": 8.0, "accel": 8.0, "alpha": 0.48, "beta": 0.09},
    "球: v<=35m/s, a<=30m/s^2": {"speed": 35.0, "accel": 30.0, "alpha": 0.55, "beta": 0.12},
}


def read_anchor_positions(path):
    anchors = []
    with Path(path).open("r", newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            anchors.append({
                "id": row["anchor_id"],
                "pos": [float(row["x_m"]), float(row["y_m"]), float(row["z_m"])],
            })
    return anchors


def write_anchor_positions(path, anchors):
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["anchor_id", "x_m", "y_m", "z_m"])
        writer.writeheader()
        for anchor in anchors:
            x, y, z = anchor["pos"]
            writer.writerow({
                "anchor_id": anchor["id"],
                "x_m": f"{x:.4f}",
                "y_m": f"{y:.4f}",
                "z_m": f"{z:.4f}",
            })


def read_positions(path):
    rows = []
    with Path(path).open("r", newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            try:
                rows.append({
                    "idx": len(rows),
                    "pc_time": row.get("pc_time", ""),
                    "seq": int(row.get("seq", 0)),
                    "pc_ms": int(float(row.get("pc_ms", len(rows) * 100))),
                    "x": float(row["x_m"]),
                    "y": float(row["y_m"]),
                    "z": float(row["z_m"]),
                    "rms": float(row["rms_error_m"]),
                })
            except (KeyError, ValueError):
                continue
    return rows


def csv_stem(path):
    path = Path(path)
    return path.name[:-4] if path.name.lower().endswith(".csv") else path.stem


def rms_suffix(value):
    return f"rms{value:.2f}".replace(".", "p")


def trajectory_colors(count):
    if count <= 0:
        return np.empty((0, 4), dtype=float)
    t = np.linspace(0.0, 1.0, count)
    start = np.array([1.0, 0.96, 0.68, 0.45])
    end = np.array([1.0, 0.28, 0.02, 1.0])
    return start + (end - start) * t[:, None]


class AnchorConfigDialog(QDialog):
    def __init__(self, anchors, parent=None):
        super().__init__(parent)
        self.setWindowTitle("设置锚点坐标")
        self.inputs = {}

        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)

        for anchor in anchors:
            row = QHBoxLayout()
            boxes = []
            for axis, value in zip(("x", "y", "z"), anchor["pos"]):
                box = QDoubleSpinBox()
                box.setRange(-100.0, 100.0)
                box.setDecimals(4)
                box.setSingleStep(0.05)
                box.setValue(value)
                box.setSuffix(f" {axis}")
                row.addWidget(box)
                boxes.append(box)
            self.inputs[anchor["id"]] = boxes
            form.addRow(anchor["id"], row)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_anchors(self):
        return [
            {"id": anchor_id, "pos": [box.value() for box in boxes]}
            for anchor_id, boxes in self.inputs.items()
        ]


class TrajectoryVisualizer(QMainWindow):
    def __init__(self, position_csv, anchor_csv, interval_ms):
        super().__init__()
        self.position_csv = str(position_csv)
        self.anchor_csv = str(anchor_csv)
        self.all_positions = []
        self.visible_positions = []
        self.anchors = []
        self.anchor_labels = []
        self.play_index = 0
        self.selected_item = gl.GLScatterPlotItem(size=22, color=(0.1, 0.45, 1.0, 1.0))

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.advance_one_point)
        self.timer.setInterval(interval_ms)

        self.setWindowTitle("BU01 UWB 三维轨迹可视化")
        self.resize(1480, 880)
        self.init_ui(interval_ms)
        self.load_all()
        self.timer.start()

    def init_ui(self, interval_ms):
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)

        top = QHBoxLayout()
        self.open_btn = QPushButton("打开3D坐标")
        self.open_btn.clicked.connect(self.open_position_csv)

        self.anchor_btn = QPushButton("设置锚点坐标")
        self.anchor_btn.clicked.connect(self.open_anchor_config)

        self.import_raw_btn = QPushButton("导入原始数据并显示")
        self.import_raw_btn.clicked.connect(self.open_raw_csv_and_process)

        self.mode_box = QComboBox()
        self.mode_box.addItems(FILTER_MODES.keys())

        self.rms_box = QDoubleSpinBox()
        self.rms_box.setRange(0.05, 2.0)
        self.rms_box.setDecimals(2)
        self.rms_box.setSingleStep(0.05)
        self.rms_box.setValue(0.30)
        self.rms_box.setSuffix(" m")

        self.filter_z0_box = QCheckBox("过滤 z=0 点")
        self.filter_z0_box.setChecked(True)

        self.drop_z0_box = QCheckBox("删除全部 z=0 点")
        self.drop_z0_box.setChecked(False)

        self.pause_btn = QPushButton("暂停播放")
        self.pause_btn.setCheckable(True)
        self.pause_btn.toggled.connect(self.toggle_pause)

        self.replay_btn = QPushButton("从头播放")
        self.replay_btn.clicked.connect(self.restart_playback)

        self.show_all_btn = QPushButton("一键显示全部轨迹")
        self.show_all_btn.clicked.connect(self.show_all_trajectory)

        self.index_box = QSpinBox()
        self.index_box.setRange(0, 1000000)
        self.index_box.setSingleStep(1)
        self.index_btn = QPushButton("定位idx")
        self.index_btn.clicked.connect(self.locate_index)

        self.seq_box = QSpinBox()
        self.seq_box.setRange(0, 255)
        self.seq_box.setSingleStep(1)
        self.seq_btn = QPushButton("定位seq")
        self.seq_btn.clicked.connect(self.locate_sequence)

        self.interval_box = QSpinBox()
        self.interval_box.setRange(10, 2000)
        self.interval_box.setSingleStep(10)
        self.interval_box.setValue(interval_ms)
        self.interval_box.setSuffix(" ms/点")
        self.interval_box.valueChanged.connect(self.timer.setInterval)

        self.status_label = QLabel("准备加载")

        for widget in [
            self.open_btn,
            self.anchor_btn,
            self.import_raw_btn,
            QLabel("滤波模式:"),
            self.mode_box,
            QLabel("RMS阈值:"),
            self.rms_box,
            self.filter_z0_box,
            self.drop_z0_box,
            self.pause_btn,
            self.replay_btn,
            self.show_all_btn,
            QLabel("Idx:"),
            self.index_box,
            self.index_btn,
            QLabel("Seq:"),
            self.seq_box,
            self.seq_btn,
            QLabel("播放速度:"),
            self.interval_box,
        ]:
            top.addWidget(widget)
        top.addStretch()
        top.addWidget(self.status_label)
        layout.addLayout(top)

        content = QHBoxLayout()
        self.view = gl.GLViewWidget()
        self.view.setBackgroundColor("#101418")
        self.view.setCameraPosition(distance=8, elevation=28, azimuth=-135)
        content.addWidget(self.view, stretch=3)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["idx", "seq", "x", "y", "z", "rms", "time"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.cellClicked.connect(self.on_table_cell_clicked)
        content.addWidget(self.table, stretch=1)
        layout.addLayout(content)

        self.view.addItem(gl.GLAxisItem(size=Vector(4.5, 4.5, 2.0)))

        self.ground_item = gl.GLGridItem()
        self.ground_item.setSize(4.5, 4.5)
        self.ground_item.setSpacing(0.5, 0.5)
        self.view.addItem(self.ground_item)

        self.anchor_item = gl.GLScatterPlotItem(size=12, color=(0.25, 0.70, 1.0, 1.0))
        self.path_item = gl.GLLinePlotItem(color=(1.0, 0.92, 0.55, 0.85), width=2)
        self.start_item = gl.GLScatterPlotItem(size=22, color=(0.1, 0.9, 0.25, 1.0))
        self.ball_item = gl.GLScatterPlotItem(size=22, color=(1.0, 0.1, 0.1, 1.0))
        self.shadow_item = gl.GLScatterPlotItem(size=5, color=(0.55, 0.55, 0.55, 0.45))

        for item in [self.anchor_item, self.path_item, self.shadow_item, self.start_item, self.ball_item]:
            self.view.addItem(item)
        self.view.addItem(self.selected_item)
        self.original_mouse_press_event = self.view.mousePressEvent
        self.original_mouse_move_event = self.view.mouseMoveEvent
        self.view.mousePressEvent = self.on_view_mouse_press
        self.view.mouseMoveEvent = self.on_view_mouse_move

    def open_anchor_config(self):
        self.anchors = read_anchor_positions(self.anchor_csv)
        dialog = AnchorConfigDialog(self.anchors, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.anchors = dialog.get_anchors()
        write_anchor_positions(self.anchor_csv, self.anchors)
        self.refresh_anchors()
        QMessageBox.information(self, "锚点已更新", f"已保存到:\n{self.anchor_csv}\n后续导入原始数据会使用新坐标重建。")

    def open_position_csv(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择3D坐标CSV", str(Path(self.position_csv).parent), "CSV Files (*.csv)")
        if path:
            self.position_csv = path
            self.load_all()

    def open_raw_csv_and_process(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择原始RANGE4D数据CSV", str(ROOT / "data"), "CSV Files (*.csv)")
        if not path:
            return
        try:
            output = self.process_raw_csv(Path(path))
        except subprocess.CalledProcessError as exc:
            QMessageBox.critical(self, "处理失败", f"处理脚本返回错误:\n{exc}")
            return
        except Exception as exc:
            QMessageBox.critical(self, "处理失败", str(exc))
            return

        self.position_csv = str(output)
        self.load_all()
        QMessageBox.information(self, "处理完成", f"已生成并加载:\n{output}")

    def process_raw_csv(self, raw_csv):
        self.anchors = read_anchor_positions(self.anchor_csv)
        mode_name = self.mode_box.currentText()
        mode = FILTER_MODES[mode_name]
        safe_mode = mode_name.split(":")[0]
        max_rms_m = self.rms_box.value()
        if self.drop_z0_box.isChecked():
            z_suffix = "zfloor_drop"
        else:
            z_suffix = "zfloor_on" if self.filter_z0_box.isChecked() else "zfloor_off"
        stem = f"{csv_stem(raw_csv)}_{safe_mode}_{z_suffix}_{rms_suffix(max_rms_m)}_ui"
        data_dir = ROOT / "data"
        bias_csv = data_dir / f"{stem}_bias_minus30.csv"
        range_csv = data_dir / f"{stem}_range_filtered.csv"
        pos_csv = data_dir / f"{stem}_position3d.csv"
        final_csv = data_dir / f"{stem}_position3d_filtered.csv"

        z_filter_args = ["--z-drop-step-m", "0.2", "--z-floor-epsilon", "0.02"]
        if self.filter_z0_box.isChecked():
            z_filter_args.append("--filter-z-floor")
        if self.drop_z0_box.isChecked():
            z_filter_args.append("--drop-z-floor")

        steps = [
            [sys.executable, str(ROOT / "tools" / "uwb_apply_range_bias.py"), "--input", str(raw_csv), "--output", str(bias_csv), "--bias-cm", "-30"],
            [
                sys.executable, str(ROOT / "tools" / "uwb_filter_ranges.py"),
                "--input", str(bias_csv), "--output", str(range_csv),
                "--max-jump-cm", "220", "--smooth-window", "1", "--neighborhood", "4", "--max-interp-run", "3",
            ],
            [sys.executable, str(ROOT / "tools" / "uwb_trilateration_3d.py"), "--input", str(range_csv), "--anchors", str(self.anchor_csv), "--output", str(pos_csv), "--z-min", "0"],
            [
                sys.executable, str(ROOT / "tools" / "uwb_filter_positions.py"),
                "--input", str(pos_csv), "--output", str(final_csv),
                "--max-step-m", "1.2", "--max-rms-m", f"{max_rms_m:.2f}", "--smooth-window", "3",
                "--rms-local-neighborhood", "10", "--rms-local-ratio", "3.0",
                "--rms-local-delta-m", "0.08", "--rms-local-min-m", "0.12",
                *z_filter_args,
                "--neighborhood", "4", "--max-interp-run", "3",
                "--max-speed-mps", str(mode["speed"]), "--max-accel-mps2", str(mode["accel"]),
                "--alpha", str(mode["alpha"]), "--beta", str(mode["beta"]),
            ],
        ]

        self.status_label.setText(f"正在处理: {Path(raw_csv).name} | {mode_name}")
        QApplication.processEvents()
        for step in steps:
            subprocess.run(step, cwd=ROOT, check=True)
        return final_csv

    def toggle_pause(self, checked):
        if checked:
            self.timer.stop()
            self.pause_btn.setText("继续播放")
        else:
            self.timer.start()
            self.pause_btn.setText("暂停播放")

    def restart_playback(self):
        self.play_index = 0
        self.visible_positions = []
        self.table.setRowCount(0)
        self.refresh_positions()
        if self.pause_btn.isChecked():
            self.pause_btn.setChecked(False)
        self.pause_btn.setText("暂停播放")
        self.timer.start()
        if self.all_positions:
            self.index_box.setRange(0, len(self.all_positions) - 1)
            self.seq_box.setRange(0, 255)

    def show_all_trajectory(self):
        self.timer.stop()
        self.visible_positions = list(self.all_positions)
        self.play_index = len(self.all_positions)
        self.table.setRowCount(0)
        for row in self.visible_positions:
            self.append_table_row(row)
        self.refresh_positions()
        self.pause_btn.setChecked(True)
        self.pause_btn.setText("继续播放")

    def locate_sequence(self):
        target_seq = self.seq_box.value()
        if not self.all_positions:
            return
        start = min(max(self.play_index - 1, 0), len(self.all_positions) - 1)
        ordered_indices = list(range(start, len(self.all_positions))) + list(range(0, start))
        for index in ordered_indices:
            point = self.all_positions[index]
            if point["seq"] == target_seq:
                self.ensure_visible_until(index)
                self.highlight_point(index)
                return
        QMessageBox.information(self, "未找到", f"没有找到 seq={target_seq}")

    def locate_index(self):
        target_index = self.index_box.value()
        if target_index < 0 or target_index >= len(self.all_positions):
            QMessageBox.information(self, "未找到", f"没有找到 idx={target_index}")
            return
        self.ensure_visible_until(target_index)
        self.highlight_point(target_index)

    def ensure_visible_until(self, index):
        if index < len(self.visible_positions):
            return
        self.timer.stop()
        self.visible_positions = list(self.all_positions[:index + 1])
        self.play_index = index + 1
        self.table.setRowCount(0)
        for row in self.visible_positions:
            self.append_table_row(row)
        self.refresh_positions()

    def highlight_point(self, all_index):
        if all_index < 0 or all_index >= len(self.all_positions):
            return
        point = self.all_positions[all_index]
        pos = np.array([[point["x"], point["y"], point["z"]]], dtype=float)
        self.selected_item.setData(pos=pos)
        visible_index = min(all_index, len(self.visible_positions) - 1)
        speed = self.point_speed(visible_index) if visible_index >= 0 else 0.0
        self.status_label.setText(
            f"选中 idx={point['idx']} seq={point['seq']} | "
            f"x={point['x']:.3f}, y={point['y']:.3f}, z={point['z']:.3f} | "
            f"v={speed:.3f} m/s | rms={point['rms']:.3f}m"
        )
        self.select_table_index(point["idx"])

    def on_table_cell_clicked(self, row, _col):
        idx_item = self.table.item(row, 0)
        if idx_item is None:
            return
        try:
            all_index = int(idx_item.text())
        except ValueError:
            return
        self.highlight_point(all_index)

    def load_all(self):
        self.anchors = read_anchor_positions(self.anchor_csv)
        self.all_positions = read_positions(self.position_csv)
        self.refresh_anchors()
        self.restart_playback()

    def advance_one_point(self):
        if self.play_index >= len(self.all_positions):
            self.timer.stop()
            self.pause_btn.setText("播放完成")
            self.status_label.setText(f"播放完成 | {len(self.visible_positions)} / {len(self.all_positions)} points")
            return
        row = self.all_positions[self.play_index]
        self.visible_positions.append(row)
        self.play_index += 1
        self.refresh_positions()
        self.append_table_row(row)

    def refresh_anchors(self):
        pts = np.array([a["pos"] for a in self.anchors], dtype=float)
        if len(pts):
            self.anchor_item.setData(pos=pts)
        for label in self.anchor_labels:
            self.view.removeItem(label)
        self.anchor_labels = []
        for anchor in self.anchors:
            x, y, z = anchor["pos"]
            label = gl.GLTextItem(pos=(x, y, z + 0.08), text=anchor["id"], color=(0.7, 0.9, 1.0, 1.0))
            self.anchor_labels.append(label)
            self.view.addItem(label)

    def refresh_positions(self):
        if not self.visible_positions:
            self.path_item.setData(pos=np.empty((0, 3)), color=trajectory_colors(0))
            self.start_item.setData(pos=np.empty((0, 3)))
            self.ball_item.setData(pos=np.empty((0, 3)))
            self.shadow_item.setData(pos=np.empty((0, 3)))
            self.status_label.setText(f"等待播放 | 0 / {len(self.all_positions)} points")
            return
        pts = np.array([[p["x"], p["y"], p["z"]] for p in self.visible_positions], dtype=float)
        self.path_item.setData(pos=pts, color=trajectory_colors(len(pts)))
        self.start_item.setData(pos=pts[:1])
        self.ball_item.setData(pos=pts[-1:])
        shadow = pts.copy()
        shadow[:, 2] = 0
        self.shadow_item.setData(pos=shadow)
        last = self.visible_positions[-1]
        speed = self.point_speed(len(self.visible_positions) - 1)
        self.status_label.setText(
            f"{Path(self.position_csv).name} | {len(self.visible_positions)} / {len(self.all_positions)} | "
            f"idx={last['idx']} seq={last['seq']} ({last['x']:.2f}, {last['y']:.2f}, {last['z']:.2f}) "
            f"v={speed:.2f}m/s rms={last['rms']:.3f}m"
        )

    def point_speed(self, index):
        if index <= 0 or index >= len(self.visible_positions):
            return 0.0
        a = self.visible_positions[index - 1]
        b = self.visible_positions[index]
        dt_ms = b.get("pc_ms", 0) - a.get("pc_ms", 0)
        dt = max(dt_ms / 1000.0, self.interval_box.value() / 1000.0, 1e-3)
        dist = ((b["x"] - a["x"]) ** 2 + (b["y"] - a["y"]) ** 2 + (b["z"] - a["z"]) ** 2) ** 0.5
        return dist / dt

    def nearest_visible_point(self, event_pos):
        if not self.visible_positions:
            return None
        width = max(self.view.width(), 1)
        height = max(self.view.height(), 1)
        x_norm = event_pos.position().x() / width
        y_norm = event_pos.position().y() / height

        # Lightweight picking fallback: map x/y field range to view plane.
        xs = [p["x"] for p in self.visible_positions]
        ys = [p["y"] for p in self.visible_positions]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        target_x = min_x + x_norm * max(max_x - min_x, 1e-6)
        target_y = max_y - y_norm * max(max_y - min_y, 1e-6)

        best_index = min(
            range(len(self.visible_positions)),
            key=lambda i: (self.visible_positions[i]["x"] - target_x) ** 2 + (self.visible_positions[i]["y"] - target_y) ** 2,
        )
        return best_index

    def on_view_mouse_press(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            mapped = QMouseEvent(
                event.type(),
                event.position(),
                event.globalPosition(),
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.LeftButton,
                event.modifiers(),
            )
            self.original_mouse_press_event(mapped)
            return
        if event.button() == Qt.MouseButton.MiddleButton:
            self.original_mouse_press_event(event)
            return
        if event.button() != Qt.MouseButton.LeftButton:
            event.ignore()
            return
        index = self.nearest_visible_point(event)
        if index is None:
            return
        point = self.visible_positions[index]
        speed = self.point_speed(index)
        pos = np.array([[point["x"], point["y"], point["z"]]], dtype=float)
        self.selected_item.setData(pos=pos)
        self.status_label.setText(
            f"选中 idx={point['idx']} seq={point['seq']} | "
            f"x={point['x']:.3f}, y={point['y']:.3f}, z={point['z']:.3f} | "
            f"v={speed:.3f} m/s | rms={point['rms']:.3f}m"
        )
        event.accept()

    def on_view_mouse_move(self, event):
        if event.buttons() & Qt.MouseButton.RightButton:
            mapped = QMouseEvent(
                event.type(),
                event.position(),
                event.globalPosition(),
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.LeftButton,
                event.modifiers(),
            )
            self.original_mouse_move_event(mapped)
        elif event.buttons() & Qt.MouseButton.MiddleButton:
            self.original_mouse_move_event(event)
        else:
            event.ignore()

    def append_table_row(self, row):
        idx = self.table.rowCount()
        self.table.insertRow(idx)
        values = [
            row["idx"],
            row["seq"],
            f"{row['x']:.3f}",
            f"{row['y']:.3f}",
            f"{row['z']:.3f}",
            f"{row['rms']:.3f}",
            row["pc_time"],
        ]
        for col, value in enumerate(values):
            item = QTableWidgetItem(str(value))
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(idx, col, item)
        self.table.scrollToBottom()

    def select_table_index(self, point_index):
        matches = self.table.findItems(str(point_index), Qt.MatchFlag.MatchExactly)
        for item in matches:
            if item.column() == 0:
                self.table.selectRow(item.row())
                self.table.scrollToItem(item)
                return


def main():
    parser = argparse.ArgumentParser(description="Play reconstructed BU01 UWB 3D trajectory point by point.")
    parser.add_argument("--positions", default="data/a0_tag_diag_test6_position3d_bias_minus30_z0_weighted_filtered.csv")
    parser.add_argument("--anchors", default="config/anchor_positions.csv")
    parser.add_argument("--interval-ms", type=int, default=100, help="playback interval per point")
    args = parser.parse_args()

    app = QApplication(sys.argv)
    window = TrajectoryVisualizer(args.positions, args.anchors, args.interval_ms)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
