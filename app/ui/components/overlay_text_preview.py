"""画面叠字可视化预览：黑底画布 + 可拖拽剧名/提示标签。"""

from __future__ import annotations

import os
from typing import Literal

from PySide6.QtCore import QEvent, QPoint, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QFontMetrics,
    QMouseEvent,
    QPainter,
    QResizeEvent,
    QWheelEvent,
)
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QLabel, QWidget

from app.common.overlay_text_settings import (
    DEFAULT_DISCLAIMER,
    DEFAULT_TITLE,
    Orientation,
    OverlayTextStyle,
    apply_text_layout,
    clamp_font_key,
    clamp_overlay_fontsize,
    clamp_text_effect,
    effect_style,
    font_filename,
    position_for_orientation,
    resolve_glow_color,
    resolve_overlay_text,
    style_for_orientation,
)

Which = Literal["title", "disclaimer"]

# 预览字号与成片同比（相对 1280/720 画布），保证左侧位置百分比可信
_LABEL_PAD = 2
_MAX_PREVIEW_FONT_RATIO = 0.14  # 避免竖排过高把坐标夹死

# 预览用的 Qt 字体族回退名（优先从 Fonts 目录按文件加载）
_PREVIEW_FONT_FAMILY = {
    "msyh": "Microsoft YaHei",
    "msyhbd": "Microsoft YaHei",
    "msyhl": "Microsoft YaHei Light",
    "simhei": "SimHei",
    "simsun": "SimSun",
    "simsunb": "SimSun",
    "simkai": "KaiTi",
    "simfang": "FangSong",
    "simli": "LiSu",
    "simyou": "YouYuan",
    "stxingka": "STXingkai",
    "stxinwei": "STXinwei",
    "stkaiti": "STKaiti",
    "stliti": "STLiti",
    "sthupo": "STHupo",
    "stcaiyun": "STCaiyun",
    "stxihei": "STXihei",
    "stzhongs": "STZhongsong",
    "stsong": "STSong",
    "stfangso": "STFangsong",
    "fzstk": "FZShuTi",
    "fzytk": "FZYaoTi",
}
_LOADED_FONT_FAMILY: dict[str, str] = {}


def _preview_font_family(font_key: str) -> str:
    """按字体文件加载，保证剧名/提示选不同字时预览真的不一样。"""
    key = clamp_font_key(font_key)
    cached = _LOADED_FONT_FAMILY.get(key)
    if cached:
        return cached
    windir = os.environ.get("WINDIR", "C:/Windows")
    path = os.path.join(windir, "Fonts", font_filename(key))
    family = _PREVIEW_FONT_FAMILY.get(key, "Microsoft YaHei")
    if os.path.isfile(path):
        fid = QFontDatabase.addApplicationFont(path)
        if fid >= 0:
            families = QFontDatabase.applicationFontFamilies(fid)
            if families:
                family = families[0]
    _LOADED_FONT_FAMILY[key] = family
    return family


class _DraggableLabel(QLabel):
    pressed = Signal(str)
    dragged = Signal(str, float, float)  # which, x_pct, y_pct
    wheelNudged = Signal(str, int)  # which, step (+/-)

    def __init__(self, which: Which, parent: QWidget):
        super().__init__(parent)
        self._which = which
        self._dragging = False
        self._grab_offset = QPoint()
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

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

    def wheelEvent(self, event: QWheelEvent) -> None:
        delta = event.angleDelta().y()
        if delta == 0:
            super().wheelEvent(event)
            return
        step = 1 if delta > 0 else -1
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            step *= 5
        self.pressed.emit(self._which)
        self.wheelNudged.emit(self._which, step)
        event.accept()


class OverlayTextPreview(QWidget):
    """左预览：按横/竖屏比例显示样例画布，叠字可拖动；选中后滚轮调字号。"""

    positionChanged = Signal(str, float, float)  # which, x_pct, y_pct
    itemSelected = Signal(str)  # which
    fontSizeChanged = Signal(str, int)  # which, fontsize

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setMinimumSize(280, 360)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self._orientation: Orientation = "portrait"
        self._project_name = "剧名示例"
        self._title: OverlayTextStyle | dict = {}
        self._disclaimer: OverlayTextStyle | dict = {}
        self._selected: Which = "title"

        self._canvas = QWidget(self)
        self._canvas.setStyleSheet("background-color: #111111;")
        self._canvas.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self._canvas.installEventFilter(self)

        self._title_label = _DraggableLabel("title", self._canvas)
        self._disc_label = _DraggableLabel("disclaimer", self._canvas)
        self._title_label.pressed.connect(self._on_pressed)
        self._disc_label.pressed.connect(self._on_pressed)
        self._title_label.dragged.connect(self._on_dragged)
        self._disc_label.dragged.connect(self._on_dragged)
        self._title_label.wheelNudged.connect(self._on_wheel_nudge)
        self._disc_label.wheelNudged.connect(self._on_wheel_nudge)

        self._updating = False

    def eventFilter(self, obj, event) -> bool:  # noqa: ANN001
        if obj is self._canvas and event.type() == QEvent.Type.Wheel:
            self.wheelEvent(event)  # type: ignore[arg-type]
            return True
        return super().eventFilter(obj, event)

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

    def showEvent(self, event) -> None:  # noqa: ANN001
        super().showEvent(event)
        # 对话框布局完成后再排一次，避免首次几何为 0 时位置跑偏
        self._layout_canvas()
        self._refresh_labels()

    def paintEvent(self, event) -> None:  # noqa: ANN001
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#3a3a3a"))
        painter.end()
        super().paintEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        # 画布空白处滚轮：调整当前选中项字号
        delta = event.angleDelta().y()
        if delta == 0 or self._updating:
            super().wheelEvent(event)
            return
        step = 1 if delta > 0 else -1
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            step *= 5
        self._on_wheel_nudge(self._selected, step)
        event.accept()

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

    def _on_wheel_nudge(self, which: str, step: int) -> None:
        if self._updating or not step:
            return
        key: Which = "title" if which == "title" else "disclaimer"
        self._selected = key
        style = self._title if key == "title" else self._disclaimer
        if not isinstance(style, dict):
            return
        # 按当前横/竖方向取字号，避免改到另一向
        cur = clamp_overlay_fontsize(
            position_for_orientation(style, self._orientation).get("fontsize"),
            16,
        )
        new = clamp_overlay_fontsize(cur + step, cur)
        if new == cur:
            return
        self.fontSizeChanged.emit(key, new)

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
        """预览字号与成片同比，保证拖拽位置与右侧百分比一致。"""
        canvas_h = max(1, self._canvas.height())
        true_scale = canvas_h / self._ref_height()
        px = max(1.0, float(fontsize) * true_scale)
        return min(px, canvas_h * _MAX_PREVIEW_FONT_RATIO)

    def _selection_border(self, which: Which) -> str:
        if which == self._selected:
            return "1px solid #f2c14e"
        return "1px solid transparent"

    def _apply_label_style(self, label: _DraggableLabel, style: dict, text: str) -> None:
        color = style.get("color") or "#FFFFFF"
        opacity = float(style.get("opacity") or 1.0)
        fontsize = clamp_overlay_fontsize(style.get("fontsize"), 16)
        px = self._preview_font_px(fontsize)
        font_key = str(style.get("font") or "msyh").strip().lower()
        family = _preview_font_family(font_key)
        font = QFont(family)
        if font_key == "msyhbd":
            font.setBold(True)
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
        self._apply_preview_glow(label, style, px)

    @staticmethod
    def _apply_preview_glow(
        label: QLabel, style: dict, font_px: float
    ) -> None:
        effect_id = clamp_text_effect(style.get("effect"))
        if effect_id == "none" or not label.isVisible():
            label.setGraphicsEffect(None)
            return
        estyle = effect_style(effect_id)
        # 大半径模糊阴影 ≈ 柔和外发光；纯描边风格用深色窄阴影近似
        if not estyle["radii"]:
            glow = QColor(estyle["outline_color"] or "#000000")
            glow.setAlphaF(0.88)
            blur = max(3.0, font_px * max(0.12, estyle["outline_ratio"] * 1.6))
        else:
            glow = QColor(resolve_glow_color(style))
            max_r = max(estyle["radii"]) if estyle["radii"] else 0.4
            glow.setAlphaF(0.72 + min(0.18, max_r * 0.2))
            blur = max(22.0, font_px * (1.4 + max_r))
        shadow = QGraphicsDropShadowEffect(label)
        shadow.setBlurRadius(blur)
        shadow.setColor(glow)
        shadow.setOffset(0, 0)
        label.setGraphicsEffect(shadow)

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
            title_view = style_for_orientation(
                self._title, self._orientation, defaults=DEFAULT_TITLE
            )
            disc_view = style_for_orientation(
                self._disclaimer, self._orientation, defaults=DEFAULT_DISCLAIMER
            )
            title_text = resolve_overlay_text(
                str(title_view.get("text", "")), self._project_name
            )
            disc_text = resolve_overlay_text(
                str(disc_view.get("text", "")), self._project_name
            )
            self._apply_label_style(self._title_label, title_view, title_text)
            self._apply_label_style(self._disc_label, disc_view, disc_text)
            self._place_label(self._title_label, title_view)
            self._place_label(self._disc_label, disc_view)
        finally:
            self._updating = False
