"""画面文字编辑弹框：左预览 + 右剧名/提示参数（供文字组新增/编辑复用）。"""

from __future__ import annotations

from PySide6.QtGui import QColor
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QRadioButton,
    QScrollArea,
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
    available_font_choices,
    clamp_h_align,
    clamp_text_effect,
    default_overlay_disclaimer,
    default_overlay_disclaimer2,
    default_overlay_title,
    position_for_orientation,
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
        disclaimer2_style: dict | None = None,
        project_name: str = "示例剧名",
        window_title: str = "编辑文字组",
    ):
        super().__init__(parent)
        self.setWindowTitle(window_title)
        self.setMinimumSize(900, 560)
        self._result_title: dict | None = None
        self._result_disclaimer: dict | None = None
        self._result_disclaimer2: dict | None = None

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
            "disclaimer2": dict(
                disclaimer2_style or default_overlay_disclaimer2()
            ),
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

        def _make_center_row(
            parent: QWidget, spin: QWidget
        ) -> tuple[QWidget, QCheckBox]:
            """位置行：数值旋钮 + 「居中」开关；开启后旋钮禁用并居中排布。"""
            host = QWidget(parent)
            lay = QHBoxLayout(host)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(4)
            check = QCheckBox("居中", host)
            lay.addWidget(spin, 1)
            lay.addWidget(check)
            return host, check

        def _build_section(
            title: str, key: str, *, enable_color_spans: bool = False
        ) -> dict:
            box = QGroupBox(title, self)
            outer = QVBoxLayout(box)

            shared_form = QFormLayout()
            text_edit = LineEdit(box)
            text_edit.setClearButtonEnabled(True)

            shared_form.addRow("文案：", text_edit)

            # 局部变色规则：[{text, color}]，仅提示位启用
            color_spans_rows: list[dict] = []
            spans_add = None
            spans_clear = None
            if enable_color_spans:
                spans_scroll_cap = 3 * 44 + 8

                def _fit_button(btn: PushButton, label: str) -> None:
                    btn.setText(label)
                    btn.setFixedWidth(
                        btn.fontMetrics().horizontalAdvance(label) + 26
                    )

                spans_field = QWidget(box)
                spans_field_layout = QVBoxLayout(spans_field)
                spans_field_layout.setContentsMargins(0, 0, 0, 0)
                spans_field_layout.setSpacing(4)

                # 变色行列表放进滚动区：行数多时滚动查看，避免上下压缩行高
                scroll = QScrollArea(spans_field)
                scroll.setWidgetResizable(True)
                scroll.setFrameShape(QFrame.Shape.NoFrame)
                scroll.setHorizontalScrollBarPolicy(
                    Qt.ScrollBarPolicy.ScrollBarAlwaysOff
                )
                scroll.setVerticalScrollBarPolicy(
                    Qt.ScrollBarPolicy.ScrollBarAsNeeded
                )

                spans_host = QWidget()
                spans_layout = QVBoxLayout(spans_host)
                spans_layout.setContentsMargins(0, 0, 0, 0)
                spans_layout.setSpacing(4)
                scroll.setWidget(spans_host)

                def _sync_scroll_height() -> None:
                    def _apply():
                        if not color_spans_rows:
                            scroll.hide()
                            return
                        scroll.show()
                        needed = spans_host.sizeHint().height()
                        scroll.setFixedHeight(
                            max(1, min(needed, spans_scroll_cap))
                        )

                    QTimer.singleShot(0, _apply)

                _sync_scroll_height()

                def _add_span_row(text_val: str = "", color_val: str = "#FFFF00"):
                    if len(color_spans_rows) >= 8:
                        return
                    row = QWidget(spans_host)
                    h = QHBoxLayout(row)
                    h.setContentsMargins(0, 0, 0, 0)
                    h.setSpacing(4)
                    span_edit = LineEdit(row)
                    span_edit.setPlaceholderText("要变色的文字")
                    span_edit.setText(text_val)
                    color_btn = PushButton(row)
                    _fit_button(color_btn, "选色")
                    del_btn = PushButton(row)
                    _fit_button(del_btn, "删")
                    entry = {"text": span_edit, "row": row, "color": color_val}

                    def _pick(_checked=False):
                        cur = QColor(str(entry["color"] or "#FFFF00"))
                        chosen = QColorDialog.getColor(cur, self, "选择变色颜色")
                        if chosen.isValid():
                            entry["color"] = chosen.name().upper()
                            _on_param_changed()

                    def _remove():
                        if entry in color_spans_rows:
                            color_spans_rows.remove(entry)
                        spans_layout.removeWidget(row)
                        row.deleteLater()
                        _on_param_changed()
                        _sync_scroll_height()

                    def _on_span_text_changed(_t):
                        # 变色文字会按顺序拼接在文案末尾并染色，无需回填文案
                        _on_param_changed()

                    color_btn.clicked.connect(_pick)
                    del_btn.clicked.connect(_remove)
                    span_edit.textChanged.connect(_on_span_text_changed)
                    h.addWidget(span_edit, 1)
                    h.addWidget(color_btn)
                    h.addWidget(del_btn)
                    spans_layout.addWidget(row)
                    color_spans_rows.append(entry)
                    _sync_scroll_height()

                def _clear_span_rows():
                    for entry in list(color_spans_rows):
                        spans_layout.removeWidget(entry["row"])
                        entry["row"].deleteLater()
                    color_spans_rows.clear()
                    _sync_scroll_height()

                def _on_add_span_clicked():
                    _add_span_row()

                add_span_btn = PushButton("+ 添加变色文字", spans_field)
                add_span_btn.setToolTip(
                    "输入的文字会整体染色，并**追加到文案末尾**（按添加顺序）。\n"
                    "例：文案「内容纯属虚构」，点选色把「请勿带入现实」设为黄色，\n"
                    "渲染为「内容纯属虚构请勿带入现实」，后半段为黄色。\n"
                    "花字样式自带配色，变色不生效。"
                )
                add_span_btn.clicked.connect(_on_add_span_clicked)
                spans_field_layout.addWidget(add_span_btn)
                spans_field_layout.addWidget(scroll)
                shared_form.addRow("变色文字：", spans_field)
                spans_add = _add_span_row
                spans_clear = _clear_span_rows

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
            shared_form.addRow("排布：", layout_row)

            font_combo = QComboBox(box)
            for font_key, label, _filename in available_font_choices():
                font_combo.addItem(label, font_key)
            shared_form.addRow("字体：", font_combo)
            outer.addLayout(shared_form)

            tabs = QTabWidget(box)

            # —— 基础：字号/透明度/颜色/位置 ——
            basic_page = QWidget(tabs)
            basic_form = QFormLayout(basic_page)

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
            basic_x_host, basic_x_center = _make_center_row(basic_page, basic_x)
            basic_y_host, basic_y_center = _make_center_row(basic_page, basic_y)

            basic_form.addRow("字号：", basic_size)
            basic_form.addRow("颜色：", color_row)
            basic_form.addRow("透明度：", opacity_spin)
            basic_form.addRow("位置 X：", basic_x_host)
            basic_form.addRow("位置 Y：", basic_y_host)
            tabs.addTab(basic_page, "基础")

            # —— 花字：字号/位置/样式（无字体颜色发光） ——
            huazi_page = QWidget(tabs)
            huazi_form = QFormLayout(huazi_page)
            huazi_size = _make_size_spin(huazi_page)
            huazi_x, huazi_y = _make_pos_spins(huazi_page)
            huazi_x_host, huazi_x_center = _make_center_row(huazi_page, huazi_x)
            huazi_y_host, huazi_y_center = _make_center_row(huazi_page, huazi_y)
            effect_row = OverlayEffectSelectRow(huazi_page, huazi_only=True)
            huazi_form.addRow("花字：", effect_row)
            huazi_form.addRow("大小：", huazi_size)
            huazi_form.addRow("位置 X：", huazi_x_host)
            huazi_form.addRow("位置 Y：", huazi_y_host)
            tabs.addTab(huazi_page, "花字")

            outer.addWidget(tabs)
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
                "x_center": basic_x_center,
                "y_center": basic_y_center,
                "huazi_fontsize": huazi_size,
                "huazi_x_pct": huazi_x,
                "huazi_y_pct": huazi_y,
                "huazi_x_center": huazi_x_center,
                "huazi_y_center": huazi_y_center,
                "effect": effect_row,
                "key": key,
                "last_huazi": "none",
                "huazi_font": None,
                "spans_enabled": enable_color_spans,
                "spans_rows": color_spans_rows,
                "spans_add": spans_add,
                "spans_clear": spans_clear,
            }

        title_w = _build_section("剧名文字", "title")
        disc_w = _build_section("提示文字", "disclaimer", enable_color_spans=True)
        disc2_w = _build_section(
            "提示文字2", "disclaimer2", enable_color_spans=True
        )
        # 三个文本位用页签承载：任一页参数修改都会实时刷新预览
        section_tabs = QTabWidget(self)
        section_tabs.addTab(title_w["box"], "剧名")
        section_tabs.addTab(disc_w["box"], "提示文字")
        section_tabs.addTab(disc2_w["box"], "提示文字2")
        right.addWidget(section_tabs, 1)

        _sections = {"title": title_w, "disclaimer": disc_w, "disclaimer2": disc2_w}

        def _section_defaults(key: str) -> dict:
            if key == "title":
                return default_overlay_title()
            if key == "disclaimer2":
                return default_overlay_disclaimer2()
            return default_overlay_disclaimer()

        def _is_huazi_mode(widgets: dict) -> bool:
            return widgets["tabs"].currentIndex() == _MODE_HUAZI

        def _apply_huazi_defaults(widgets: dict, effect_id: str) -> None:
            """花字样式自带字体/填色提示，UI 不暴露但静默写入。"""
            hz = get_huazi_style(effect_id)
            if hz is None:
                widgets["huazi_font"] = None
                return
            prefers = hz.get("prefer_fonts") or ()
            if prefers:
                font_key = str(prefers[0])
                widgets["huazi_font"] = font_key
                idx = widgets["font"].findData(font_key)
                if idx >= 0:
                    widgets["font"].blockSignals(True)
                    widgets["font"].setCurrentIndex(idx)
                    widgets["font"].blockSignals(False)
            else:
                widgets["huazi_font"] = None
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
                "x_center",
                "y_center",
                "huazi_x_center",
                "huazi_y_center",
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
                    hz = get_huazi_style(effect)
                    prefers = (hz or {}).get("prefer_fonts") or ()
                    widgets["huazi_font"] = (
                        str(prefers[0]) if prefers else view.get("font")
                    )
                else:
                    # 旧辉光特效在本弹框不再可选，回基础纯字
                    widgets["tabs"].setCurrentIndex(_MODE_BASIC)
                    widgets["effect"].set_effect("none")
                    widgets["huazi_font"] = None

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
                # 居中开关与当前横/竖锚点一致；开启时对应百分比旋钮禁用
                x_center = (view.get("h_align") or "") == "c"
                y_center = (view.get("v_align") or "") == "c"
                widgets["x_center"].setChecked(x_center)
                widgets["y_center"].setChecked(y_center)
                widgets["huazi_x_center"].setChecked(x_center)
                widgets["huazi_y_center"].setChecked(y_center)
                widgets["x_pct"].setEnabled(not x_center)
                widgets["y_pct"].setEnabled(not y_center)
                widgets["huazi_x_pct"].setEnabled(not x_center)
                widgets["huazi_y_pct"].setEnabled(not y_center)
                if widgets.get("spans_enabled"):
                    widgets["spans_clear"]()
                    for sp in style.get("color_spans") or []:
                        widgets["spans_add"](
                            str(sp.get("text") or ""),
                            str(sp.get("color") or "#FFFF00"),
                        )
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
                    "x_center",
                    "y_center",
                    "huazi_x_center",
                    "huazi_y_center",
                ):
                    widgets[key].blockSignals(False)
                widgets["effect"].blockSignals(False)
                widgets["text"].blockSignals(False)
                widgets["color"].blockSignals(False)
                widgets["layout_h"].blockSignals(False)
                widgets["layout_v"].blockSignals(False)

        def _read_shared(
            widgets: dict, style: dict, *, free_pos: bool = False
        ) -> dict:
            out = dict(style)
            out["text"] = widgets["text"].text()
            if widgets.get("spans_enabled"):
                out["color_spans"] = [
                    {
                        "text": r["text"].text().strip(),
                        "color": str(r["color"] or "").strip() or "#FFFF00",
                    }
                    for r in widgets.get("spans_rows", [])
                    if r["text"].text().strip()
                ]
            layout = (
                "vertical" if widgets["layout_v"].isChecked() else "horizontal"
            )
            if _is_huazi_mode(widgets):
                effect = clamp_text_effect(widgets["effect"].current_effect())
                if is_huazi_effect(effect):
                    widgets["last_huazi"] = effect
                # 字体花字：优先用样式绑定字体（可能不在「字体」下拉里）
                hz = get_huazi_style(effect) if is_huazi_effect(effect) else None
                prefers = (hz or {}).get("prefer_fonts") or ()
                font_key = (
                    widgets.get("huazi_font")
                    or (prefers[0] if prefers else None)
                    or widgets["font"].currentData()
                )
                patch = {
                    "layout": layout,
                    "fontsize": widgets["huazi_fontsize"].value(),
                    "x_pct": widgets["huazi_x_pct"].value(),
                    "y_pct": widgets["huazi_y_pct"].value(),
                    "effect": effect if is_huazi_effect(effect) else "none",
                    "font": font_key,
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
            # 位置锚点：X/Y 各自的「居中」开关决定；居中时对应百分比禁用
            if _is_huazi_mode(widgets):
                x_center = widgets["huazi_x_center"].isChecked()
                y_center = widgets["huazi_y_center"].isChecked()
            else:
                x_center = widgets["x_center"].isChecked()
                y_center = widgets["y_center"].isChecked()
            patch["h_align"] = "c" if x_center else "l"
            patch["v_align"] = "c" if y_center else "t"
            return update_orient_style(
                out,
                state["orientation"],
                patch,
                defaults=_section_defaults(widgets["key"]),
            )

        def _refresh_preview():
            preview.set_orientation(state["orientation"])
            preview.set_styles(
                state["title"], state["disclaimer"], state["disclaimer2"]
            )

        def _on_param_changed(_value=None):
            if state["syncing"]:
                return
            state["title"] = _read_shared(title_w, state["title"])
            state["disclaimer"] = _read_shared(disc_w, state["disclaimer"])
            state["disclaimer2"] = _read_shared(disc2_w, state["disclaimer2"])
            _refresh_preview()

        def _sync_from_ui():
            """从各页控件重新读取当前值，保证预览状态与右侧表单一致。"""
            if state["syncing"]:
                return
            state["title"] = _read_shared(title_w, state["title"])
            state["disclaimer"] = _read_shared(disc_w, state["disclaimer"])
            state["disclaimer2"] = _read_shared(disc2_w, state["disclaimer2"])
            _refresh_preview()

        def _on_pos_spin_changed(widgets: dict, _value=None):
            """位置旋钮视为自由定位，清除该组的九宫格几何对齐。"""
            if state["syncing"]:
                return
            key = widgets["key"]
            state[key] = _read_shared(widgets, state[key], free_pos=True)
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

            def _apply_centers():
                # 以当前页(基础/花字)的开关为准，两页始终保持一致
                if _is_huazi_mode(widgets):
                    x_center = widgets["huazi_x_center"].isChecked()
                    y_center = widgets["huazi_y_center"].isChecked()
                else:
                    x_center = widgets["x_center"].isChecked()
                    y_center = widgets["y_center"].isChecked()
                for chk, on in (
                    (widgets["x_center"], x_center),
                    (widgets["huazi_x_center"], x_center),
                    (widgets["y_center"], y_center),
                    (widgets["huazi_y_center"], y_center),
                ):
                    chk.blockSignals(True)
                    chk.setChecked(on)
                    chk.blockSignals(False)
                widgets["x_pct"].setEnabled(not x_center)
                widgets["huazi_x_pct"].setEnabled(not x_center)
                widgets["y_pct"].setEnabled(not y_center)
                widgets["huazi_y_pct"].setEnabled(not y_center)
                _on_param_changed()

            for key in (
                "x_center",
                "y_center",
                "huazi_x_center",
                "huazi_y_center",
            ):
                widgets[key].toggled.connect(lambda _c: _apply_centers())

            widgets["x_pct"].valueChanged.connect(
                lambda _v, w=widgets: _on_pos_spin_changed(w)
            )
            widgets["y_pct"].valueChanged.connect(
                lambda _v, w=widgets: _on_pos_spin_changed(w)
            )
            widgets["huazi_fontsize"].valueChanged.connect(_on_param_changed)
            widgets["huazi_x_pct"].valueChanged.connect(
                lambda _v, w=widgets: _on_pos_spin_changed(w)
            )
            widgets["huazi_y_pct"].valueChanged.connect(
                lambda _v, w=widgets: _on_pos_spin_changed(w)
            )
            widgets["effect"].effectChanged.connect(
                lambda eid, w=widgets: _on_effect_changed(w, eid)
            )
            widgets["tabs"].currentChanged.connect(
                lambda idx, w=widgets: _on_mode_changed(w, idx)
            )

        _wire(title_w)
        _wire(disc_w)
        _wire(disc2_w)

        def _on_orientation_toggled(_checked=False):
            if not portrait_radio.isChecked() and not landscape_radio.isChecked():
                return
            if not state["syncing"]:
                state["title"] = _read_shared(title_w, state["title"])
                state["disclaimer"] = _read_shared(disc_w, state["disclaimer"])
                state["disclaimer2"] = _read_shared(disc2_w, state["disclaimer2"])
            state["orientation"] = (
                "landscape" if landscape_radio.isChecked() else "portrait"
            )
            state["syncing"] = True
            try:
                _fill_section(title_w, state["title"])
                _fill_section(disc_w, state["disclaimer"])
                _fill_section(disc2_w, state["disclaimer2"])
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
            key = which if which in ("disclaimer", "disclaimer2") else "title"
            state[key] = set_position_for_orientation(  # type: ignore[index]
                state[key],
                state["orientation"],
                x_pct,
                y_pct,
                h_align=h_align,
                v_align=v_align,
            )
            widgets = _sections[key]
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
                # 预览拖拽/跳格产生的锚点同步到「居中」开关
                x_center = h_align == "c"
                y_center = v_align == "c"
                for chk, on in (
                    (widgets["x_center"], x_center),
                    (widgets["huazi_x_center"], x_center),
                    (widgets["y_center"], y_center),
                    (widgets["huazi_y_center"], y_center),
                ):
                    chk.blockSignals(True)
                    chk.setChecked(on)
                    chk.blockSignals(False)
                widgets["x_pct"].setEnabled(not x_center)
                widgets["y_pct"].setEnabled(not y_center)
                widgets["huazi_x_pct"].setEnabled(not x_center)
                widgets["huazi_y_pct"].setEnabled(not y_center)
            finally:
                state["syncing"] = False

        def _on_preview_fontsize(which: str, fontsize: int):
            key = which if which in ("disclaimer", "disclaimer2") else "title"
            state[key] = update_orient_style(  # type: ignore[index]
                state[key],
                state["orientation"],
                {"fontsize": int(fontsize)},
                defaults=_section_defaults(key),
            )
            widgets = _sections[key]
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

        # 预览选中 ↔ 编辑页签 双向联动
        def _on_preview_item_selected(which: str):
            # 切换前按右侧控件当前值重新渲染，避免预览沿用旧的样式快照
            _sync_from_ui()
            idx = {"title": 0, "disclaimer": 1, "disclaimer2": 2}.get(which)
            if idx is not None and section_tabs.currentIndex() != idx:
                section_tabs.setCurrentIndex(idx)

        def _on_section_tab_changed(idx: int):
            _sync_from_ui()
            keys = ("title", "disclaimer", "disclaimer2")
            which = keys[idx] if 0 <= idx < len(keys) else "title"
            if preview.selected() != which:
                preview.set_selected(which)

        preview.itemSelected.connect(_on_preview_item_selected)
        section_tabs.currentChanged.connect(_on_section_tab_changed)

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
            state["disclaimer2"] = dict(default_overlay_disclaimer2())
            title_w["last_huazi"] = "none"
            disc_w["last_huazi"] = "none"
            disc2_w["last_huazi"] = "none"
            state["syncing"] = True
            try:
                _fill_section(title_w, state["title"])
                _fill_section(disc_w, state["disclaimer"])
                _fill_section(disc2_w, state["disclaimer2"])
            finally:
                state["syncing"] = False
            state["title"] = _read_shared(title_w, state["title"])
            state["disclaimer"] = _read_shared(disc_w, state["disclaimer"])
            state["disclaimer2"] = _read_shared(disc2_w, state["disclaimer2"])
            _refresh_preview()

        def _accept():
            state["title"] = _read_shared(title_w, state["title"])
            state["disclaimer"] = _read_shared(disc_w, state["disclaimer"])
            state["disclaimer2"] = _read_shared(disc2_w, state["disclaimer2"])
            self._result_title = dict(state["title"])
            self._result_disclaimer = dict(state["disclaimer"])
            self._result_disclaimer2 = dict(state["disclaimer2"])
            self.accept()

        reset_btn.clicked.connect(_reset)
        buttons.accepted.connect(_accept)
        buttons.rejected.connect(self.reject)

        state["syncing"] = True
        try:
            _fill_section(title_w, state["title"])
            _fill_section(disc_w, state["disclaimer"])
            _fill_section(disc2_w, state["disclaimer2"])
        finally:
            state["syncing"] = False
        # 旧辉光等非花字特效在本弹框回落为基础纯字，写回 state 再预览
        state["title"] = _read_shared(title_w, state["title"])
        state["disclaimer"] = _read_shared(disc_w, state["disclaimer"])
        state["disclaimer2"] = _read_shared(disc2_w, state["disclaimer2"])
        _refresh_preview()

    def result_styles(self) -> tuple[dict, dict, dict]:
        return (
            dict(self._result_title or default_overlay_title()),
            dict(self._result_disclaimer or default_overlay_disclaimer()),
            dict(self._result_disclaimer2 or default_overlay_disclaimer2()),
        )
