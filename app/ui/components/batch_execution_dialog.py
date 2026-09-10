"""批量任务执行与多阶段耗时统计弹框。"""

from __future__ import annotations

import os
import time
from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    FluentIcon as FIF,
    IndeterminateProgressRing,
    ProgressBar,
    PrimaryPushButton,
    PushButton,
    SubtitleLabel,
    TableWidget,
    isDarkTheme,
)

from app.common.export_paths import resolve_clip_export_root
from app.data.models.batch_execution_record import (
    BatchExecutionSummary,
    DramaTimingRecord,
    format_duration,
    format_duration_short,
)


class BatchExecutionDialog(QDialog):
    """批量任务（批量识别/策划/渲染/一键执行）的实时看板与耗时结算弹框。"""

    cancelled = Signal()

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        task_type: str = "transcribe",
    ):
        super().__init__(parent)
        self.task_type = task_type
        self._summary: BatchExecutionSummary | None = None
        self._is_finished = False
        self._is_cancelling = False
        self._close_on_finish = False
        self._id_to_row: dict[str, int] = {}
        self._start_time: float | None = None

        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(1000)
        self._elapsed_timer.timeout.connect(self._update_live_elapsed)

        self.setWindowTitle(self._window_title_for(task_type))
        self.setMinimumSize(760, 480)
        self.resize(850, 520)

        self._init_ui()

    def _window_title_for(self, task_type: str) -> str:
        mapping = {
            "transcribe": "批量识别进度与耗时",
            "plan": "批量策划进度与耗时",
            "render": "批量渲染进度与耗时",
            "all": "一键执行全流程与耗时结算",
        }
        return mapping.get(task_type, "批量任务进度")

    def _init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)

        # 顶部标题与当前执行动态
        header_box = QVBoxLayout()
        header_box.setSpacing(6)
        self.title_label = SubtitleLabel("准备就绪…", self)
        header_box.addWidget(self.title_label)

        status_row = QHBoxLayout()
        status_row.setSpacing(10)
        status_row.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self.status_label = BodyLabel("正在初始化任务队列…", self)
        self.status_label.setWordWrap(True)
        status_row.addWidget(self.status_label, 1)

        self.progress_detail_label = CaptionLabel("", self)
        self.progress_detail_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        status_row.addWidget(self.progress_detail_label, 0, Qt.AlignmentFlag.AlignVCenter)

        self.timer_label = CaptionLabel("⏱️ 00:00", self)
        self.timer_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        status_row.addWidget(self.timer_label, 0, Qt.AlignmentFlag.AlignVCenter)

        self.spinner = IndeterminateProgressRing(self)
        self.spinner.setFixedSize(18, 18)
        self.spinner.setStrokeWidth(3)
        self.spinner.stop()
        self.spinner.hide()
        status_row.addWidget(self.spinner, 0, Qt.AlignmentFlag.AlignVCenter)

        header_box.addLayout(status_row)
        root.addLayout(header_box)

        # 总体进度条
        self.progress_bar = ProgressBar(self)
        self.progress_bar.setValue(0)
        root.addWidget(self.progress_bar)

        # 核心数据表格
        self.table = TableWidget(self)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(TableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(TableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(TableWidget.SelectionMode.SingleSelection)
        self._setup_table_columns()
        root.addWidget(self.table, 1)

        # 完成态汇总信息条
        self.summary_label = BodyLabel("", self)
        self.summary_label.setVisible(False)
        self.summary_label.setWordWrap(True)
        root.addWidget(self.summary_label)

        # 底部操作栏
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        self.open_export_btn = PushButton(FIF.FOLDER, "打开导出目录", self)
        self.open_export_btn.clicked.connect(self._on_open_export_clicked)
        self.open_export_btn.setVisible(False)
        btn_row.addWidget(self.open_export_btn)

        btn_row.addStretch(1)

        self.cancel_btn = PushButton("取消任务", self)
        self.cancel_btn.clicked.connect(self._on_cancel_clicked)
        btn_row.addWidget(self.cancel_btn)

        self.close_btn = PrimaryPushButton("完成", self)
        self.close_btn.clicked.connect(self.accept)
        self.close_btn.setVisible(False)
        btn_row.addWidget(self.close_btn)

        root.addLayout(btn_row)

    def _setup_table_columns(self):
        header = self.table.horizontalHeader()
        if self.task_type == "all":
            # 一键执行：剧名、集数、识别耗时、策划耗时、渲染耗时、总耗时、状态
            self.table.setColumnCount(7)
            self.table.setHorizontalHeaderLabels(
                ["剧名", "集数", "识别耗时", "策划耗时", "渲染耗时", "单剧总计", "状态"]
            )
            header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
            header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
            header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
            header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
            header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
            header.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
            header.setSectionResizeMode(6, QHeaderView.ResizeMode.Fixed)
            self.table.setColumnWidth(1, 65)
            self.table.setColumnWidth(2, 105)
            self.table.setColumnWidth(3, 105)
            self.table.setColumnWidth(4, 105)
            self.table.setColumnWidth(5, 110)
            self.table.setColumnWidth(6, 110)
        else:
            # 单批次任务：剧名、集数、阶段状态、耗时、详细信息
            stage_name = {
                "transcribe": "识别",
                "plan": "策划",
                "render": "渲染",
            }.get(self.task_type, "处理")
            self.table.setColumnCount(5)
            self.table.setHorizontalHeaderLabels(
                ["剧名", "集数", f"{stage_name}状态", f"{stage_name}耗时", "备注/结果"]
            )
            header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
            header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
            header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
            header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
            header.setSectionResizeMode(4, QHeaderView.ResizeMode.Interactive)
            self.table.setColumnWidth(1, 70)
            self.table.setColumnWidth(2, 110)
            self.table.setColumnWidth(3, 130)
            self.table.setColumnWidth(4, 180)

    def _update_live_elapsed(self):
        if self._start_time is None or self._is_finished:
            return
        elapsed = time.perf_counter() - self._start_time
        mins, secs = divmod(int(elapsed), 60)
        hours, mins = divmod(mins, 60)
        if hours > 0:
            time_str = f"{hours:02d}:{mins:02d}:{secs:02d}"
        else:
            time_str = f"{mins:02d}:{secs:02d}"
        self.timer_label.setText(f"⏱️ {time_str}")

    def closeEvent(self, event):
        if not self._is_finished:
            # 任务执行中，关闭窗口视为取消任务；等待后台任务安全停止后再关闭弹框
            event.ignore()
            self._close_on_finish = True
            if not self._is_cancelling:
                self._is_cancelling = True
                self.title_label.setText("正在取消任务…")
                self.status_label.setText("正在等待当前任务安全退出后关闭窗口，请稍候…")
                self.cancel_btn.setEnabled(False)
                self.cancel_btn.setText("正在关闭…")
                self.spinner.show()
                self.spinner.start()
                self.cancelled.emit()
            else:
                self.status_label.setText("正在等待当前任务安全退出后关闭窗口，请稍候…")
            return

        self._elapsed_timer.stop()
        self.spinner.stop()
        super().closeEvent(event)

    def reject(self):
        # 拦截 ESC 键触发的 reject，与右上角关闭行为保持一致
        if not self._is_finished:
            self.close()
            return
        super().reject()

    def init_batch(self, summary: BatchExecutionSummary):
        """初始化任务列表与表格视图。"""
        self._summary = summary
        self._is_finished = False
        self._is_cancelling = False
        self._close_on_finish = False
        self._start_time = time.perf_counter()
        self._elapsed_timer.start()
        self.spinner.show()
        self.spinner.start()

        records = summary.records
        total = len(records)
        self.progress_bar.setRange(0, total if total > 0 else 1)
        self.progress_bar.setValue(0)

        task_title = summary.task_name
        self.title_label.setText(f"正在{task_title}（共 {total} 部剧）")
        self.status_label.setText("正在准备执行…")
        if total > 0:
            self.progress_detail_label.setText(f"进度: 0/{total} (0%)")
        else:
            self.progress_detail_label.setText("")
        self.timer_label.setText("⏱️ 00:00")

        self.table.setRowCount(total)
        self._id_to_row.clear()

        for row, rec in enumerate(records):
            self._id_to_row[rec.project_id] = row
            self._render_row(row, rec)

    def update_progress(
        self,
        record: DramaTimingRecord,
        *,
        action_text: str = "",
        current_index: int = 0,
        total_count: int = 0,
    ):
        """实时更新某剧目的状态与耗时。"""
        row = self._id_to_row.get(record.project_id)
        if row is not None:
            self._render_row(row, record)
            item = self.table.item(row, 0)
            if item:
                self.table.scrollToItem(item, QAbstractItemView.ScrollHint.EnsureVisible)

        if total_count > 0:
            self.progress_bar.setValue(current_index)
            percent = int((current_index / total_count) * 100)
            self.progress_detail_label.setText(f"进度: {current_index}/{total_count} ({percent}%)")

        if action_text:
            self.status_label.setText(action_text)

    def _render_row(self, row: int, rec: DramaTimingRecord):
        dark = isDarkTheme()
        green_color = QColor("#3dd68c") if dark else Qt.GlobalColor.darkGreen
        yellow_color = QColor("#f2c14e") if dark else Qt.GlobalColor.darkYellow
        red_color = QColor("#ff5c5c") if dark else Qt.GlobalColor.red

        # 剧名
        name_item = QTableWidgetItem(rec.project_name)
        name_item.setToolTip(rec.project_name)
        self.table.setItem(row, 0, name_item)

        # 集数
        ep_text = str(rec.episode_count or "-")
        ep_item = QTableWidgetItem(ep_text)
        ep_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        ep_item.setToolTip(f"{ep_text} 集" if rec.episode_count else "-")
        self.table.setItem(row, 1, ep_item)

        if self.task_type == "all":
            # 识别耗时
            t_str = format_duration_short(rec.transcribe_time)
            t_item = QTableWidgetItem(t_str)
            t_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if rec.transcribe_status == "done":
                t_item.setForeground(green_color)
                t_item.setToolTip(f"识别耗时: {format_duration(rec.transcribe_time)}")
            elif rec.transcribe_status == "in_progress":
                t_item.setText("识别中…")
                t_item.setForeground(yellow_color)
                t_item.setToolTip("正在识别中…")
            elif rec.transcribe_status == "failed":
                t_item.setText("失败")
                t_item.setForeground(red_color)
                t_item.setToolTip(rec.error_msg or "识别失败")
            else:
                t_item.setToolTip(t_item.text())
            self.table.setItem(row, 2, t_item)

            # 策划耗时
            p_str = format_duration_short(rec.plan_time)
            p_item = QTableWidgetItem(p_str)
            p_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if rec.plan_status == "done":
                p_item.setForeground(green_color)
                p_item.setToolTip(f"策划耗时: {format_duration(rec.plan_time)}")
            elif rec.plan_status == "in_progress":
                p_item.setText("策划中…")
                p_item.setForeground(yellow_color)
                p_item.setToolTip("正在策划中…")
            elif rec.plan_status == "failed":
                p_item.setText("失败")
                p_item.setForeground(red_color)
                p_item.setToolTip(rec.error_msg or "策划失败")
            else:
                p_item.setToolTip(p_item.text())
            self.table.setItem(row, 3, p_item)

            # 渲染耗时
            r_str = format_duration_short(rec.render_time)
            r_item = QTableWidgetItem(r_str)
            r_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if rec.render_status == "done":
                r_item.setForeground(green_color)
                r_item.setToolTip(f"渲染耗时: {format_duration(rec.render_time)}")
            elif rec.render_status == "in_progress":
                r_item.setText("渲染中…")
                r_item.setForeground(yellow_color)
                r_item.setToolTip("正在渲染中…")
            elif rec.render_status == "failed":
                r_item.setText("失败")
                r_item.setForeground(red_color)
                r_item.setToolTip(rec.error_msg or "渲染失败")
            else:
                r_item.setToolTip(r_item.text())
            self.table.setItem(row, 4, r_item)

            # 单剧总计
            tot_str = format_duration_short(rec.total_time) if rec.total_time > 0 else "-"
            tot_item = QTableWidgetItem(tot_str)
            tot_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if rec.is_success("all"):
                tot_item.setForeground(green_color)
            tot_item.setToolTip(f"单剧总耗时: {format_duration(rec.total_time)}" if rec.total_time > 0 else "-")
            self.table.setItem(row, 5, tot_item)

            # 总体状态
            st_text = self._overall_status_text(rec)
            st_item = QTableWidgetItem(st_text)
            st_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if rec.is_success("all"):
                st_item.setForeground(green_color)
            elif "失败" in st_text:
                st_item.setForeground(red_color)
            elif "进行中" in st_text or "中" in st_text:
                st_item.setForeground(yellow_color)
            st_item.setToolTip(st_text)
            self.table.setItem(row, 6, st_item)

        else:
            # 单批次任务
            status_val, time_val = self._single_stage_data(rec)
            st_text = self._status_label_text(status_val)
            st_item = QTableWidgetItem(st_text)
            st_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if status_val == "done":
                st_item.setForeground(green_color)
            elif status_val == "in_progress":
                st_item.setForeground(yellow_color)
            elif status_val == "failed":
                st_item.setForeground(red_color)
            st_item.setToolTip(st_text)
            self.table.setItem(row, 2, st_item)

            # 耗时
            t_str = format_duration(time_val) if time_val > 0 else "-"
            t_item = QTableWidgetItem(t_str)
            t_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if status_val == "done":
                t_item.setForeground(green_color)
            t_item.setToolTip(f"耗时: {t_str}" if time_val > 0 else "-")
            self.table.setItem(row, 3, t_item)

            # 备注
            note = rec.error_msg if status_val == "failed" else ("完成" if status_val == "done" else "-")
            note_item = QTableWidgetItem(note)
            if status_val == "failed":
                note_item.setForeground(red_color)
            note_item.setToolTip(note)
            self.table.setItem(row, 4, note_item)

    def _single_stage_data(self, rec: DramaTimingRecord) -> tuple[str, float]:
        if self.task_type == "transcribe":
            return rec.transcribe_status, rec.transcribe_time
        if self.task_type == "plan":
            return rec.plan_status, rec.plan_time
        return rec.render_status, rec.render_time

    def _status_label_text(self, status: str) -> str:
        mapping = {
            "pending": "排队等待",
            "in_progress": "处理中…",
            "done": "✅ 已完成",
            "failed": "❌ 失败",
            "cancelled": "已取消",
            "skipped": "已跳过",
        }
        return mapping.get(status, status)

    def _overall_status_text(self, rec: DramaTimingRecord) -> str:
        if rec.is_success("all"):
            return "✅ 全部完成"
        if rec.render_status == "in_progress":
            return "渲染中"
        if rec.plan_status == "in_progress":
            return "策划中"
        if rec.transcribe_status == "in_progress":
            return "识别中"
        if rec.transcribe_status == "failed":
            return "❌ 识别失败"
        if rec.plan_status == "failed":
            return "❌ 策划失败"
        if rec.render_status == "failed":
            return "❌ 渲染失败"
        if rec.render_status == "cancelled" or rec.plan_status == "cancelled":
            return "已取消"
        return "等待中"

    def finish_batch(self, summary: BatchExecutionSummary):
        """任务全部执行完毕或取消时的结算呈现。"""
        self._summary = summary
        self._is_finished = True
        self._is_cancelling = False
        self.spinner.stop()
        self.spinner.hide()
        self._elapsed_timer.stop()

        for row, rec in enumerate(summary.records):
            self._render_row(row, rec)

        self.progress_bar.setValue(self.progress_bar.maximum())

        if self._close_on_finish:
            self.accept()
            return

        # 状态标题与副标题
        if summary.is_cancelled:
            self.title_label.setText(f"⚠️ {summary.task_name}已取消")
            self.status_label.setText(
                f"用户已终止任务。已完成 {summary.success_count}/{summary.total_count} 部剧。"
            )
            self.progress_detail_label.setText(f"已取消 ({summary.success_count}/{summary.total_count})")
            self.timer_label.setText(f"⏱️ 耗时: {format_duration_short(summary.total_elapsed)}")
        else:
            if self.task_type == "all":
                self.title_label.setText("🎉 一键执行全部完毕！")
            else:
                self.title_label.setText(f"✅ {summary.task_name}执行完毕！")

            self.status_label.setText(
                f"共处理 {summary.total_count} 部剧 · 成功 {summary.success_count} 部"
                + (f" · 失败 {summary.fail_count} 部" if summary.fail_count > 0 else "")
                + f" · 全程总耗时：{format_duration(summary.total_elapsed)}"
            )
            self.progress_detail_label.setText(f"已完成 {summary.success_count}/{summary.total_count}")
            self.timer_label.setText(f"⏱️ 总耗时: {format_duration_short(summary.total_elapsed)}")

        # 汇总提示条
        self.summary_label.setText(
            f"💡 耗时统计已汇总完毕。共耗时 {format_duration(summary.total_elapsed)}。"
            + (" 可在上方表格查看每部剧各阶段的具体耗时。" if self.task_type == "all" else " 可在上方表格查看各剧耗时。")
        )
        self.summary_label.setVisible(True)

        # 按钮状态切换
        self.cancel_btn.setVisible(False)
        self.close_btn.setVisible(True)
        if self.task_type in ("render", "all") and summary.success_count > 0:
            self.open_export_btn.setVisible(True)

    def _on_cancel_clicked(self):
        if self._is_cancelling:
            return
        self._is_cancelling = True
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.setText("正在取消…")
        self.status_label.setText("正在取消后续任务，请稍候…")
        self.spinner.show()
        self.spinner.start()
        self.cancelled.emit()

    def _on_open_export_clicked(self):
        path = resolve_clip_export_root()
        os.makedirs(path, exist_ok=True)
        os.startfile(path)
