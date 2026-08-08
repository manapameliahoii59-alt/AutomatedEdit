"""画面叠字可视化预览：黑底画布 + 基准线 + 可拖拽剧名/提示；键盘微调位置。"""

from __future__ import annotations

import os
from typing import Literal

from PySide6.QtCore import QEvent, QPoint, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QFontMetrics,
    QImage,
    QMouseEvent,
    QPainter,
    QPen,
    QPixmap,
    QResizeEvent,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QGraphicsDropShadowEffect,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.common.overlay_text_settings import (
    DEFAULT_DISCLAIMER,
    DEFAULT_POSITION_MARGIN_PCT,
    DEFAULT_TITLE,
    Orientation,
    OverlayTextStyle,
    align_for_position_preset,
    apply_text_layout,
    clamp_font_key,
    clamp_overlay_fontsize,
    clamp_text_effect,
    clamp_text_layout,
    effect_style,
    font_filename,
    nearest_position_preset,
    pct_for_position_preset,
    position_for_orientation,
    resolve_glow_color,
    resolve_overlay_text,
    step_position_preset,
    style_for_orientation,
    top_left_pct_for_align,
)

Which = Literal["title", "disclaimer"]

# 预览字号与成片同比（相对 1280/720 画布），保证左侧位置百分比可信
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


class _GuideCanvas(QWidget):
    """预览画布：深色底 + 中心/三分/安全边距基准线。"""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setStyleSheet("background-color: #111111;")
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)

    def paintEvent(self, event) -> None:  # noqa: ANN001
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.fillRect(self.rect(), QColor("#111111"))
        w = self.width()
        h = self.height()
        if w < 8 or h < 8:
            painter.end()
            return

        # 安全边距框
        m = max(2, int(round(min(w, h) * DEFAULT_POSITION_MARGIN_PCT / 100.0)))
        margin_pen = QPen(QColor(255, 255, 255, 55))
        margin_pen.setStyle(Qt.PenStyle.DashLine)
        margin_pen.setWidth(1)
        painter.setPen(margin_pen)
        painter.drawRect(m, m, max(1, w - 2 * m - 1), max(1, h - 2 * m - 1))

        # 三分线
        third_pen = QPen(QColor(255, 255, 255, 38))
        third_pen.setStyle(Qt.PenStyle.DotLine)
        painter.setPen(third_pen)
        for i in (1, 2):
            x = int(round(w * i / 3.0))
            y = int(round(h * i / 3.0))
            painter.drawLine(x, 0, x, h)
            painter.drawLine(0, y, w, y)

        # 中心十字（略亮，方便对准）
        center_pen = QPen(QColor(242, 193, 78, 110))
        center_pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(center_pen)
        cx, cy = w // 2, h // 2
        painter.drawLine(cx, 0, cx, h)
        painter.drawLine(0, cy, w, cy)

        painter.end()
        super().paintEvent(event)


class _DraggableLabel(QLabel):
    pressed = Signal(str)
    dragged = Signal(str, float, float, str, str)  # which, x, y, h_align, v_align
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
        x_pct = 100.0 * x / w
        y_pct = 100.0 * y / h
        bw = self.width() / w
        bh = self.height() / h
        preset = nearest_position_preset(
            x_pct, y_pct, box_w_ratio=bw, box_h_ratio=bh
        )
        h_align, v_align = align_for_position_preset(preset)
        self.dragged.emit(self._which, x_pct, y_pct, h_align, v_align)
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
    """左预览：横/竖屏画布、基准线、叠字拖动；WASD / 方向键按九宫格跳格。"""

    positionChanged = Signal(str, float, float, str, str)  # which, x, y, h_align, v_align
    itemSelected = Signal(str)  # which
    fontSizeChanged = Signal(str, int)  # which, fontsize

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setMinimumSize(280, 360)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._orientation: Orientation = "portrait"
        self._project_name = "剧名示例"
        self._title: OverlayTextStyle | dict = {}
        self._disclaimer: OverlayTextStyle | dict = {}
        self._selected: Which = "title"
        self._updating = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        self._stage = QWidget(self)
        self._stage.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._stage.setMinimumHeight(200)
        self._stage.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        root.addWidget(self._stage, 1)

        self._canvas = _GuideCanvas(self._stage)
        self._canvas.setFocusPolicy(Qt.FocusPolicy.ClickFocus)

        self._title_label = _DraggableLabel("title", self._canvas)
        self._disc_label = _DraggableLabel("disclaimer", self._canvas)
        self._title_label.pressed.connect(self._on_pressed)
        self._disc_label.pressed.connect(self._on_pressed)
        self._title_label.dragged.connect(self._on_dragged)
        self._disc_label.dragged.connect(self._on_dragged)
        self._title_label.wheelNudged.connect(self._on_wheel_nudge)
        self._disc_label.wheelNudged.connect(self._on_wheel_nudge)

        # 等子控件建完再装过滤器，避免构造期事件访问未就绪属性
        self._stage.installEventFilter(self)
        self._canvas.installEventFilter(self)
        self._title_label.installEventFilter(self)
        self._disc_label.installEventFilter(self)

        tip = QLabel(
            "点击预览选中文字后：WASD / 方向键按九宫格移动一格 · 虚线为基准线",
            self,
        )
        tip.setStyleSheet("color: #999; font-size: 11px;")
        tip.setWordWrap(True)
        root.addWidget(tip, 0)

    def eventFilter(self, obj, event) -> bool:  # noqa: ANN001
        canvas = getattr(self, "_canvas", None)
        if canvas is None:
            return super().eventFilter(obj, event)
        et = event.type()
        watched = (
            canvas,
            getattr(self, "_stage", None),
            getattr(self, "_title_label", None),
            getattr(self, "_disc_label", None),
        )
        if obj in watched and et == QEvent.Type.Wheel:
            self.wheelEvent(event)  # type: ignore[arg-type]
            return True
        if obj in watched and et == QEvent.Type.KeyPress:
            if self._handle_grid_key(event):  # type: ignore[arg-type]
                return True
        return super().eventFilter(obj, event)

    def orientation(self) -> Orientation:
        return self._orientation

    def selected(self) -> Which:
        return self._selected

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
        self._selected = which if which == "disclaimer" else "title"
        self._refresh_labels()

    def keyPressEvent(self, event) -> None:  # noqa: ANN001
        if self._handle_grid_key(event):
            return
        super().keyPressEvent(event)

    def _handle_grid_key(self, event) -> bool:  # noqa: ANN001
        """WASD / 方向键：在九宫格上移动一格。"""
        if self._updating:
            return False
        key = event.key()
        dcol = drow = 0
        if key in (Qt.Key.Key_A, Qt.Key.Key_Left):
            dcol = -1
        elif key in (Qt.Key.Key_D, Qt.Key.Key_Right):
            dcol = 1
        elif key in (Qt.Key.Key_W, Qt.Key.Key_Up):
            drow = -1
        elif key in (Qt.Key.Key_S, Qt.Key.Key_Down):
            drow = 1
        else:
            return False
        self._move_selected_grid(dcol=dcol, drow=drow)
        event.accept()
        return True

    def _move_selected_grid(self, *, dcol: int, drow: int) -> None:
        label = (
            self._title_label
            if self._selected == "title"
            else self._disc_label
        )
        if not label.isVisible():
            return
        cw = max(1, self._canvas.width())
        ch = max(1, self._canvas.height())
        bw = label.width() / cw
        bh = label.height() / ch
        pos = label.pos()
        x_pct = 100.0 * pos.x() / cw
        y_pct = 100.0 * pos.y() / ch
        current = nearest_position_preset(
            x_pct, y_pct, box_w_ratio=bw, box_h_ratio=bh
        )
        target = step_position_preset(current, dcol=dcol, drow=drow)
        nx, ny = pct_for_position_preset(
            target, box_w_ratio=bw, box_h_ratio=bh
        )
        h_align, v_align = align_for_position_preset(target)
        self._clamp_label_pos(
            label,
            QPoint(int(round(cw * nx / 100.0)), int(round(ch * ny / 100.0))),
        )
        new_pos = label.pos()
        self.positionChanged.emit(
            self._selected,
            100.0 * new_pos.x() / cw,
            100.0 * new_pos.y() / ch,
            h_align,
            v_align,
        )

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
        self.setFocus(Qt.FocusReason.MouseFocusReason)
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

    def _on_dragged(
        self, which: str, x_pct: float, y_pct: float, h_align: str, v_align: str
    ) -> None:
        if self._updating:
            return
        self.positionChanged.emit(which, x_pct, y_pct, h_align, v_align)

    def _layout_canvas(self) -> None:
        margin = 8
        avail_w = max(1, self._stage.width() - 2 * margin)
        avail_h = max(1, self._stage.height() - 2 * margin)
        if self._orientation == "landscape":
            target_w, target_h = 16, 9
        else:
            target_w, target_h = 9, 16
        scale = min(avail_w / target_w, avail_h / target_h)
        cw = int(target_w * scale)
        ch = int(target_h * scale)
        x = (self._stage.width() - cw) // 2
        y = (self._stage.height() - ch) // 2
        self._canvas.setGeometry(x, y, cw, ch)

    def _ref_height(self) -> float:
        return 720.0 if self._orientation == "landscape" else 1280.0

    def _preview_font_px(self, fontsize: int, *, line_count: int = 1) -> float:
        """预览字号与成片同比；竖排多行时再按画布高度收紧，避免末字贴边被裁。"""
        canvas_h = max(1, self._canvas.height())
        true_scale = canvas_h / self._ref_height()
        px = max(1.0, float(fontsize) * true_scale)
        px = min(px, canvas_h * _MAX_PREVIEW_FONT_RATIO)
        n = max(1, int(line_count))
        if n > 1:
            # 预留边框/抗锯齿，保证 n 行 lineSpacing 能完整落在画布内
            max_px = max(1.0, (canvas_h - 8) / (n * 1.35))
            px = min(px, max_px)
        return px

    def _selection_border(self, which: Which) -> str:
        if which == self._selected:
            return "1px solid #f2c14e"
        return "1px solid transparent"

    def _apply_label_style(self, label: _DraggableLabel, style: dict, text: str) -> None:
        from app.common.huazi_styles import is_huazi_effect

        color = style.get("color") or "#FFFFFF"
        opacity = float(style.get("opacity") or 1.0)
        fontsize = clamp_overlay_fontsize(style.get("fontsize"), 16)
        font_key = str(style.get("font") or "msyh").strip().lower()
        effect_id = clamp_text_effect(style.get("effect"))
        border = self._selection_border(label._which)
        label.setFrameShape(QLabel.Shape.NoFrame)
        label.setGraphicsEffect(None)

        layout = clamp_text_layout(style.get("layout") or "horizontal")
        display = apply_text_layout(text, layout)
        visible = bool(text.strip())
        label.setVisible(visible)
        vertical = layout == "vertical"
        line_count = display.count("\n") + 1 if display else 1
        px = self._preview_font_px(
            fontsize, line_count=line_count if vertical else 1
        )

        if visible and is_huazi_effect(effect_id):
            self._apply_huazi_pixmap(label, display, style, px, border)
            return

        family = _preview_font_family(font_key)
        font = QFont(family)
        if font_key == "msyhbd":
            font.setBold(True)
        font.setPixelSize(max(1, int(round(px))))
        label.setFont(font)
        qcolor = QColor(color)
        qcolor.setAlphaF(max(0.0, min(1.0, opacity)))
        # 不用 stylesheet padding（会挤占内容区导致下半截被裁），边距靠 resize 留白
        label.clear()
        label.setMargin(0)
        label.setIndent(0)
        label.setWordWrap(False)
        # 避免 sizeHint 把横排撑出大块右下空白
        label.setMinimumSize(1, 1)
        label.setStyleSheet(
            f"color: rgba({qcolor.red()},{qcolor.green()},{qcolor.blue()},"
            f"{qcolor.alphaF():.3f});"
            f"background: transparent;"
            f"border: {border};"
            f"padding: 0px;"
            f"margin: 0px;"
        )
        label.setText(display)
        self._resize_label_to_text(label, display, font, vertical=vertical)
        self._apply_preview_glow(label, style, px)
    def _apply_huazi_pixmap(
        self,
        label: _DraggableLabel,
        display: str,
        style: dict,
        font_px: float,
        border: str,
    ) -> None:
        from app.common.huazi_render import render_huazi_image

        font_key = clamp_font_key(style.get("font") or "msyh")
        windir = os.environ.get("WINDIR", "C:/Windows")
        font_path = os.path.join(windir, "Fonts", font_filename(font_key))
        if not os.path.isfile(font_path):
            font_path = os.path.join(windir, "Fonts", "msyh.ttc")
        try:
            img = render_huazi_image(
                display,
                clamp_text_effect(style.get("effect")),
                font_path=font_path,
                fontsize=max(8, int(round(font_px))),
                opacity=float(style.get("opacity") or 1.0),
            )
        except Exception:
            label.clear()
            label.setText(display)
            return
        # 去掉发光预留透明边，选框贴紧可见字形
        bbox = img.getbbox()
        if bbox is not None:
            img = img.crop(bbox)
        data = img.tobytes("raw", "RGBA")
        qimg = QImage(
            data,
            img.width,
            img.height,
            QImage.Format.Format_RGBA8888,
        ).copy()
        pix = QPixmap.fromImage(qimg)
        label.setMargin(0)
        label.setIndent(0)
        label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        label.setStyleSheet(
            f"background: transparent; border: {border}; padding: 0px; margin: 0px;"
        )
        label.setText("")
        label.setPixmap(pix)
        # 仅 1px 边框占位，不再额外撑大选框
        label.resize(max(1, pix.width() + 2), max(1, pix.height() + 2))

    @staticmethod
    def _apply_preview_glow(
        label: QLabel, style: dict, font_px: float
    ) -> None:
        from app.common.huazi_styles import is_huazi_effect

        effect_id = clamp_text_effect(style.get("effect"))
        if (
            effect_id == "none"
            or is_huazi_effect(effect_id)
            or not label.isVisible()
        ):
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
            max_r = max(estyle["radii"]) if estyle["radii"] else 0.26
            # 与成片近缘辉光对齐：半径更小，避免预览「一团光」与成片重影反差
            glow.setAlphaF(0.55 + min(0.22, max_r * 0.5))
            blur = max(10.0, font_px * (0.55 + max_r * 1.2))
        shadow = QGraphicsDropShadowEffect(label)
        shadow.setBlurRadius(blur)
        shadow.setColor(glow)
        shadow.setOffset(0, 0)
        label.setGraphicsEffect(shadow)

    @staticmethod
    def _resize_label_to_text(
        label: QLabel,
        display: str,
        font: QFont,
        *,
        vertical: bool = False,
    ) -> None:
        """横/竖排分别测尺寸：竖排按行距留足高度；横排按字宽收紧。"""
        fm = QFontMetrics(font)
        lines = display.split("\n") if display else [""]
        n = max(1, len(lines))
        # 边框占 1px×2，内容区高度必须 >= 文字排版高度，否则末字被吃
        border = 2
        label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        label.setMinimumSize(1, 1)

        if vertical:
            # 按墨水宽收紧；高度用 height（非 lineSpacing），避免选框虚高导致贴边空隙偏大
            text_w = 1
            for line in lines:
                tr = fm.tightBoundingRect(line if line.strip() else "字")
                text_w = max(text_w, tr.x() + tr.width())
            gap = max(0, int(round(fm.height() * 0.12)))
            inner_h = fm.height() * n + gap * max(0, n - 1)
            label.resize(max(1, text_w + border), max(1, inner_h + border))
            return

        # 横排：horizontalAdvance 右侧常多于实际墨水；用 tight 右缘收紧选框
        tr = fm.tightBoundingRect(display)
        text_w = max(1, tr.x() + tr.width())
        # 高度收到墨水底边（相对基线），避免下方假空白
        text_h = max(1, fm.ascent() + tr.y() + tr.height())
        label.resize(max(1, text_w + border), max(1, text_h + border))

    def _place_label(self, label: QLabel, style: dict) -> None:
        if not label.isVisible():
            return
        pos = position_for_orientation(style, self._orientation)
        w = max(1, self._canvas.width())
        h = max(1, self._canvas.height())
        bw = label.width() / w
        bh = label.height() / h
        x_pct, y_pct = top_left_pct_for_align(
            pos, box_w_ratio=bw, box_h_ratio=bh
        )
        x = int(round(w * x_pct / 100.0))
        y = int(round(h * y_pct / 100.0))
        # 与画布边缘留 1px，避免末行贴边被父控件裁切
        max_x = max(0, w - label.width() - 1)
        max_y = max(0, h - label.height() - 1)
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
