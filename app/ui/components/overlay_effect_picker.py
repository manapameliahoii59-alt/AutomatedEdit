"""花字/特效样式墙：分组网格挑选，替代下拉列表。"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import PushButton

from app.common.overlay_text_settings import (
    EFFECT_CATEGORY_LABELS,
    clamp_text_effect,
    effect_label,
    effect_style,
    effects_in_category,
    font_filename,
)


def _huazi_card_pixmap(effect_id: str) -> QPixmap | None:
    """为综艺花字卡片生成小缩略图。"""
    from app.common.huazi_render import render_huazi_image
    from app.common.huazi_styles import is_huazi_effect

    if not is_huazi_effect(effect_id):
        return None
    windir = os.environ.get("WINDIR", "C:/Windows")
    font_path = os.path.join(windir, "Fonts", "msyhbd.ttc")
    if not os.path.isfile(font_path):
        font_path = os.path.join(windir, "Fonts", font_filename("msyh"))
    if not os.path.isfile(font_path):
        return None
    try:
        img = render_huazi_image(
            "花字",
            effect_id,
            font_path=font_path,
            fontsize=28,
            opacity=1.0,
        )
    except Exception:
        return None
    # 缩放到卡片宽度内
    max_w, max_h = 96, 48
    img.thumbnail((max_w, max_h))
    data = img.tobytes("raw", "RGBA")
    qimg = QImage(
        data, img.width, img.height, QImage.Format.Format_RGBA8888
    ).copy()
    return QPixmap.fromImage(qimg)


class _EffectCard(QToolButton):
    """单张花字卡片：样例字 + 名称。"""

    doubleActivated = Signal(str)

    def __init__(self, effect_id: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.effect_id = effect_id
        style = effect_style(effect_id)
        glow = QColor(style["default_glow"] or "#FFFFFF")
        fill = QColor(style["suggest_fill"] or "#FFFFFF")
        if not style["suggest_fill"]:
            fill = QColor("#FFFFFF")
        self.setCheckable(True)
        self.setAutoExclusive(False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(108, 88)
        self.setToolTip(style["label"])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 8, 6, 6)
        layout.setSpacing(4)

        sample = QLabel(self)
        sample.setAlignment(Qt.AlignmentFlag.AlignCenter)
        thumb = _huazi_card_pixmap(effect_id)
        if thumb is not None and not thumb.isNull():
            sample.setPixmap(thumb)
            sample.setStyleSheet("background: transparent; border: none;")
        else:
            sample.setText("花字")
            sample.setFont(QFont("Microsoft YaHei", 16, QFont.Weight.Bold))
            sample.setStyleSheet(
                f"color: {fill.name()}; background: transparent; border: none;"
            )
        name = QLabel(style["label"], self)
        name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name.setWordWrap(True)
        name.setStyleSheet(
            "color: #ddd; font-size: 11px; background: transparent; border: none;"
        )
        layout.addWidget(sample, 1)
        layout.addWidget(name, 0)

        self._base_border = glow.name()
        self._refresh_chrome(False)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: ANN001
        self.doubleActivated.emit(self.effect_id)
        super().mouseDoubleClickEvent(event)

    def _refresh_chrome(self, selected: bool) -> None:
        border = "#f2c14e" if selected else self._base_border
        width = 2 if selected else 1
        self.setStyleSheet(
            "QToolButton {"
            f"background-color: #1a1a1a;"
            f"border: {width}px solid {border};"
            "border-radius: 8px;"
            "padding: 0px;"
            "}"
            "QToolButton:hover {"
            "background-color: #252525;"
            "}"
        )

    def setChecked(self, checked: bool) -> None:  # noqa: N802
        super().setChecked(checked)
        self._refresh_chrome(checked)


class OverlayEffectPickerDialog(QDialog):
    """分组样式墙；双击卡片或点确定选用。"""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        current: str = "none",
        huazi_only: bool = False,
    ):
        super().__init__(parent)
        self.setWindowTitle("选择花字" if huazi_only else "选择样式")
        self.setMinimumSize(560, 480)
        self._selected = clamp_text_effect(current)
        self._cards: dict[str, _EffectCard] = {}
        self._huazi_only = bool(huazi_only)

        root = QVBoxLayout(self)
        tip = QLabel(
            "点击卡片选中，确定后应用。"
            if huazi_only
            else "点击卡片预览选中，确定后应用到文字组。",
            self,
        )
        tip.setStyleSheet("color: #888;")
        root.addWidget(tip)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget(scroll)
        body_layout = QVBoxLayout(body)
        body_layout.setSpacing(14)

        categories = (
            (("huazi", "花字"),)
            if self._huazi_only
            else EFFECT_CATEGORY_LABELS
        )
        for cat_id, cat_label in categories:
            items = effects_in_category(cat_id)
            if not items:
                continue
            # 仅花字时不必再挂小标题
            if not self._huazi_only or len(categories) > 1:
                header = QLabel(cat_label, body)
                header.setStyleSheet("font-weight: 600; font-size: 13px;")
                body_layout.addWidget(header)
            grid = QGridLayout()
            grid.setSpacing(8)
            cols = 4
            for i, (eid, _label) in enumerate(items):
                card = _EffectCard(eid, body)
                card.clicked.connect(
                    lambda _checked=False, e=eid: self._on_card(e)
                )
                card.doubleActivated.connect(self._accept_effect)
                self._cards[eid] = card
                grid.addWidget(card, i // cols, i % cols)
            body_layout.addLayout(grid)

        body_layout.addStretch(1)
        scroll.setWidget(body)
        root.addWidget(scroll, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self._sync_checked()

    def _on_card(self, effect_id: str) -> None:
        self._selected = clamp_text_effect(effect_id)
        self._sync_checked()

    def _accept_effect(self, effect_id: str) -> None:
        self._selected = clamp_text_effect(effect_id)
        self.accept()

    def _sync_checked(self) -> None:
        for eid, card in self._cards.items():
            card.setChecked(eid == self._selected)

    def selected_effect(self) -> str:
        return self._selected


class OverlayEffectSelectRow(QWidget):
    """编辑区一行：当前花字名 +「选花字」按钮。"""

    effectChanged = Signal(str)

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        huazi_only: bool = False,
    ):
        super().__init__(parent)
        self._effect = "none"
        self._blocked = False
        self._huazi_only = bool(huazi_only)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        self._name = QLabel(self._display_name("none"), self)
        self._name.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        self._btn = PushButton("选花字", self)
        self._btn.setFixedWidth(72)
        self._btn.clicked.connect(self._open_picker)
        row.addWidget(self._name, 1)
        row.addWidget(self._btn, 0)

    def _display_name(self, effect_id: str) -> str:
        eid = clamp_text_effect(effect_id)
        if eid == "none":
            return "未选择花字"
        return effect_label(eid)

    def current_effect(self) -> str:
        return self._effect

    def set_effect(self, effect_id: str, *, emit: bool = False) -> None:
        eid = clamp_text_effect(effect_id)
        self._effect = eid
        self._name.setText(self._display_name(eid))
        if emit and not self._blocked:
            self.effectChanged.emit(eid)

    def blockSignals(self, block: bool) -> bool:  # noqa: N802
        self._blocked = bool(block)
        return super().blockSignals(block)

    def _open_picker(self) -> None:
        dlg = OverlayEffectPickerDialog(
            self,
            current=self._effect,
            huazi_only=self._huazi_only,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        self.set_effect(dlg.selected_effect(), emit=not self._blocked)
