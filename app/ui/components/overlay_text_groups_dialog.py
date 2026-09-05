"""画面文字组列表弹框：卡片勾选启用，双击编辑，右键重命名/编辑/删除。"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMenu,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import BodyLabel, PushButton, SwitchButton, isDarkTheme

from app.common.overlay_text_settings import (
    DEFAULT_OVERLAY_GROUP_ID,
    OverlayTextGroup,
    OverlayTextLibrary,
    clamp_overlay_library,
    default_overlay_disclaimer,
    default_overlay_disclaimer2,
    default_overlay_title,
    delete_overlay_group,
    effect_label,
    load_overlay_library_from_cfg,
    make_overlay_group,
    save_overlay_library_to_cfg,
    upsert_overlay_group,
)
from app.common.utils import show_toast
from app.ui.components.overlay_text_editor_dialog import OverlayTextEditorDialog


def _card_colors(*, enabled: bool, hover: bool = False) -> tuple[str, str, str]:
    """返回 (背景, 边框, 次要文字色)。"""
    dark = isDarkTheme()
    if dark:
        bg = "#323232" if not hover else "#3a3a3a"
        border = "#f2c14e" if enabled else "#555555"
        muted = "#aaaaaa"
    else:
        bg = "#ffffff" if not hover else "#f5f7fa"
        border = "#3b8cff" if enabled else "#d8dee8"
        muted = "#6b7280"
    return bg, border, muted


class _GroupCard(QFrame):
    """单个文字组卡片。"""

    def __init__(
        self,
        group: OverlayTextGroup,
        *,
        enabled: bool,
        on_toggle_enable,
        on_edit,
        on_rename,
        on_delete,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._group = group
        self._enabled = enabled
        self._on_toggle_enable = on_toggle_enable
        self._on_edit = on_edit
        self._on_rename = on_rename
        self._on_delete = on_delete
        self._hover = False

        self.setObjectName("overlayGroupCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.setMinimumHeight(72)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_menu)

        root = QHBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(12)

        self._radio = QRadioButton(self)
        self._radio.setChecked(enabled)
        self._radio.setToolTip("勾选后渲染使用此组；取消勾选则使用「默认」组")
        self._radio.clicked.connect(self._on_radio_clicked)
        root.addWidget(self._radio, 0, Qt.AlignmentFlag.AlignVCenter)

        text_col = QVBoxLayout()
        text_col.setSpacing(4)

        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        self._name = QLabel(group["name"], self)
        self._name.setStyleSheet("font-size: 14px; font-weight: 600;")
        title_row.addWidget(self._name, 0, Qt.AlignmentFlag.AlignVCenter)
        if group["id"] == DEFAULT_OVERLAY_GROUP_ID:
            badge = QLabel("默认", self)
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            badge.setFixedHeight(18)
            badge.setStyleSheet(
                "QLabel{padding:0 6px;border-radius:9px;font-size:11px;"
                "background:#6b7280;color:#fff;}"
            )
            title_row.addWidget(badge, 0, Qt.AlignmentFlag.AlignVCenter)
        title_row.addStretch(1)
        text_col.addLayout(title_row)

        title_text = str(group["title"].get("text") or "").strip() or "（无剧名文案）"
        effect = effect_label(group["title"].get("effect"))
        disc = str(group["disclaimer"].get("text") or "").strip()
        disc_preview = (disc[:18] + "…") if len(disc) > 18 else (disc or "无提示文案")
        disc2 = str(group.get("disclaimer2", {}).get("text") or "").strip()
        disc2_preview = (disc2[:12] + "…") if len(disc2) > 12 else (disc2 or "无提示2")
        self._sub = QLabel(
            f"{title_text}  ·  {effect}  ·  {disc_preview}  ·  {disc2_preview}", self
        )
        self._sub.setWordWrap(False)
        text_col.addWidget(self._sub)
        root.addLayout(text_col, 1)

        hint = QLabel("双击编辑", self)
        hint.setStyleSheet("font-size: 11px;")
        root.addWidget(hint, 0, Qt.AlignmentFlag.AlignVCenter)

        self._apply_style()

    @property
    def group_id(self) -> str:
        return self._group["id"]

    def set_enabled_visual(self, enabled: bool) -> None:
        self._enabled = enabled
        self._radio.blockSignals(True)
        self._radio.setChecked(enabled)
        self._radio.blockSignals(False)
        self._apply_style()

    def _apply_style(self) -> None:
        bg, border, muted = _card_colors(enabled=self._enabled, hover=self._hover)
        width = 2 if self._enabled else 1
        self.setStyleSheet(
            f"QFrame#overlayGroupCard{{"
            f"background:{bg};"
            f"border:{width}px solid {border};"
            f"border-radius:10px;"
            f"}}"
        )
        self._sub.setStyleSheet(f"color:{muted};font-size:12px;")
        # 右侧提示跟 muted
        for child in self.findChildren(QLabel):
            if child is self._name:
                continue
            if child.text() == "双击编辑":
                child.setStyleSheet(f"color:{muted};font-size:11px;")

    def enterEvent(self, event) -> None:  # noqa: ANN001
        self._hover = True
        self._apply_style()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: ANN001
        self._hover = False
        self._apply_style()
        super().leaveEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: ANN001
        if event.button() == Qt.MouseButton.LeftButton:
            self._on_edit(self._group["id"])
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def _on_radio_clicked(self) -> None:
        self._on_toggle_enable(self._group["id"], self._radio.isChecked())

    def _show_menu(self, pos) -> None:  # noqa: ANN001
        menu = QMenu(self)
        act_edit = QAction("编辑", menu)
        act_rename = QAction("重命名", menu)
        act_delete = QAction("删除", menu)
        act_edit.triggered.connect(lambda: self._on_edit(self._group["id"]))
        act_rename.triggered.connect(lambda: self._on_rename(self._group["id"]))
        act_delete.triggered.connect(lambda: self._on_delete(self._group["id"]))
        menu.addAction(act_edit)
        menu.addAction(act_rename)
        menu.addAction(act_delete)
        if self._group["id"] == DEFAULT_OVERLAY_GROUP_ID:
            act_rename.setEnabled(False)
            act_rename.setText("重命名（默认组不可改名）")
            act_delete.setEnabled(False)
            act_delete.setText("删除（默认组不可删）")
        menu.exec(self.mapToGlobal(pos))


class OverlayTextGroupsDialog(QDialog):
    """文字组管理首页。确定后 library 已写入 cfg，可通过 result_library() 取回。"""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        project_name: str = "示例剧名",
    ):
        super().__init__(parent)
        self.setWindowTitle("画面文字")
        self.setMinimumSize(520, 460)
        self._project_name = project_name
        self._lib: OverlayTextLibrary = clamp_overlay_library(
            load_overlay_library_from_cfg()
        )
        self._saved: OverlayTextLibrary | None = None
        self._cards: list[_GroupCard] = []
        self._last_enabled_id: str | None = (
            str(self._lib.get("selected_id") or "") or None
        )

        root = QVBoxLayout(self)
        root.setSpacing(12)
        tip = BodyLabel(
            "勾选启用一组用于渲染；不勾选则使用「默认」。双击卡片编辑，右键可重命名/编辑/删除。",
            self,
        )
        tip.setWordWrap(True)
        root.addWidget(tip)

        no_text_row = QHBoxLayout()
        no_text_label = BodyLabel("不设置文字", self)
        no_text_label.setToolTip("打开后渲染成片不叠加剧名和提示文字")
        self._no_text_switch = SwitchButton(self)
        self._no_text_switch.setOnText("开")
        self._no_text_switch.setOffText("关")
        self._no_text_switch.setChecked(bool(self._lib.get("no_text")))
        self._no_text_switch.setToolTip(no_text_label.toolTip())
        self._no_text_switch.checkedChanged.connect(self._on_no_text_changed)
        no_text_row.addWidget(no_text_label)
        no_text_row.addWidget(self._no_text_switch)
        no_text_row.addStretch(1)
        root.addLayout(no_text_row)

        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._list_host = QWidget(self._scroll)
        self._list_layout = QVBoxLayout(self._list_host)
        self._list_layout.setContentsMargins(2, 2, 8, 2)
        self._list_layout.setSpacing(10)
        self._list_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._scroll.setWidget(self._list_host)
        root.addWidget(self._scroll, 1)

        action_row = QHBoxLayout()
        self._add_btn = PushButton("新增文字组", self)
        action_row.addWidget(self._add_btn)
        action_row.addStretch(1)
        root.addLayout(action_row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        root.addWidget(buttons)

        self._add_btn.clicked.connect(self._on_add)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)

        self._rebuild_list()
        self._apply_no_text_ui(bool(self._lib.get("no_text")))

    def result_library(self) -> OverlayTextLibrary:
        return clamp_overlay_library(self._saved or self._lib)

    def _on_no_text_changed(self, checked: bool) -> None:
        self._lib["no_text"] = bool(checked)
        self._apply_no_text_ui(bool(checked))

    def _apply_no_text_ui(self, no_text: bool) -> None:
        enabled = not no_text
        self._scroll.setEnabled(enabled)
        self._add_btn.setEnabled(enabled)

    def _reload_lib(self, *, selected_id: str | None = None) -> None:
        no_text = bool(self._lib.get("no_text"))
        sid = self._lib["selected_id"] if selected_id is None else selected_id
        self._lib = load_overlay_library_from_cfg()
        self._lib["no_text"] = no_text
        self._lib["selected_id"] = sid
        self._rebuild_list()
        self._apply_no_text_ui(no_text)

    def _rebuild_list(self) -> None:
        while self._list_layout.count():
            item = self._list_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._cards.clear()

        selected = str(self._lib.get("selected_id") or "")
        for group in self._lib["groups"]:
            card = _GroupCard(
                group,
                enabled=(group["id"] == selected),
                on_toggle_enable=self._on_toggle_enable,
                on_edit=self._edit_group,
                on_rename=self._rename_group,
                on_delete=self._delete_group,
                parent=self._list_host,
            )
            self._cards.append(card)
            self._list_layout.addWidget(card)
        self._list_layout.addStretch(1)
        self._last_enabled_id = selected or None

    def _on_toggle_enable(self, group_id: str, checked: bool) -> None:
        # 再次点已启用项 → 取消勾选（渲染回退默认组）
        if checked and self._last_enabled_id == group_id:
            self._lib["selected_id"] = ""
            self._last_enabled_id = None
            for card in self._cards:
                card.set_enabled_visual(False)
            return
        if checked:
            self._lib["selected_id"] = group_id
            self._last_enabled_id = group_id
            for card in self._cards:
                card.set_enabled_visual(card.group_id == group_id)
            return
        self._lib["selected_id"] = ""
        self._last_enabled_id = None
        for card in self._cards:
            card.set_enabled_visual(False)

    def _prompt_name(self, title: str, initial: str = "") -> str | None:
        text, ok = QInputDialog.getText(self, title, "文字组名称：", text=initial)
        if not ok:
            return None
        name = str(text).strip()
        if not name:
            return None
        return name[:64]

    def _find_group(self, gid: str | None) -> OverlayTextGroup | None:
        if not gid:
            return None
        for g in self._lib["groups"]:
            if g["id"] == gid:
                return g
        return None

    def _on_add(self) -> None:
        name = self._prompt_name("新增文字组")
        if not name:
            return
        group = make_overlay_group(
            name=name,
            title=default_overlay_title(),
            disclaimer=default_overlay_disclaimer(),
            disclaimer2=default_overlay_disclaimer2(),
        )
        editor = OverlayTextEditorDialog(
            self,
            title_style=dict(group["title"]),
            disclaimer_style=dict(group["disclaimer"]),
            disclaimer2_style=dict(group["disclaimer2"]),
            project_name=self._project_name,
            window_title=f"新增文字组 — {name}",
        )
        if editor.exec() != QDialog.DialogCode.Accepted:
            return
        title, disc, disc2 = editor.result_styles()
        group["title"] = title  # type: ignore[assignment]
        group["disclaimer"] = disc  # type: ignore[assignment]
        group["disclaimer2"] = disc2  # type: ignore[assignment]
        upsert_overlay_group(group)
        self._reload_lib(selected_id=group["id"])

    def _edit_group(self, group_id: str) -> None:
        group = self._find_group(group_id)
        if group is None:
            return
        editor = OverlayTextEditorDialog(
            self,
            title_style=dict(group["title"]),
            disclaimer_style=dict(group["disclaimer"]),
            disclaimer2_style=dict(group.get("disclaimer2") or {}),
            project_name=self._project_name,
            window_title=f"编辑文字组 — {group['name']}",
        )
        if editor.exec() != QDialog.DialogCode.Accepted:
            return
        title, disc, disc2 = editor.result_styles()
        group = {
            **group,
            "title": title,
            "disclaimer": disc,
            "disclaimer2": disc2,
        }  # type: ignore[misc]
        selected = self._lib["selected_id"]
        upsert_overlay_group(group)
        self._reload_lib(selected_id=selected)

    def _rename_group(self, group_id: str) -> None:
        group = self._find_group(group_id)
        if group is None:
            return
        if group["id"] == DEFAULT_OVERLAY_GROUP_ID:
            show_toast(self, "「默认」文字组不可重命名，只能编辑内容", title="画面文字")
            return
        name = self._prompt_name("重命名文字组", initial=group["name"])
        if not name:
            return
        group = {**group, "name": name}
        selected = self._lib["selected_id"]
        upsert_overlay_group(group)
        self._reload_lib(selected_id=selected)

    def _delete_group(self, group_id: str) -> None:
        group = self._find_group(group_id)
        if group is None:
            return
        if group["id"] == DEFAULT_OVERLAY_GROUP_ID:
            show_toast(self, "「默认」文字组不可删除", title="画面文字")
            return
        delete_overlay_group(group["id"])
        self._reload_lib()

    def _on_accept(self) -> None:
        self._lib["no_text"] = bool(self._no_text_switch.isChecked())
        self._saved = save_overlay_library_to_cfg(self._lib)
        self.accept()
