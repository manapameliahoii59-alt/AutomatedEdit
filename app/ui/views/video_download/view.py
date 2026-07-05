import os

from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QPlainTextEdit,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CheckBox,
    Dialog,
    LineEdit,
    PrimaryPushButton,
    PushButton,
    ScrollArea,
    TableWidget,
    FluentIcon as FIF,
    qconfig,
)

from app.common.config import cfg

from app.common.utils import show_dialog
from app.data.services.changdu_paths import resolve_video_download_root
from app.data.services.drama_folder_service import list_drama_folders_under
from app.ui.components.bar import ProgressInfoBar

from .view_model import MAX_DOWNLOAD_EPISODE, VideoDownloadViewModel


class VideoDownloadPage(ScrollArea):
    """常读平台视频批量下载。"""

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self._parent_window = parent
        self.vm = VideoDownloadViewModel(self)
        self.setObjectName("video_download_page")
        self.loading_bar = None
        self._init_ui()
        self._bind_view_model()

    def _init_ui(self):
        self.scroll_widget = QWidget()
        self.scroll_widget.setObjectName("videoDownloadScrollWidget")
        self.setWidget(self.scroll_widget)
        self.setWidgetResizable(True)

        layout = QVBoxLayout(self.scroll_widget)
        layout.setContentsMargins(36, 20, 36, 20)
        layout.setSpacing(12)

        auth_row = QHBoxLayout()
        auth_row.setSpacing(8)
        auth_row.addWidget(BodyLabel("常读登录：", self.scroll_widget))
        self.auth_status_label = BodyLabel("未登录", self.scroll_widget)
        auth_row.addWidget(self.auth_status_label, 1)
        self.login_btn = PrimaryPushButton(FIF.PEOPLE, "打开浏览器登录", self.scroll_widget)
        self.login_btn.clicked.connect(self.vm.login_changdu)
        self.check_auth_btn = PushButton("验证登录态", self.scroll_widget)
        self.check_auth_btn.clicked.connect(self.vm.check_auth)
        auth_row.addWidget(self.login_btn)
        auth_row.addWidget(self.check_auth_btn)
        layout.addLayout(auth_row)

        download_row = QHBoxLayout()
        download_row.setSpacing(8)
        download_row.addWidget(BodyLabel("下载目录：", self.scroll_widget))
        self.download_path_label = BodyLabel(resolve_video_download_root(), self.scroll_widget)
        self.download_path_label.setWordWrap(True)
        download_row.addWidget(self.download_path_label, 1)
        self.download_browse_btn = PushButton("浏览…", self.scroll_widget)
        self.download_browse_btn.clicked.connect(self._pick_download_dir)
        self.download_open_btn = PushButton("打开文件夹", self.scroll_widget)
        self.download_open_btn.clicked.connect(self._open_download_dir)
        download_row.addWidget(self.download_browse_btn)
        download_row.addWidget(self.download_open_btn)
        layout.addLayout(download_row)

        range_row = QHBoxLayout()
        range_row.setSpacing(8)
        range_row.addWidget(BodyLabel("默认集数：", self.scroll_widget))
        range_row.addWidget(BodyLabel("从第", self.scroll_widget))
        self.from_input = LineEdit(self.scroll_widget)
        self.from_input.setText(str(self.vm.get_default_from()))
        self.from_input.setPlaceholderText("1")
        self.from_input.setFixedWidth(64)
        self.from_input.editingFinished.connect(self._normalize_episode_inputs)
        range_row.addWidget(self.from_input)
        range_row.addWidget(BodyLabel("集 到第", self.scroll_widget))
        self.to_input = LineEdit(self.scroll_widget)
        self.to_input.setText(str(self.vm.get_default_to()))
        self.to_input.setPlaceholderText(str(MAX_DOWNLOAD_EPISODE))
        self.to_input.setFixedWidth(64)
        self.to_input.editingFinished.connect(self._normalize_episode_inputs)
        range_row.addWidget(self.to_input)
        range_row.addWidget(BodyLabel("集", self.scroll_widget))
        range_row.addStretch(1)
        self.add_btn = PushButton(FIF.ADD, "添加剧目", self.scroll_widget)
        self.add_btn.clicked.connect(self._open_add_drama_dialog)
        range_row.addWidget(self.add_btn)
        self.more_btn = PushButton("⁝", self.scroll_widget)
        self.more_btn.setFixedSize(36, 36)
        self.more_btn.setToolTip("下载设置")
        self.more_btn.clicked.connect(self._open_download_settings_dialog)
        range_row.addWidget(self.more_btn)
        layout.addLayout(range_row)

        self.table = TableWidget(self.scroll_widget)
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["剧名", "起始集", "结束集", "状态", "操作"])
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(44)
        self.table.setEditTriggers(TableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(TableWidget.SelectionBehavior.SelectRows)
        table_header = self.table.horizontalHeader()
        table_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        table_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        table_header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        table_header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        table_header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(0, 220)
        self.table.setColumnWidth(1, 80)
        self.table.setColumnWidth(2, 80)
        self.table.setColumnWidth(3, 100)
        self.table.setColumnWidth(4, 88)
        layout.addWidget(self.table, 1)

        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        self.start_btn = PrimaryPushButton(FIF.DOWNLOAD, "开始下载", self.scroll_widget)
        self.start_btn.clicked.connect(self._start)
        self.import_all_btn = PushButton(FIF.FOLDER_ADD, "导出至剪辑页", self.scroll_widget)
        self.import_all_btn.clicked.connect(self._import_all_to_clip)
        action_row.addWidget(self.start_btn)
        action_row.addWidget(self.import_all_btn)
        action_row.addStretch(1)
        layout.addLayout(action_row)

        layout.addWidget(BodyLabel("运行日志：", self.scroll_widget))
        self.log_view = QPlainTextEdit(self.scroll_widget)
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(2000)
        self.log_view.setMinimumHeight(160)
        layout.addWidget(self.log_view)

        self.setViewportMargins(0, 0, 0, 0)

    def _bind_view_model(self):
        self.vm.targetsChanged.connect(self._refresh_table)
        self.vm.loadingChanged.connect(self._handle_loading)
        self.vm.logAppended.connect(self._append_log)
        self.vm.authStatusChanged.connect(self._update_auth_status)
        self.vm.messageReceived.connect(lambda msg: show_dialog(self, msg, "提示"))
        self.vm.errorOccurred.connect(lambda msg: show_dialog(self, msg, "提示"))
        self.vm.clipHandoffRequested.connect(self._on_clip_handoff)
        self.vm.refresh_auth_status()

    def _on_clip_handoff(self, folders: list):
        if self._parent_window and hasattr(self._parent_window, "handoff_to_clip_edit"):
            self._parent_window.handoff_to_clip_edit(folders)

    def _update_auth_status(self, ok: bool, text: str):
        self.auth_status_label.setText(text)

    def _append_log(self, line: str):
        self.log_view.appendPlainText(line)
        self.log_view.verticalScrollBar().setValue(
            self.log_view.verticalScrollBar().maximum()
        )

    def _handle_loading(self, loading: bool, title: str, content: str):
        busy = loading
        self.login_btn.setEnabled(not busy)
        self.check_auth_btn.setEnabled(not busy)
        self.start_btn.setEnabled(not busy)
        self.import_all_btn.setEnabled(not busy)
        if loading:
            self.loading_bar = ProgressInfoBar(title, content, self)
            self.loading_bar.show()
        elif self.loading_bar is not None:
            self.loading_bar.hide()
            self.loading_bar = None

    def _refresh_table(self):
        targets = self.vm.get_targets()
        self.table.setRowCount(len(targets))
        for row, target in enumerate(targets):
            name_item = QTableWidgetItem(target.name)
            name_item.setToolTip(target.name)
            self.table.setItem(row, 0, name_item)
            self.table.setItem(row, 1, QTableWidgetItem(str(target.from_ep)))
            self.table.setItem(row, 2, QTableWidgetItem(str(target.to_ep)))
            self.table.setItem(row, 3, QTableWidgetItem(target.status))

            remove_btn = PushButton("删除", self.table)
            remove_btn.clicked.connect(
                lambda _checked=False, tid=target.id: self.vm.remove_target(tid)
            )
            self.table.setCellWidget(row, 4, remove_btn)

    def _parse_episode_input(self, text: str, label: str) -> int | None:
        raw = text.strip()
        if not raw.isdigit():
            show_dialog(self, f"{label}须为正整数", "提示")
            return None
        value = int(raw)
        if value < 1:
            show_dialog(self, f"{label}须大于等于 1", "提示")
            return None
        return value

    def _clamp_episode(self, value: int) -> int:
        return max(1, min(value, MAX_DOWNLOAD_EPISODE))

    def _normalize_episode_inputs(self) -> None:
        from_text = self.from_input.text().strip()
        to_text = self.to_input.text().strip()
        if not from_text.isdigit() or not to_text.isdigit():
            return
        from_ep = self._clamp_episode(int(from_text))
        to_ep = self._clamp_episode(int(to_text))
        if to_ep < from_ep:
            to_ep = from_ep
        if from_text != str(from_ep):
            self.from_input.setText(str(from_ep))
        if to_text != str(to_ep):
            self.to_input.setText(str(to_ep))

    def _apply_episode_range(self) -> bool:
        from_ep = self._parse_episode_input(self.from_input.text(), "起始集")
        if from_ep is None:
            return False
        to_ep = self._parse_episode_input(self.to_input.text(), "结束集")
        if to_ep is None:
            return False
        from_ep = self._clamp_episode(from_ep)
        to_ep = self._clamp_episode(to_ep)
        if to_ep < from_ep:
            to_ep = from_ep
        self.from_input.setText(str(from_ep))
        self.to_input.setText(str(to_ep))
        self.vm.set_default_range(from_ep, to_ep)
        return True

    def _open_add_drama_dialog(self):
        if not self._apply_episode_range():
            return

        dialog = Dialog("添加剧目", "每行输入一个剧名", self.window())
        dialog.titleLabel.hide()
        dialog.windowTitleLabel.hide()
        dialog.titleBar.show()
        dialog.titleBar.raise_()
        dialog.titleBar.minBtn.hide()
        dialog.titleBar.maxBtn.hide()
        dialog.setWindowTitle("添加剧目")
        dialog.yesButton.setText("确定")
        dialog.cancelButton.setText("取消")

        while dialog.buttonLayout.count():
            dialog.buttonLayout.takeAt(0)
        dialog.buttonLayout.setContentsMargins(24, 8, 24, 12)
        dialog.buttonLayout.addStretch(1)
        dialog.buttonLayout.addWidget(dialog.cancelButton, 0)
        dialog.buttonLayout.addWidget(dialog.yesButton, 0)
        dialog.buttonGroup.setFixedHeight(52)

        name_input = QPlainTextEdit(dialog)
        name_input.setPlaceholderText("半山青果第一季\n某剧名\n…")
        name_input.setMaximumBlockCount(500)
        name_input.setFixedSize(360, 140)
        name_input.setStyleSheet(
            "QPlainTextEdit {"
            "  border: 1px solid #c8c8c8;"
            "  border-radius: 6px;"
            "  padding: 8px;"
            "  background-color: #ffffff;"
            "}"
            "QPlainTextEdit:focus {"
            "  border: 1px solid #009faa;"
            "}"
        )
        dialog.textLayout.setContentsMargins(24, 16, 24, 8)
        dialog.textLayout.addWidget(name_input)

        dialog.setFixedSize(420, 268)
        if dialog.exec():
            added = self.vm.add_targets_from_text(name_input.toPlainText())
            if added > 0 and cfg.video_download_auto_start_after_add.value:
                self._start()

    def _import_all_to_clip(self):
        folders = list_drama_folders_under(resolve_video_download_root())
        if not folders:
            show_dialog(self, "下载目录中未找到可导入的剧目视频文件夹", "提示")
            return
        if self._parent_window and hasattr(self._parent_window, "import_to_clip_edit"):
            self._parent_window.import_to_clip_edit(folders)

    def _open_download_settings_dialog(self):
        dialog = Dialog("设置", "", self.window())
        dialog.contentLabel.hide()
        dialog.windowTitleLabel.hide()
        dialog.titleBar.show()
        dialog.titleBar.raise_()
        dialog.titleBar.minBtn.hide()
        dialog.titleBar.maxBtn.hide()
        dialog.setWindowTitle("设置")
        dialog.yesButton.setText("确定")
        dialog.cancelButton.setText("取消")

        while dialog.buttonLayout.count():
            dialog.buttonLayout.takeAt(0)
        dialog.buttonLayout.setContentsMargins(24, 8, 24, 12)
        dialog.buttonLayout.addStretch(1)
        dialog.buttonLayout.addWidget(dialog.cancelButton, 0)
        dialog.buttonLayout.addWidget(dialog.yesButton, 0)
        dialog.buttonGroup.setFixedHeight(52)

        auto_unzip_cb = CheckBox("下载完成后自动解压并删除压缩包", dialog)
        auto_unzip_cb.setChecked(cfg.video_download_auto_unzip.value)
        auto_transcribe_cb = CheckBox("解压后自动识别视频", dialog)
        auto_transcribe_cb.setChecked(cfg.video_download_auto_transcribe.value)
        auto_clip_cb = CheckBox("识别完成后自动导入剪辑并执行后续流程", dialog)
        auto_clip_cb.setChecked(cfg.video_download_auto_import_clip.value)
        auto_clip_cb.setEnabled(auto_transcribe_cb.isChecked())
        auto_start_cb = CheckBox("添加剧目确定后自动开始下载", dialog)
        auto_start_cb.setChecked(cfg.video_download_auto_start_after_add.value)

        def _on_transcribe_toggled(checked: bool) -> None:
            if checked:
                auto_unzip_cb.setChecked(True)
            else:
                auto_clip_cb.setChecked(False)
            auto_clip_cb.setEnabled(checked)

        def _on_clip_toggled(checked: bool) -> None:
            if checked:
                auto_unzip_cb.setChecked(True)
                auto_transcribe_cb.setChecked(True)

        auto_transcribe_cb.toggled.connect(_on_transcribe_toggled)
        auto_clip_cb.toggled.connect(_on_clip_toggled)

        dialog.textLayout.setContentsMargins(24, 16, 24, 8)
        dialog.textLayout.addWidget(auto_unzip_cb)
        dialog.textLayout.addWidget(auto_transcribe_cb)
        dialog.textLayout.addWidget(auto_clip_cb)
        dialog.textLayout.addWidget(auto_start_cb)

        dialog.setFixedSize(420, 300)
        if dialog.exec():
            clip = auto_clip_cb.isChecked()
            transcribe = auto_transcribe_cb.isChecked() or clip
            unzip = auto_unzip_cb.isChecked() or transcribe
            qconfig.set(cfg.video_download_auto_unzip, unzip)
            qconfig.set(cfg.video_download_auto_transcribe, transcribe)
            qconfig.set(cfg.video_download_auto_import_clip, clip)
            qconfig.set(cfg.video_download_auto_start_after_add, auto_start_cb.isChecked())

    def _start(self):
        if not self._apply_episode_range():
            return
        self.vm.start_download()

    def _pick_download_dir(self):
        folder = QFileDialog.getExistingDirectory(
            self,
            "选择下载目录",
            resolve_video_download_root(),
            QFileDialog.Option.ShowDirsOnly | QFileDialog.Option.DontResolveSymlinks,
        )
        if folder:
            self.vm.set_download_dir(folder)
            self.download_path_label.setText(folder)

    def _open_download_dir(self):
        path = resolve_video_download_root()
        os.makedirs(path, exist_ok=True)
        os.startfile(path)
