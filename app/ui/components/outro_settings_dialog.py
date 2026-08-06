"""片尾设置对话框：多条目缩略图横向排布，勾选启用，拖拽/右键删除。"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QDragEnterEvent, QDropEvent, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QRadioButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import BodyLabel, Dialog, PushButton

from app.common.outro_paths import (
    OutroItem,
    add_outro_item,
    list_outro_items,
    remove_outro_item,
    selected_outro_id,
    set_selected_outro_id,
)
from app.common.utils import setup_confirm_dialog, show_dialog, show_toast

_THUMB = 88
_VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".m4v", ".webm"}


def _paths_from_mime(event: QDragEnterEvent | QDropEvent) -> list[str]:
    urls = event.mimeData().urls() if event.mimeData() else []
    out: list[str] = []
    for url in urls:
        if not url.isLocalFile():
            continue
        path = url.toLocalFile()
        if Path(path).suffix.lower() in _VIDEO_EXTS:
            out.append(path)
    return out


class _ThumbCard(QFrame):
    """单个片尾缩略图卡片：单击选中，双击播放，右键删除。"""

    def __init__(
        self,
        item: OutroItem,
        *,
        horizontal: bool,
        selected: bool,
        on_select,
        on_play,
        on_delete,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._item = item
        self._horizontal = horizontal
        self._on_select = on_select
        self._on_play = on_play
        self._on_delete = on_delete
        self.setFixedSize(_THUMB + 8, _THUMB + 8)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_menu)
        self._thumb = QLabel(self)
        self._thumb.setFixedSize(_THUMB, _THUMB)
        self._thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._thumb.move(4, 4)
        if item.thumb_path.is_file():
            pix = QPixmap(str(item.thumb_path))
            if not pix.isNull():
                self._thumb.setPixmap(
                    pix.scaled(
                        _THUMB,
                        _THUMB,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
            else:
                self._thumb.setText("无图")
        else:
            self._thumb.setText("无图")
        self.set_selected(selected)

    def set_selected(self, selected: bool) -> None:
        if selected:
            self.setStyleSheet(
                "QFrame{background:#2a2a2a;border:2px solid #f2c14e;border-radius:6px;}"
            )
        else:
            self.setStyleSheet(
                "QFrame{background:#2a2a2a;border:1px solid #555;border-radius:6px;}"
            )

    def mousePressEvent(self, event) -> None:  # noqa: ANN001
        if event.button() == Qt.MouseButton.LeftButton:
            self._on_select(self._horizontal, self._item.id)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: ANN001
        if event.button() == Qt.MouseButton.LeftButton:
            self._on_play(self._item)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def _show_menu(self, pos) -> None:  # noqa: ANN001
        menu = QMenu(self)
        play_act = QAction("打开播放", menu)
        play_act.triggered.connect(lambda: self._on_play(self._item))
        menu.addAction(play_act)
        del_act = QAction("删除", menu)
        del_act.triggered.connect(
            lambda: self._on_delete(self._horizontal, self._item)
        )
        menu.addAction(del_act)
        menu.exec(self.mapToGlobal(pos))


class _DropStrip(QScrollArea):
    """可拖入视频的横向缩略图条。"""

    def __init__(self, *, horizontal: bool, on_drop_files, parent: QWidget | None = None):
        super().__init__(parent)
        self._horizontal = horizontal
        self._on_drop_files = on_drop_files
        self.setAcceptDrops(True)
        self.setWidgetResizable(True)
        self.setFixedHeight(_THUMB + 36)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self._set_idle_style()

        self._host = QWidget(self)
        self._row = QHBoxLayout(self._host)
        self._row.setContentsMargins(8, 6, 8, 6)
        self._row.setSpacing(10)
        self.setWidget(self._host)

    def row_layout(self) -> QHBoxLayout:
        return self._row

    def host(self) -> QWidget:
        return self._host

    def _set_idle_style(self) -> None:
        self.setStyleSheet(
            "QScrollArea{border:1px dashed #666;border-radius:6px;background:transparent;}"
        )

    def _set_active_style(self) -> None:
        self.setStyleSheet(
            "QScrollArea{border:2px dashed #f2c14e;border-radius:6px;background:rgba(242,193,78,0.08);}"
        )

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if _paths_from_mime(event):
            event.acceptProposedAction()
            self._set_active_style()
        else:
            event.ignore()

    def dragLeaveEvent(self, event) -> None:  # noqa: ANN001
        self._set_idle_style()
        super().dragLeaveEvent(event)

    def dragMoveEvent(self, event) -> None:  # noqa: ANN001
        if _paths_from_mime(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        self._set_idle_style()
        paths = _paths_from_mime(event)
        if not paths:
            event.ignore()
            return
        event.acceptProposedAction()
        self._on_drop_files(self._horizontal, paths)


class OutroSettingsDialog(QDialog):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("片尾设置")
        self.setMinimumSize(720, 420)
        self.setAcceptDrops(False)
        root = QVBoxLayout(self)
        root.setSpacing(14)

        self._sections: dict[bool, dict] = {}
        root.addWidget(self._build_section(horizontal=True))
        root.addWidget(self._build_section(horizontal=False))
        root.addStretch(1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        if ok_btn is not None:
            ok_btn.setText("确定")
        cancel_btn = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        if cancel_btn is not None:
            cancel_btn.setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self.reload_all()

    def _build_section(self, *, horizontal: bool) -> QWidget:
        title = "横屏片尾" if horizontal else "竖屏片尾"
        box = QWidget(self)
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        head = QHBoxLayout()
        head.addWidget(BodyLabel(title, box))
        head.addStretch(1)
        default_radio = QRadioButton("使用默认片尾", box)
        default_radio.toggled.connect(
            lambda checked, hor=horizontal: self._on_default_toggled(hor, checked)
        )
        head.addWidget(default_radio)
        upload_btn = PushButton("上传…", box)
        upload_btn.clicked.connect(lambda: self._on_upload(horizontal=horizontal))
        head.addWidget(upload_btn)
        layout.addLayout(head)

        strip = _DropStrip(
            horizontal=horizontal,
            on_drop_files=self._on_drop_files,
            parent=box,
        )
        layout.addWidget(strip)

        group = QButtonGroup(box)
        group.setExclusive(True)
        group.addButton(default_radio)

        self._sections[horizontal] = {
            "default_radio": default_radio,
            "row": strip.row_layout(),
            "host": strip.host(),
            "strip": strip,
            "cards": {},
            "group": group,
        }
        return box

    def reload_all(self) -> None:
        self._reload_section(horizontal=True)
        self._reload_section(horizontal=False)

    def _clear_cards(self, horizontal: bool) -> None:
        section = self._sections[horizontal]
        row: QHBoxLayout = section["row"]
        while row.count():
            item = row.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        section["cards"] = {}

    def _reload_section(self, *, horizontal: bool) -> None:
        self._clear_cards(horizontal)
        section = self._sections[horizontal]
        row: QHBoxLayout = section["row"]
        default_radio: QRadioButton = section["default_radio"]
        selected = selected_outro_id(horizontal)
        items = list_outro_items(horizontal)

        default_radio.blockSignals(True)
        default_radio.setChecked(not bool(selected))
        default_radio.blockSignals(False)

        if not items:
            hint = QLabel("将视频拖到此处，或点击「上传…」", section["host"])
            hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
            hint.setStyleSheet("color:#888;")
            row.addWidget(hint, 1)
        else:
            for item in items:
                card = _ThumbCard(
                    item,
                    horizontal=horizontal,
                    selected=(item.id == selected),
                    on_select=self._on_card_select,
                    on_play=self._on_play,
                    on_delete=self._on_delete,
                    parent=section["host"],
                )
                row.addWidget(card)
                section["cards"][item.id] = card
            row.addStretch(1)

    def _on_default_toggled(self, horizontal: bool, checked: bool) -> None:
        if not checked:
            return
        set_selected_outro_id(horizontal, "")
        for card in self._sections[horizontal]["cards"].values():
            card.set_selected(False)

    def _on_card_select(self, horizontal: bool, item_id: str) -> None:
        set_selected_outro_id(horizontal, item_id)
        section = self._sections[horizontal]
        section["default_radio"].blockSignals(True)
        section["default_radio"].setChecked(False)
        section["default_radio"].blockSignals(False)
        for cid, card in section["cards"].items():
            card.set_selected(cid == item_id)

    def _on_play(self, item: OutroItem) -> None:
        path = item.video_path
        if not path.is_file():
            show_dialog(self, "视频文件不存在或已被移除", "无法播放")
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.resolve()))):
            show_dialog(self, f"无法打开：{path.name}", "无法播放")

    def _import_paths(self, *, horizontal: bool, paths: list[str]) -> None:
        ok = 0
        errors: list[str] = []
        for path in paths:
            try:
                add_outro_item(path, horizontal=horizontal)
                ok += 1
            except ValueError as exc:
                errors.append(f"{Path(path).name}：{exc}")
            except OSError as exc:
                errors.append(f"{Path(path).name}：{exc}")
        if ok:
            self._reload_section(horizontal=horizontal)
            show_toast(
                self,
                f"已添加 {ok} 个片尾" + ("并启用最后一个" if ok == 1 else "（已启用最后上传的）"),
                title="片尾设置",
            )
        if errors:
            show_dialog(self, "\n".join(errors[:6]), "片尾校验失败")

    def _on_drop_files(self, horizontal: bool, paths: list[str]) -> None:
        self._import_paths(horizontal=horizontal, paths=paths)

    def _on_upload(self, *, horizontal: bool) -> None:
        paths, _filter = QFileDialog.getOpenFileNames(
            self,
            "选择片尾视频",
            "",
            "视频文件 (*.mp4 *.mov *.mkv *.avi *.m4v *.webm);;所有文件 (*.*)",
        )
        if not paths:
            return
        self._import_paths(horizontal=horizontal, paths=paths)

    def _on_delete(self, horizontal: bool, item: OutroItem) -> None:
        w = Dialog(
            "删除片尾",
            "确定删除该片尾吗？删除后无法恢复。",
            self,
        )
        setup_confirm_dialog(w, window_title="删除片尾")
        if not w.exec():
            return
        remove_outro_item(horizontal, item.id)
        self._reload_section(horizontal=horizontal)
        show_toast(self, "已删除片尾", title="片尾设置")
