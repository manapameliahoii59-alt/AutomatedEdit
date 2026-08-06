"""画面文字编辑弹框：左预览 + 右剧名/提示参数（供文字组新增/编辑复用）。"""

from __future__ import annotations

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QButtonGroup,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import LineEdit, PushButton

from app.common.overlay_text_settings import (
    EFFECT_CHOICES,
    OVERLAY_FONTSIZE_MAX,
    OVERLAY_FONTSIZE_MIN,
    available_font_choices,
    clamp_text_effect,
    default_overlay_disclaimer,
    default_overlay_title,
    effect_style,
    position_for_orientation,
    resolve_glow_color,
    set_position_for_orientation,
    style_for_orientation,
    update_orient_style,
)
from app.ui.components.overlay_text_preview import OverlayTextPreview


class OverlayTextEditorDialog(QDialog):
    """编辑一组剧名+提示样式；Accepted 后通过 result_styles() 取回。"""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        title_style: dict | None = None,
        disclaimer_style: dict | None = None,
        project_name: str = "示例剧名",
        window_title: str = "编辑文字组",
    ):
        super().__init__(parent)
        self.setWindowTitle(window_title)
        self.setMinimumSize(900, 560)
        self._result_title: dict | None = None
        self._result_disclaimer: dict | None = None

        root = QHBoxLayout(self)
        root.setSpacing(12)

        preview = OverlayTextPreview(self)
        preview.set_project_name(project_name)
        preview.setMinimumWidth(360)
        root.addWidget(preview, 3)

        right = QVBoxLayout()
        orient_row = QHBoxLayout()
        portrait_radio = QRadioButton("竖屏", self)
        landscape_radio = QRadioButton("横屏", self)
        orient_group = QButtonGroup(self)
        orient_group.addButton(portrait_radio)
        orient_group.addButton(landscape_radio)
        portrait_radio.setChecked(True)
        orient_row.addWidget(portrait_radio)
        orient_row.addWidget(landscape_radio)
        orient_row.addStretch(1)
        right.addLayout(orient_row)

        state = {
            "title": dict(title_style or default_overlay_title()),
            "disclaimer": dict(disclaimer_style or default_overlay_disclaimer()),
            "orientation": "portrait",
            "syncing": False,
        }

        def _build_section(title: str, key: str) -> dict:
            box = QGroupBox(title, self)
            form = QFormLayout(box)

            text_edit = LineEdit(box)
            text_edit.setClearButtonEnabled(True)

            font_combo = QComboBox(box)
            for font_key, label, _filename in available_font_choices():
                font_combo.addItem(label, font_key)

            size_spin = QSpinBox(box)
            size_spin.setRange(OVERLAY_FONTSIZE_MIN, OVERLAY_FONTSIZE_MAX)

            color_row = QHBoxLayout()
            color_edit = LineEdit(box)
            color_btn = PushButton("选色", box)
            color_btn.setFixedWidth(56)

            def _pick_color(_checked=False, edit=color_edit):
                current = QColor(edit.text().strip() or "#FFFFFF")
                chosen = QColorDialog.getColor(current, self, "选择颜色")
                if chosen.isValid():
                    edit.setText(chosen.name().upper())

            color_btn.clicked.connect(_pick_color)
            color_row.addWidget(color_edit)
            color_row.addWidget(color_btn)

            opacity_spin = QDoubleSpinBox(box)
            opacity_spin.setRange(0.0, 1.0)
            opacity_spin.setSingleStep(0.05)
            opacity_spin.setDecimals(2)

            effect_combo = QComboBox(box)
            for effect_id, effect_label in EFFECT_CHOICES:
                effect_combo.addItem(effect_label, effect_id)

            glow_row = QHBoxLayout()
            glow_edit = LineEdit(box)
            glow_btn = PushButton("选色", box)
            glow_btn.setFixedWidth(56)

            def _pick_glow(_checked=False, edit=glow_edit):
                current = QColor(edit.text().strip() or "#00E5FF")
                chosen = QColorDialog.getColor(current, self, "选择发光颜色")
                if chosen.isValid():
                    edit.setText(chosen.name().upper())

            glow_btn.clicked.connect(_pick_glow)
            glow_row.addWidget(glow_edit)
            glow_row.addWidget(glow_btn)

            layout_row = QHBoxLayout()
            h_radio = QRadioButton("横向", box)
            v_radio = QRadioButton("竖向", box)
            layout_group = QButtonGroup(box)
            layout_group.addButton(h_radio)
            layout_group.addButton(v_radio)
            h_radio.setChecked(True)
            layout_row.addWidget(h_radio)
            layout_row.addWidget(v_radio)
            layout_row.addStretch(1)

            x_spin = QDoubleSpinBox(box)
            x_spin.setRange(0.0, 100.0)
            x_spin.setSingleStep(0.5)
            x_spin.setDecimals(1)
            x_spin.setSuffix(" %")

            y_spin = QDoubleSpinBox(box)
            y_spin.setRange(0.0, 100.0)
            y_spin.setSingleStep(0.5)
            y_spin.setDecimals(1)
            y_spin.setSuffix(" %")

            form.addRow("文案：", text_edit)
            form.addRow("排布：", layout_row)
            form.addRow("字体：", font_combo)
            form.addRow("字号：", size_spin)
            form.addRow("颜色：", color_row)
            form.addRow("透明度：", opacity_spin)
            form.addRow("特效：", effect_combo)
            form.addRow("发光色：", glow_row)
            form.addRow("位置 X：", x_spin)
            form.addRow("位置 Y：", y_spin)
            right.addWidget(box)
            return {
                "box": box,
                "text": text_edit,
                "layout_h": h_radio,
                "layout_v": v_radio,
                "font": font_combo,
                "fontsize": size_spin,
                "color": color_edit,
                "opacity": opacity_spin,
                "effect": effect_combo,
                "glow_color": glow_edit,
                "glow_btn": glow_btn,
                "x_pct": x_spin,
                "y_pct": y_spin,
                "key": key,
            }

        title_w = _build_section("剧名文字", "title")
        disc_w = _build_section("提示文字", "disclaimer")

        def _section_defaults(key: str) -> dict:
            return (
                default_overlay_title()
                if key == "title"
                else default_overlay_disclaimer()
            )

        def _fill_section(widgets: dict, style: dict):
            # 填表时屏蔽信号，避免特效变更回调把另一侧/本侧字体冲掉
            for key in ("font", "effect", "fontsize", "opacity", "x_pct", "y_pct"):
                widgets[key].blockSignals(True)
            widgets["text"].blockSignals(True)
            widgets["color"].blockSignals(True)
            widgets["glow_color"].blockSignals(True)
            widgets["layout_h"].blockSignals(True)
            widgets["layout_v"].blockSignals(True)
            try:
                view = style_for_orientation(
                    style,
                    state["orientation"],
                    defaults=_section_defaults(widgets["key"]),
                )
                widgets["text"].setText(view.get("text", ""))
                if str(view.get("layout") or "horizontal") == "vertical":
                    widgets["layout_v"].setChecked(True)
                else:
                    widgets["layout_h"].setChecked(True)
                effect = clamp_text_effect(view.get("effect"))
                eidx = widgets["effect"].findData(effect)
                widgets["effect"].setCurrentIndex(eidx if eidx >= 0 else 0)
                _sync_glow_enabled(widgets)
                idx = widgets["font"].findData(view.get("font"))
                widgets["font"].setCurrentIndex(idx if idx >= 0 else 0)
                widgets["fontsize"].setValue(int(view.get("fontsize") or 16))
                widgets["color"].setText(view.get("color") or "#FFFFFF")
                widgets["opacity"].setValue(float(view.get("opacity") or 1.0))
                widgets["glow_color"].setText(resolve_glow_color(view))
                widgets["x_pct"].setValue(float(view["x_pct"]))
                widgets["y_pct"].setValue(float(view["y_pct"]))
            finally:
                for key in ("font", "effect", "fontsize", "opacity", "x_pct", "y_pct"):
                    widgets[key].blockSignals(False)
                widgets["text"].blockSignals(False)
                widgets["color"].blockSignals(False)
                widgets["glow_color"].blockSignals(False)
                widgets["layout_h"].blockSignals(False)
                widgets["layout_v"].blockSignals(False)

        def _sync_glow_enabled(widgets: dict) -> None:
            effect = clamp_text_effect(widgets["effect"].currentData())
            enabled = effect not in {"none", "outline", "heavy_outline"}
            widgets["glow_color"].setEnabled(enabled)
            widgets["glow_btn"].setEnabled(enabled)

        def _read_shared(widgets: dict, style: dict) -> dict:
            # 文案共用；字体/特效/坐标写入当前横或竖，互不影响
            out = dict(style)
            out["text"] = widgets["text"].text()
            return update_orient_style(
                out,
                state["orientation"],
                {
                    "layout": (
                        "vertical"
                        if widgets["layout_v"].isChecked()
                        else "horizontal"
                    ),
                    "font": widgets["font"].currentData(),
                    "fontsize": widgets["fontsize"].value(),
                    "color": widgets["color"].text().strip(),
                    "opacity": widgets["opacity"].value(),
                    "effect": clamp_text_effect(widgets["effect"].currentData()),
                    "glow_color": widgets["glow_color"].text().strip(),
                    "x_pct": widgets["x_pct"].value(),
                    "y_pct": widgets["y_pct"].value(),
                },
                defaults=_section_defaults(widgets["key"]),
            )

        def _refresh_preview():
            preview.set_orientation(state["orientation"])
            preview.set_styles(state["title"], state["disclaimer"])

        def _on_param_changed(_value=None):
            if state["syncing"]:
                return
            # 各区字体/样式独立读写，互不覆盖
            state["title"] = _read_shared(title_w, state["title"])
            state["disclaimer"] = _read_shared(disc_w, state["disclaimer"])
            _refresh_preview()

        def _on_effect_changed(widgets: dict, _index: int = 0):
            if state["syncing"]:
                return
            effect = clamp_text_effect(widgets["effect"].currentData())
            _sync_glow_enabled(widgets)
            style = effect_style(effect)
            if effect != "none":
                widgets["glow_color"].setText(style["default_glow"])
            if style["suggest_fill"]:
                widgets["color"].setText(style["suggest_fill"])
            # 不自动改字体：剧名/提示各自字体由用户分开选
            _on_param_changed()

        def _wire(widgets: dict):
            widgets["text"].textChanged.connect(_on_param_changed)
            widgets["layout_h"].toggled.connect(_on_param_changed)
            widgets["layout_v"].toggled.connect(_on_param_changed)
            widgets["font"].currentIndexChanged.connect(_on_param_changed)
            widgets["fontsize"].valueChanged.connect(_on_param_changed)
            widgets["color"].textChanged.connect(_on_param_changed)
            widgets["opacity"].valueChanged.connect(_on_param_changed)
            widgets["effect"].currentIndexChanged.connect(
                lambda i, w=widgets: _on_effect_changed(w, i)
            )
            widgets["glow_color"].textChanged.connect(_on_param_changed)
            widgets["x_pct"].valueChanged.connect(_on_param_changed)
            widgets["y_pct"].valueChanged.connect(_on_param_changed)

        _wire(title_w)
        _wire(disc_w)

        def _on_orientation_toggled(_checked=False):
            if not portrait_radio.isChecked() and not landscape_radio.isChecked():
                return
            if not state["syncing"]:
                state["title"] = _read_shared(title_w, state["title"])
                state["disclaimer"] = _read_shared(disc_w, state["disclaimer"])
            state["orientation"] = (
                "landscape" if landscape_radio.isChecked() else "portrait"
            )
            state["syncing"] = True
            try:
                _fill_section(title_w, state["title"])
                _fill_section(disc_w, state["disclaimer"])
            finally:
                state["syncing"] = False
            _refresh_preview()

        portrait_radio.toggled.connect(_on_orientation_toggled)
        landscape_radio.toggled.connect(_on_orientation_toggled)

        def _on_preview_pos(which: str, x_pct: float, y_pct: float):
            key = "title" if which == "title" else "disclaimer"
            state[key] = set_position_for_orientation(
                state[key], state["orientation"], x_pct, y_pct
            )
            widgets = title_w if key == "title" else disc_w
            state["syncing"] = True
            try:
                widgets["x_pct"].setValue(x_pct)
                widgets["y_pct"].setValue(y_pct)
            finally:
                state["syncing"] = False

        def _on_preview_fontsize(which: str, fontsize: int):
            key = "title" if which == "title" else "disclaimer"
            state[key] = update_orient_style(
                state[key],
                state["orientation"],
                {"fontsize": int(fontsize)},
                defaults=_section_defaults(key),
            )
            widgets = title_w if key == "title" else disc_w
            state["syncing"] = True
            try:
                widgets["fontsize"].setValue(int(fontsize))
            finally:
                state["syncing"] = False
            _refresh_preview()

        preview.positionChanged.connect(_on_preview_pos)
        preview.fontSizeChanged.connect(_on_preview_fontsize)

        btn_row = QHBoxLayout()
        reset_btn = PushButton("重置默认", self)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        btn_row.addWidget(reset_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(buttons)
        right.addLayout(btn_row)
        right.addStretch(1)
        root.addLayout(right, 2)

        def _reset():
            state["title"] = dict(default_overlay_title())
            state["disclaimer"] = dict(default_overlay_disclaimer())
            state["syncing"] = True
            try:
                _fill_section(title_w, state["title"])
                _fill_section(disc_w, state["disclaimer"])
            finally:
                state["syncing"] = False
            _refresh_preview()

        def _accept():
            state["title"] = _read_shared(title_w, state["title"])
            state["disclaimer"] = _read_shared(disc_w, state["disclaimer"])
            self._result_title = dict(state["title"])
            self._result_disclaimer = dict(state["disclaimer"])
            self.accept()

        reset_btn.clicked.connect(_reset)
        buttons.accepted.connect(_accept)
        buttons.rejected.connect(self.reject)

        state["syncing"] = True
        try:
            _fill_section(title_w, state["title"])
            _fill_section(disc_w, state["disclaimer"])
        finally:
            state["syncing"] = False
        _refresh_preview()

    def result_styles(self) -> tuple[dict, dict]:
        return (
            dict(self._result_title or default_overlay_title()),
            dict(self._result_disclaimer or default_overlay_disclaimer()),
        )
