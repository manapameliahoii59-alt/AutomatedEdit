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
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import LineEdit, PushButton

from app.common.huazi_styles import get_huazi_style, is_huazi_effect
from app.common.overlay_text_settings import (
    OVERLAY_FONTSIZE_MAX,
    OVERLAY_FONTSIZE_MIN,
    align_for_position_preset,
    available_font_choices,
    clamp_text_effect,
    default_overlay_disclaimer,
    default_overlay_title,
    nearest_position_preset,
    set_position_for_orientation,
    style_for_orientation,
    update_orient_style,
)
from app.ui.components.overlay_effect_picker import OverlayEffectSelectRow
from app.ui.components.overlay_text_preview import OverlayTextPreview

_MODE_BASIC = 0
_MODE_HUAZI = 1


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

        def _make_pos_spins(parent: QWidget) -> tuple[QDoubleSpinBox, QDoubleSpinBox]:
            x_spin = QDoubleSpinBox(parent)
            x_spin.setRange(0.0, 100.0)
            x_spin.setSingleStep(0.5)
            x_spin.setDecimals(1)
            x_spin.setSuffix(" %")
            y_spin = QDoubleSpinBox(parent)
            y_spin.setRange(0.0, 100.0)
            y_spin.setSingleStep(0.5)
            y_spin.setDecimals(1)
            y_spin.setSuffix(" %")
            return x_spin, y_spin

        def _make_size_spin(parent: QWidget) -> QSpinBox:
            size_spin = QSpinBox(parent)
            size_spin.setRange(OVERLAY_FONTSIZE_MIN, OVERLAY_FONTSIZE_MAX)
            return size_spin

        def _build_section(title: str, key: str) -> dict:
            box = QGroupBox(title, self)
            outer = QVBoxLayout(box)

            shared_form = QFormLayout()
            text_edit = LineEdit(box)
            text_edit.setClearButtonEnabled(True)

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

            shared_form.addRow("文案：", text_edit)
            shared_form.addRow("排布：", layout_row)
            outer.addLayout(shared_form)

            tabs = QTabWidget(box)

            # —— 基础：字体/字号/透明度/颜色/位置 ——
            basic_page = QWidget(tabs)
            basic_form = QFormLayout(basic_page)

            font_combo = QComboBox(basic_page)
            for font_key, label, _filename in available_font_choices():
                font_combo.addItem(label, font_key)

            basic_size = _make_size_spin(basic_page)

            color_row = QHBoxLayout()
            color_edit = LineEdit(basic_page)
            color_btn = PushButton("选色", basic_page)
            color_btn.setFixedWidth(56)

            def _pick_color(_checked=False, edit=color_edit):
                current = QColor(edit.text().strip() or "#FFFFFF")
                chosen = QColorDialog.getColor(current, self, "选择颜色")
                if chosen.isValid():
                    edit.setText(chosen.name().upper())

            color_btn.clicked.connect(_pick_color)
            color_row.addWidget(color_edit)
            color_row.addWidget(color_btn)

            opacity_spin = QDoubleSpinBox(basic_page)
            opacity_spin.setRange(0.0, 1.0)
            opacity_spin.setSingleStep(0.05)
            opacity_spin.setDecimals(2)

            basic_x, basic_y = _make_pos_spins(basic_page)

            basic_form.addRow("字体：", font_combo)
            basic_form.addRow("字号：", basic_size)
            basic_form.addRow("颜色：", color_row)
            basic_form.addRow("透明度：", opacity_spin)
            basic_form.addRow("位置 X：", basic_x)
            basic_form.addRow("位置 Y：", basic_y)
            tabs.addTab(basic_page, "基础")

            # —— 花字：字号/位置/样式（无字体颜色发光） ——
            huazi_page = QWidget(tabs)
            huazi_form = QFormLayout(huazi_page)
            huazi_size = _make_size_spin(huazi_page)
            huazi_x, huazi_y = _make_pos_spins(huazi_page)
            effect_row = OverlayEffectSelectRow(huazi_page, huazi_only=True)
            huazi_form.addRow("花字：", effect_row)
            huazi_form.addRow("大小：", huazi_size)
            huazi_form.addRow("位置 X：", huazi_x)
            huazi_form.addRow("位置 Y：", huazi_y)
            tabs.addTab(huazi_page, "花字")

            outer.addWidget(tabs)
            right.addWidget(box)
            return {
                "box": box,
                "tabs": tabs,
                "text": text_edit,
                "layout_h": h_radio,
                "layout_v": v_radio,
                "font": font_combo,
                "fontsize": basic_size,
                "color": color_edit,
                "opacity": opacity_spin,
                "x_pct": basic_x,
                "y_pct": basic_y,
                "huazi_fontsize": huazi_size,
                "huazi_x_pct": huazi_x,
                "huazi_y_pct": huazi_y,
                "effect": effect_row,
                "key": key,
                "last_huazi": "none",
            }

        title_w = _build_section("剧名文字", "title")
        disc_w = _build_section("提示文字", "disclaimer")

        def _section_defaults(key: str) -> dict:
            return (
                default_overlay_title()
                if key == "title"
                else default_overlay_disclaimer()
            )

        def _is_huazi_mode(widgets: dict) -> bool:
            return widgets["tabs"].currentIndex() == _MODE_HUAZI

        def _apply_huazi_defaults(widgets: dict, effect_id: str) -> None:
            """花字样式自带字体/填色提示，UI 不暴露但静默写入。"""
            hz = get_huazi_style(effect_id)
            if hz is None:
                return
            prefers = hz.get("prefer_fonts") or ()
            if prefers:
                idx = widgets["font"].findData(prefers[0])
                if idx >= 0:
                    widgets["font"].blockSignals(True)
                    widgets["font"].setCurrentIndex(idx)
                    widgets["font"].blockSignals(False)
            preview_color = str(hz.get("preview_color") or "").strip()
            if preview_color:
                widgets["color"].blockSignals(True)
                widgets["color"].setText(preview_color.upper())
                widgets["color"].blockSignals(False)

        def _fill_section(widgets: dict, style: dict):
            widgets["tabs"].blockSignals(True)
            for key in (
                "font",
                "fontsize",
                "opacity",
                "x_pct",
                "y_pct",
                "huazi_fontsize",
                "huazi_x_pct",
                "huazi_y_pct",
            ):
                widgets[key].blockSignals(True)
            widgets["effect"].blockSignals(True)
            widgets["text"].blockSignals(True)
            widgets["color"].blockSignals(True)
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
                if is_huazi_effect(effect):
                    widgets["last_huazi"] = effect
                    widgets["tabs"].setCurrentIndex(_MODE_HUAZI)
                    widgets["effect"].set_effect(effect)
                else:
                    # 旧辉光特效在本弹框不再可选，回基础纯字
                    widgets["tabs"].setCurrentIndex(_MODE_BASIC)
                    widgets["effect"].set_effect("none")

                idx = widgets["font"].findData(view.get("font"))
                widgets["font"].setCurrentIndex(idx if idx >= 0 else 0)
                size = int(view.get("fontsize") or 16)
                widgets["fontsize"].setValue(size)
                widgets["huazi_fontsize"].setValue(size)
                widgets["color"].setText(view.get("color") or "#FFFFFF")
                widgets["opacity"].setValue(float(view.get("opacity") or 1.0))
                x_pct = float(view["x_pct"])
                y_pct = float(view["y_pct"])
                widgets["x_pct"].setValue(x_pct)
                widgets["y_pct"].setValue(y_pct)
                widgets["huazi_x_pct"].setValue(x_pct)
                widgets["huazi_y_pct"].setValue(y_pct)
            finally:
                widgets["tabs"].blockSignals(False)
                for key in (
                    "font",
                    "fontsize",
                    "opacity",
                    "x_pct",
                    "y_pct",
                    "huazi_fontsize",
                    "huazi_x_pct",
                    "huazi_y_pct",
                ):
                    widgets[key].blockSignals(False)
                widgets["effect"].blockSignals(False)
                widgets["text"].blockSignals(False)
                widgets["color"].blockSignals(False)
                widgets["layout_h"].blockSignals(False)
                widgets["layout_v"].blockSignals(False)

        def _read_shared(widgets: dict, style: dict) -> dict:
            out = dict(style)
            out["text"] = widgets["text"].text()
            layout = (
                "vertical" if widgets["layout_v"].isChecked() else "horizontal"
            )
            if _is_huazi_mode(widgets):
                effect = clamp_text_effect(widgets["effect"].current_effect())
                if is_huazi_effect(effect):
                    widgets["last_huazi"] = effect
                patch = {
                    "layout": layout,
                    "fontsize": widgets["huazi_fontsize"].value(),
                    "x_pct": widgets["huazi_x_pct"].value(),
                    "y_pct": widgets["huazi_y_pct"].value(),
                    "effect": effect if is_huazi_effect(effect) else "none",
                    # 字体/颜色沿用控件上静默值；透明度花字页不调，保留原值
                    "font": widgets["font"].currentData(),
                    "color": widgets["color"].text().strip(),
                }
            else:
                patch = {
                    "layout": layout,
                    "font": widgets["font"].currentData(),
                    "fontsize": widgets["fontsize"].value(),
                    "color": widgets["color"].text().strip(),
                    "opacity": widgets["opacity"].value(),
                    "effect": "none",
                    "x_pct": widgets["x_pct"].value(),
                    "y_pct": widgets["y_pct"].value(),
                }
            preset = nearest_position_preset(
                float(patch["x_pct"]), float(patch["y_pct"])
            )
            h_a, v_a = align_for_position_preset(preset)
            patch["h_align"] = h_a
            patch["v_align"] = v_a
            return update_orient_style(
                out,
                state["orientation"],
                patch,
                defaults=_section_defaults(widgets["key"]),
            )

        def _refresh_preview():
            preview.set_orientation(state["orientation"])
            preview.set_styles(state["title"], state["disclaimer"])

        def _on_param_changed(_value=None):
            if state["syncing"]:
                return
            state["title"] = _read_shared(title_w, state["title"])
            state["disclaimer"] = _read_shared(disc_w, state["disclaimer"])
            _refresh_preview()

        def _sync_pos_spins(
            widgets: dict, *, from_huazi: bool
        ) -> None:
            """两页位置/字号互相同步，避免切 Tab 数值跳变。"""
            if from_huazi:
                size = widgets["huazi_fontsize"].value()
                x = widgets["huazi_x_pct"].value()
                y = widgets["huazi_y_pct"].value()
                for key, val in (
                    ("fontsize", size),
                    ("x_pct", x),
                    ("y_pct", y),
                ):
                    widgets[key].blockSignals(True)
                    widgets[key].setValue(val)
                    widgets[key].blockSignals(False)
            else:
                size = widgets["fontsize"].value()
                x = widgets["x_pct"].value()
                y = widgets["y_pct"].value()
                for key, val in (
                    ("huazi_fontsize", size),
                    ("huazi_x_pct", x),
                    ("huazi_y_pct", y),
                ):
                    widgets[key].blockSignals(True)
                    widgets[key].setValue(val)
                    widgets[key].blockSignals(False)

        def _on_mode_changed(widgets: dict, index: int):
            if state["syncing"]:
                return
            state["syncing"] = True
            try:
                if index == _MODE_BASIC:
                    # 记下当前花字，切回纯字
                    cur = clamp_text_effect(widgets["effect"].current_effect())
                    if is_huazi_effect(cur):
                        widgets["last_huazi"] = cur
                    widgets["effect"].set_effect("none")
                    _sync_pos_spins(widgets, from_huazi=True)
                else:
                    _sync_pos_spins(widgets, from_huazi=False)
                    last = widgets.get("last_huazi") or "none"
                    if is_huazi_effect(last):
                        widgets["effect"].set_effect(last)
                        _apply_huazi_defaults(widgets, last)
                    else:
                        widgets["effect"].set_effect("none")
            finally:
                state["syncing"] = False
            _on_param_changed()

        def _on_effect_changed(widgets: dict, effect_id: str = ""):
            if state["syncing"]:
                return
            effect = clamp_text_effect(effect_id or widgets["effect"].current_effect())
            if is_huazi_effect(effect):
                widgets["last_huazi"] = effect
                _apply_huazi_defaults(widgets, effect)
            _on_param_changed()

        def _wire(widgets: dict):
            widgets["text"].textChanged.connect(_on_param_changed)
            widgets["layout_h"].toggled.connect(_on_param_changed)
            widgets["layout_v"].toggled.connect(_on_param_changed)
            widgets["font"].currentIndexChanged.connect(_on_param_changed)
            widgets["fontsize"].valueChanged.connect(_on_param_changed)
            widgets["color"].textChanged.connect(_on_param_changed)
            widgets["opacity"].valueChanged.connect(_on_param_changed)
            widgets["x_pct"].valueChanged.connect(_on_param_changed)
            widgets["y_pct"].valueChanged.connect(_on_param_changed)
            widgets["huazi_fontsize"].valueChanged.connect(_on_param_changed)
            widgets["huazi_x_pct"].valueChanged.connect(_on_param_changed)
            widgets["huazi_y_pct"].valueChanged.connect(_on_param_changed)
            widgets["effect"].effectChanged.connect(
                lambda eid, w=widgets: _on_effect_changed(w, eid)
            )
            widgets["tabs"].currentChanged.connect(
                lambda idx, w=widgets: _on_mode_changed(w, idx)
            )

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

        def _active_pos_widgets(widgets: dict):
            if _is_huazi_mode(widgets):
                return widgets["huazi_x_pct"], widgets["huazi_y_pct"]
            return widgets["x_pct"], widgets["y_pct"]

        def _active_size_widget(widgets: dict):
            if _is_huazi_mode(widgets):
                return widgets["huazi_fontsize"]
            return widgets["fontsize"]

        def _on_preview_pos(
            which: str, x_pct: float, y_pct: float, h_align: str, v_align: str
        ):
            key = "title" if which == "title" else "disclaimer"
            state[key] = set_position_for_orientation(
                state[key],
                state["orientation"],
                x_pct,
                y_pct,
                h_align=h_align,
                v_align=v_align,
            )
            widgets = title_w if key == "title" else disc_w
            state["syncing"] = True
            try:
                x_w, y_w = _active_pos_widgets(widgets)
                x_w.setValue(x_pct)
                y_w.setValue(y_pct)
                # 同步另一页
                widgets["x_pct"].setValue(x_pct)
                widgets["y_pct"].setValue(y_pct)
                widgets["huazi_x_pct"].setValue(x_pct)
                widgets["huazi_y_pct"].setValue(y_pct)
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
                size = int(fontsize)
                _active_size_widget(widgets).setValue(size)
                widgets["fontsize"].setValue(size)
                widgets["huazi_fontsize"].setValue(size)
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
            title_w["last_huazi"] = "none"
            disc_w["last_huazi"] = "none"
            state["syncing"] = True
            try:
                _fill_section(title_w, state["title"])
                _fill_section(disc_w, state["disclaimer"])
            finally:
                state["syncing"] = False
            state["title"] = _read_shared(title_w, state["title"])
            state["disclaimer"] = _read_shared(disc_w, state["disclaimer"])
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
        # 旧辉光等非花字特效在本弹框回落为基础纯字，写回 state 再预览
        state["title"] = _read_shared(title_w, state["title"])
        state["disclaimer"] = _read_shared(disc_w, state["disclaimer"])
        _refresh_preview()

    def result_styles(self) -> tuple[dict, dict]:
        return (
            dict(self._result_title or default_overlay_title()),
            dict(self._result_disclaimer or default_overlay_disclaimer()),
        )
