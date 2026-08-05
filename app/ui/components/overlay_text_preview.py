"""画面叠字可视化预览：黑底画布 + 可拖拽剧名/提示标签。"""

from __future__ import annotations

from typing import Literal

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QMouseEvent, QPainter, QResizeEvent
from PySide6.QtWidgets import QLabel, QWidget

from app.common.overlay_text_settings import (
    Orientation,
    OverlayTextStyle,
    apply_text_layout,
    position_for_orientation,
    resolve_overlay_text,
)

Which = Literal["title", "disclaimer"]

# 预览字号至少按 1:1 像素档位显示，避免 15/16 被缩成同一像素；
# 真实成片仍按画布比例理解位置，字号仅预览加重量级差异。
_MIN_PREVIEW_FONT_SCALE = 1.0
_LABEL_PAD = 2
_MAX_PREVIEW_FONT_RATIO = 0.18  # 单行预览字号不超过画布高度的 18%


class _DraggableLabel(QLabel):
    pressed = Signal(str)
    dragged = Signal(str, float, float)  # which, x_pct, y_pct

    def __init__(self, which: Which, parent: QWidget):
        super().__init__(parent)
        self._which = which
        self._dragging = False
        self._grab_offset = QPoint()
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._grab_offset = event.position().toPoint()
            self.pressed.emit(self._which)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if not self._dragging:
            super().mouseMoveEvent(event)
            return
        canvas = self.parentWidget()
        if canvas is None:
            return
        top_left = self.mapToParent(event.position().toPoint() - self._grab_offset)
        max_x = max(0, canvas.width() - self.width())
        max_y = max(0, canvas.height() - self.height())
        x = max(0, min(max_x, top_left.x()))
        y = max(0, min(max_y, top_left.y()))
        self.move(x, y)
        w = max(1, canvas.width())
        h = max(1, canvas.height())
        self.dragged.emit(self._which, 100.0 * x / w, 100.0 * y / h)
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
            event.accept()
            return
        super().mouseReleaseEvent(event)


class OverlayTextPreview(QWidget):
    """左预览：按横/竖屏比例显示样例画布，叠字可拖动。"""

    positionChanged = Signal(str, float, float)  # which, x_pct, y_pct
    itemSelected = Signal(str)  # which

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setMinimumSize(280, 360)
        self._orientation: Orientation = "portrait"
        self._project_name = "剧名示例"
        self._title: OverlayTextStyle | dict = {}
        self._disclaimer: OverlayTextStyle | dict = {}
        self._selected: Which = "title"

        self._canvas = QWidget(self)
        self._canvas.setStyleSheet("background-color: #111111;")

        self._title_label = _DraggableLabel("title", self._canvas)
        self._disc_label = _DraggableLabel("disclaimer", self._canvas)
        self._title_label.pressed.connect(self._on_pressed)
        self._disc_label.pressed.connect(self._on_pressed)
        self._title_label.dragged.connect(self._on_dragged)
        self._disc_label.dragged.connect(self._on_dragged)

        self._updating = False

    def orientation(self) -> Orientation:
        return self._orientation

    def set_orientation(self, orientation: Orientation) -> None:
        self._orientation = "landscape" if orientation == "landscape" else "portrait"
        self._layout_canvas()
        self._refresh_labels()

    def set_project_name(self, name: str) -> None:
        self._project_name = name or "剧名示例"
        self._refresh_labels()

    def set_styles(
        self,
        title: OverlayTextStyle | dict,
        disclaimer: OverlayTextStyle | dict,
    ) -> None:
        self._title = dict(title)
        self._disclaimer = dict(disclaimer)
        self._refresh_labels()

    def set_selected(self, which: Which) -> None:
        self._selected = which
        self._refresh_labels()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._layout_canvas()
        self._refresh_labels()

    def paintEvent(self, event) -> None:  # noqa: ANN001
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#3a3a3a"))
        painter.end()
        super().paintEvent(event)

    def _on_pressed(self, which: str) -> None:
        self._selected = which  # type: ignore[assignment]
        # 换选中描边时保持当前拖拽位置，避免跳回百分比坐标
        for label, style in (
            (self._title_label, self._title),
            (self._disc_label, self._disclaimer),
        ):
            pos = label.pos()
            text = resolve_overlay_text(
                str(style.get("text", "")), self._project_name
            )
            self._apply_label_style(label, style, text)
            self._clamp_label_pos(label, pos)
        self.itemSelected.emit(which)

    def _clamp_label_pos(self, label: QLabel, pos: QPoint) -> None:
        if not label.isVisible():
            return
        max_x = max(0, self._canvas.width() - label.width())
        max_y = max(0, self._canvas.height() - label.height())
        label.move(max(0, min(max_x, pos.x())), max(0, min(max_y, pos.y())))

    def _on_dragged(self, which: str, x_pct: float, y_pct: float) -> None:
        if self._updating:
            return
        self.positionChanged.emit(which, x_pct, y_pct)

    def _layout_canvas(self) -> None:
        margin = 12
        avail_w = max(1, self.width() - 2 * margin)
        avail_h = max(1, self.height() - 2 * margin)
        if self._orientation == "landscape":
            target_w, target_h = 16, 9
        else:
            target_w, target_h = 9, 16
        scale = min(avail_w / target_w, avail_h / target_h)
        cw = int(target_w * scale)
        ch = int(target_h * scale)
        x = (self.width() - cw) // 2
        y = (self.height() - ch) // 2
        self._canvas.setGeometry(x, y, cw, ch)

    def _ref_height(self) -> float:
        return 720.0 if self._orientation == "landscape" else 1280.0

    def _preview_font_px(self, fontsize: int) -> float:
        """预览字号，保证相邻整数档至少差 1 像素。"""
        canvas_h = max(1, self._canvas.height())
        true_scale = canvas_h / self._ref_height()
        scale = max(true_scale, _MIN_PREVIEW_FONT_SCALE)
        px = max(1.0, float(fontsize) * scale)
        return min(px, canvas_h * _MAX_PREVIEW_FONT_RATIO)

    def _selection_border(self, which: Which) -> str:
        if which == self._selected:
            return "1px solid #f2c14e"
        return "1px solid transparent"

    def _apply_label_style(self, label: _DraggableLabel, style: dict, text: str) -> None:
        color = style.get("color") or "#FFFFFF"
        opacity = float(style.get("opacity") or 1.0)
        fontsize = int(style.get("fontsize") or 16)
        px = self._preview_font_px(fontsize)
        font = QFont("Microsoft YaHei")
        font.setPixelSize(max(1, int(round(px))))
        label.setFont(font)
        qcolor = QColor(color)
        qcolor.setAlphaF(max(0.0, min(1.0, opacity)))
        border = self._selection_border(label._which)
        label.setFrameShape(QLabel.Shape.NoFrame)
        # 不用 stylesheet padding（会挤占内容区导致下半截被裁），边距靠 resize 留白
        label.setStyleSheet(
            f"color: rgba({qcolor.red()},{qcolor.green()},{qcolor.blue()},"
            f"{qcolor.alphaF():.3f});"
            f"background: transparent;"
            f"border: {border};"
            f"padding: 0px;"
            f"margin: 0px;"
        )
        display = apply_text_layout(text, style.get("layout") or "horizontal")
        label.setText(display)
        self._resize_label_to_text(label, display, font)
        label.setVisible(bool(text.strip()))

    @staticmethod
    def _resize_label_to_text(label: QLabel, display: str, font: QFont) -> None:
        fm = QFontMetrics(font)
        lines = display.split("\n") if display else [""]
        n = max(1, len(lines))
        text_w = max((fm.horizontalAdvance(line) for line in lines), default=0)
        # ascent+descent 盖住字形；多行只用 (n-1)*lineSpacing，避免末行再叠一段行距空白
        text_h = fm.ascent() + fm.descent() + fm.lineSpacing() * (n - 1)
        # 边框 1px×2 + 少量内边距，刚好包住文字
        chrome = (_LABEL_PAD + 1) * 2
        label.resize(max(1, text_w + chrome), max(1, text_h + chrome))

    def _place_label(self, label: QLabel, style: dict) -> None:
        if not label.isVisible():
            return
        pos = position_for_orientation(style, self._orientation)
        w = max(1, self._canvas.width())
        h = max(1, self._canvas.height())
        x = int(round(w * pos["x_pct"] / 100.0))
        y = int(round(h * pos["y_pct"] / 100.0))
        max_x = max(0, w - label.width())
        max_y = max(0, h - label.height())
        label.move(max(0, min(max_x, x)), max(0, min(max_y, y)))

    def _refresh_labels(self) -> None:
        self._updating = True
        try:
            title_text = resolve_overlay_text(
                str(self._title.get("text", "")), self._project_name
            )
            disc_text = resolve_overlay_text(
                str(self._disclaimer.get("text", "")), self._project_name
            )
            self._apply_label_style(self._title_label, self._title, title_text)
            self._apply_label_style(self._disc_label, self._disclaimer, disc_text)
            self._place_label(self._title_label, self._title)
            self._place_label(self._disc_label, self._disclaimer)
        finally:
            self._updating = False
