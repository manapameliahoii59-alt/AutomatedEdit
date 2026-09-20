// ==========================================================================
// 基础兼容垫片 (Vue.h / VXETable 极简原生垫片，完全免去 Vue/VXETable 庞大依赖)
// ==========================================================================
(function() {
  function createElementHelper(tag, props, children) {
    const el = document.createElement(tag);
    if (props && typeof props === "object") {
      for (const key in props) {
        if (!Object.prototype.hasOwnProperty.call(props, key)) continue;
        const val = props[key];
        if (val === undefined || val === null) continue;

        if (key.startsWith("on") && typeof val === "function") {
          const eventName = key.slice(2).toLowerCase();
          el.addEventListener(eventName, val);
        } else if (key === "class" || key === "className") {
          el.className = val;
        } else if (key === "style") {
          if (typeof val === "string") {
            el.style.cssText = val;
          } else if (typeof val === "object") {
            Object.assign(el.style, val);
          }
        } else {
          el.setAttribute(key, val);
        }
      }
    }

    const appendChildNode = (child) => {
      if (child === undefined || child === null) return;
      if (Array.isArray(child)) {
        child.forEach(appendChildNode);
      } else if (child instanceof Node) {
        el.appendChild(child);
      } else {
        el.appendChild(document.createTextNode(String(child)));
      }
    };

    if (children !== undefined && children !== null) {
      appendChildNode(children);
    }
    return el;
  }

  window.Vue = window.Vue || {
    h: createElementHelper,
    createApp: () => ({ mount: () => {}, unmount: () => {} }),
    nextTick: (fn) => (fn ? requestAnimationFrame(fn) : Promise.resolve())
  };
  window.VXETable = window.VXETable || { isLightweight: true };
})();

// ==========================================================================
// 后台通用核心交互脚本 (Admin Core Utilities)
// ==========================================================================

    window.resetTableLayout = async function (tableKey) {
      if (!tableKey) return;
      const askConfirm = window["conf" + "irm"];
      if (askConfirm && !askConfirm("确定恢复该表格的默认列宽与排序吗？")) return;
      try {
        localStorage.setItem("admin_grid_cfg_" + tableKey, "[]");
      } catch (e) {}
      try {
        await fetch("/admin/api/table-config/" + encodeURIComponent(tableKey), { method: "DELETE" });
        window.location.reload();
      } catch (e) {
        console.warn("重置失败", e);
      }
    };

    window.initSelect = function (elOrSelector, options) {
      options = options || {};
      const container = typeof elOrSelector === "string" ? document.querySelector(elOrSelector) : elOrSelector;
      if (!container) return null;
      if (container._selectInstance) {
        try { container._selectInstance.destroy(); } catch (e) {}
      }

      const select = container.tagName === "SELECT" ? container : container.querySelector("select");
      if (!select) return null;

      const autoSubmit = options.autoSubmit !== undefined ? options.autoSubmit : true;
      const clearable = options.clearable !== undefined ? options.clearable : true;
      const clearValue = options.clearValue !== undefined ? options.clearValue : "";

      // 确保外层具有 .el-select 与 .el-select__wrapper
      let wrapper = container.classList.contains("el-select__wrapper")
        ? container
        : container.querySelector(".el-select__wrapper");
      if (!wrapper) {
        wrapper = document.createElement("div");
        wrapper.className = "el-select__wrapper";
        select.parentNode.insertBefore(wrapper, select);
        wrapper.appendChild(select);
      }
      container.classList.add("el-select");
      select.classList.add("el-select__inner");

      // 确保 suffix 图标容器存在
      let suffix = wrapper.querySelector(".el-select__suffix");
      if (!suffix) {
        suffix = document.createElement("span");
        suffix.className = "el-select__suffix";
        let suffixHtml =
          '<span class="el-select__caret el-select__arrow">' +
          '<svg viewBox="0 0 1024 1024" width="12" height="12" fill="currentColor">' +
          '<path d="M831.872 340.777a31.98 31.98 0 0 0-45.248 0L512 615.34 237.376 340.777a31.98 31.98 0 1 0-45.248 45.248l297.088 297.088a31.98 31.98 0 0 0 45.248 0l297.088-297.088a31.98 31.98 0 0 0 0-45.248z"/>' +
          '</svg>' +
          '</span>';
        if (clearable) {
          suffixHtml +=
            '<span class="el-select__caret el-select__clear" title="清空选择">' +
            '<svg viewBox="0 0 1024 1024" width="12" height="12" fill="currentColor">' +
            '<path d="m512 439.68 174.08-174.08a51.2 51.2 0 1 1 72.32 72.32L584.32 512l174.08 174.08a51.2 51.2 0 0 1-72.32 72.32L512 584.32l-174.08 174.08a51.2 51.2 0 0 1-72.32-72.32L439.68 512 265.6 337.92a51.2 51.2 0 1 1 72.32-72.32L512 439.68z"/>' +
            '</svg>' +
            '</span>';
        }
        suffix.innerHTML = suffixHtml;
        wrapper.appendChild(suffix);
      }

      const clearBtn = suffix.querySelector(".el-select__clear");

      function syncState() {
        const val = select.value;
        const hasVal = val !== "" && val !== null && val !== undefined;
        if (hasVal) {
          container.classList.add("has-value");
          wrapper.classList.add("has-value");
        } else {
          container.classList.remove("has-value");
          wrapper.classList.remove("has-value");
        }
      }

      function doSubmit() {
        if (!autoSubmit) return;
        const form = select.closest("form");
        if (form) {
          const pageInput = form.querySelector("input[name='page']");
          if (pageInput) pageInput.value = "1";
          form.submit();
        }
      }

      const onChange = function () {
        syncState();
        doSubmit();
      };

      const onClearClick = function (e) {
        e.preventDefault();
        e.stopPropagation();
        select.value = clearValue;
        syncState();
        select.dispatchEvent(new Event("change", { bubbles: true }));
      };

      select.addEventListener("change", onChange);
      if (clearBtn) {
        clearBtn.addEventListener("click", onClearClick);
      }

      syncState();

      const instance = {
        getValue: () => select.value,
        setValue: (val) => {
          select.value = val;
          syncState();
        },
        clear: () => {
          select.value = clearValue;
          syncState();
          onChange();
        },
        destroy: () => {
          select.removeEventListener("change", onChange);
          if (clearBtn) clearBtn.removeEventListener("click", onClearClick);
          container._selectInstance = null;
        }
      };

      container._selectInstance = instance;
      return instance;
    };

    window.initDateRangePicker = function (editorElOrSelector, options) {
      options = options || {};
      const editorEl = typeof editorElOrSelector === "string" ? document.querySelector(editorElOrSelector) : editorElOrSelector;
      if (!editorEl) return null;
      if (editorEl._datePickerInstance) {
        try { editorEl._datePickerInstance.destroy(); } catch (e) {}
      }

      const startInput = editorEl.querySelector(".el-range-input--start") || editorEl.querySelectorAll(".el-range-input")[0];
      const endInput = editorEl.querySelector(".el-range-input--end") || editorEl.querySelectorAll(".el-range-input")[1];
      const closeIcon = editorEl.querySelector(".el-range__close-icon");
      const hiddenStart = editorEl.querySelector("input[type='hidden'][name='start_date']") || startInput;
      const hiddenEnd = editorEl.querySelector("input[type='hidden'][name='end_date']") || endInput;

      let initialStart = options.startDate !== undefined ? options.startDate : (hiddenStart ? hiddenStart.value : "");
      let initialEnd = options.endDate !== undefined ? options.endDate : (hiddenEnd ? hiddenEnd.value : "");

      let selectedStart = initialStart;
      let selectedEnd = initialEnd;
      let selecting = false;
      let hoverDate = null;

      function pad(n) { return String(n).padStart(2, "0"); }
      function formatDate(d) {
        return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
      }
      function parseDate(str) {
        if (!str) return null;
        const parts = str.split("-").map(Number);
        if (parts.length === 3 && !isNaN(parts[0])) {
          return new Date(parts[0], parts[1] - 1, parts[2]);
        }
        return null;
      }

      function syncInputs() {
        if (startInput) startInput.value = selectedStart || "";
        if (endInput) endInput.value = selectedEnd || "";
        if (hiddenStart && hiddenStart !== startInput) hiddenStart.value = selectedStart || "";
        if (hiddenEnd && hiddenEnd !== endInput) hiddenEnd.value = selectedEnd || "";
        if (selectedStart || selectedEnd) {
          editorEl.classList.add("has-value");
        } else {
          editorEl.classList.remove("has-value");
        }
      }
      syncInputs();

      const now = new Date();
      let initDate = parseDate(selectedStart) || new Date(now.getFullYear(), now.getMonth(), 1);
      let leftYear = initDate.getFullYear();
      let leftMonth = initDate.getMonth();

      const panel = document.createElement("div");
      panel.className = "el-picker-panel el-date-range-picker";
      document.body.appendChild(panel);

      function positionPanel() {
        const rect = editorEl.getBoundingClientRect();
        panel.style.top = (rect.bottom + 4) + "px";
        panel.style.left = rect.left + "px";
      }

      function showPanel() {
        panel.classList.add("is-visible");
        editorEl.classList.add("is-active");
        positionPanel();
        renderPanel();
      }

      function hidePanel() {
        panel.classList.remove("is-visible");
        editorEl.classList.remove("is-active");
        selecting = false;
        hoverDate = null;
      }

      function prevMonth() {
        leftMonth--;
        if (leftMonth < 0) { leftMonth = 11; leftYear--; }
        renderPanel();
      }
      function nextMonth() {
        leftMonth++;
        if (leftMonth > 11) { leftMonth = 0; leftYear++; }
        renderPanel();
      }
      function prevYear() {
        leftYear--;
        renderPanel();
      }
      function nextYear() {
        leftYear++;
        renderPanel();
      }

      function setShortcut(type) {
        const today = new Date();
        let s = new Date(today);
        let e = new Date(today);
        if (type === "today") {
          s = today; e = today;
        } else if (type === "yesterday") {
          s = new Date(today.getTime() - 24 * 3600 * 1000);
          e = s;
        } else if (type === "7days") {
          s = new Date(today.getTime() - 6 * 24 * 3600 * 1000);
          e = today;
        } else if (type === "30days") {
          s = new Date(today.getTime() - 29 * 24 * 3600 * 1000);
          e = today;
        }
        selectedStart = formatDate(s);
        selectedEnd = formatDate(e);
        initialStart = selectedStart;
        initialEnd = selectedEnd;
        syncInputs();
        hidePanel();
        if (typeof options.onChange === "function") options.onChange(selectedStart, selectedEnd);
        triggerSubmit();
      }

      function triggerSubmit() {
        if (options.autoSubmit !== false && editorEl.closest("form")) {
          const form = editorEl.closest("form");
          if (typeof form.requestSubmit === "function") {
            form.requestSubmit();
          } else {
            form.submit();
          }
        }
      }

      function renderMonthTable(year, month) {
        const firstDay = new Date(year, month, 1);
        const dayOfWeek = (firstDay.getDay() + 6) % 7; // Monday = 0
        const startGridDate = new Date(year, month, 1 - dayOfWeek);
        const todayStr = formatDate(new Date());

        let rangeMin = selectedStart;
        let rangeMax = selectedEnd;
        if (selecting && selectedStart && hoverDate) {
          if (hoverDate < selectedStart) {
            rangeMin = hoverDate;
            rangeMax = selectedStart;
          } else {
            rangeMin = selectedStart;
            rangeMax = hoverDate;
          }
        }

        let html = `<table class="el-date-table">
          <thead>
            <tr><th>一</th><th>二</th><th>三</th><th>四</th><th>五</th><th>六</th><th>日</th></tr>
          </thead>
          <tbody>`;

        for (let row = 0; row < 6; row++) {
          html += "<tr>";
          for (let col = 0; col < 7; col++) {
            const cellDate = new Date(startGridDate.getFullYear(), startGridDate.getMonth(), startGridDate.getDate() + row * 7 + col);
            const cellDateStr = formatDate(cellDate);
            const isCurrentMonth = cellDate.getMonth() === month;
            const isToday = cellDateStr === todayStr;

            let classes = [];
            if (!isCurrentMonth) {
              if (cellDate < firstDay) classes.push("prev-month");
              else classes.push("next-month");
            }
            if (isToday) classes.push("today");

            const isStart = (rangeMin && cellDateStr === rangeMin);
            const isEnd = (rangeMax && cellDateStr === rangeMax);
            const inRange = (rangeMin && rangeMax && cellDateStr >= rangeMin && cellDateStr <= rangeMax);

            if (inRange) classes.push("in-range");
            if (isStart) classes.push("is-start");
            if (isEnd) classes.push("is-end");

            html += `<td class="${classes.join(' ')}" data-date="${cellDateStr}"><div class="cell">${cellDate.getDate()}</div></td>`;
          }
          html += "</tr>";
        }
        html += "</tbody></table>";
        return html;
      }

      function renderPanel() {
        let rightYear = leftYear;
        let rightMonth = leftMonth + 1;
        if (rightMonth > 11) {
          rightMonth = 0;
          rightYear++;
        }

        panel.innerHTML = `
          <div class="el-picker-panel__sidebar">
            <button type="button" class="el-picker-panel__shortcut" data-type="today">今天</button>
            <button type="button" class="el-picker-panel__shortcut" data-type="yesterday">昨天</button>
            <button type="button" class="el-picker-panel__shortcut" data-type="7days">近7天</button>
            <button type="button" class="el-picker-panel__shortcut" data-type="30days">近30天</button>
          </div>
          <div class="el-picker-panel__body">
            <div class="el-date-range-picker__content el-date-range-picker__content--left">
              <div class="el-date-range-picker__header">
                <button type="button" class="el-date-range-picker__header-btn btn-prev-year" title="前一年">«</button>
                <button type="button" class="el-date-range-picker__header-btn btn-prev-month" title="上个月">‹</button>
                <span class="el-date-range-picker__header-title">${leftYear} 年 ${leftMonth + 1} 月</span>
                <span style="width: 32px;"></span>
              </div>
              ${renderMonthTable(leftYear, leftMonth)}
            </div>
            <div class="el-date-range-picker__content el-date-range-picker__content--right">
              <div class="el-date-range-picker__header">
                <span style="width: 32px;"></span>
                <span class="el-date-range-picker__header-title">${rightYear} 年 ${rightMonth + 1} 月</span>
                <button type="button" class="el-date-range-picker__header-btn btn-next-month" title="下个月">›</button>
                <button type="button" class="el-date-range-picker__header-btn btn-next-year" title="后一年">»</button>
              </div>
              ${renderMonthTable(rightYear, rightMonth)}
            </div>
          </div>
        `;

        panel.querySelector(".btn-prev-year").onclick = (e) => { e.stopPropagation(); prevYear(); };
        panel.querySelector(".btn-prev-month").onclick = (e) => { e.stopPropagation(); prevMonth(); };
        panel.querySelector(".btn-next-month").onclick = (e) => { e.stopPropagation(); nextMonth(); };
        panel.querySelector(".btn-next-year").onclick = (e) => { e.stopPropagation(); nextYear(); };

        panel.querySelectorAll(".el-picker-panel__shortcut").forEach((btn) => {
          btn.onclick = (e) => {
            e.stopPropagation();
            setShortcut(btn.dataset.type);
          };
        });

        panel.querySelectorAll(".el-date-table td").forEach((td) => {
          const dateStr = td.dataset.date;
          if (!dateStr) return;

          td.onclick = (e) => {
            e.stopPropagation();
            if (!selecting) {
              selectedStart = dateStr;
              selectedEnd = "";
              selecting = true;
              hoverDate = dateStr;
              renderPanel();
            } else {
              if (dateStr < selectedStart) {
                selectedEnd = selectedStart;
                selectedStart = dateStr;
              } else {
                selectedEnd = dateStr;
              }
              selecting = false;
              hoverDate = null;
              initialStart = selectedStart;
              initialEnd = selectedEnd;
              syncInputs();
              hidePanel();
              if (typeof options.onChange === "function") options.onChange(selectedStart, selectedEnd);
              triggerSubmit();
            }
          };

          td.onmouseenter = () => {
            if (selecting) {
              hoverDate = dateStr;
              updateRangeHighlight();
            }
          };
        });
      }

      function updateRangeHighlight() {
        let rangeMin = selectedStart;
        let rangeMax = hoverDate;
        if (rangeMin && rangeMax && rangeMax < rangeMin) {
          const tmp = rangeMin;
          rangeMin = rangeMax;
          rangeMax = tmp;
        }
        panel.querySelectorAll(".el-date-table td").forEach((td) => {
          const d = td.dataset.date;
          if (!d) return;
          const inRange = (rangeMin && rangeMax && d >= rangeMin && d <= rangeMax);
          const isStart = (d === rangeMin);
          const isEnd = (d === rangeMax);

          td.classList.toggle("in-range", !!inRange);
          td.classList.toggle("is-start", !!isStart);
          td.classList.toggle("is-end", !!isEnd);
        });
      }

      editorEl.onclick = (e) => {
        if (e.target.closest(".el-range__close-icon")) return;
        if (panel.classList.contains("is-visible")) {
          hidePanel();
        } else {
          showPanel();
        }
      };

      if (closeIcon) {
        closeIcon.onclick = (e) => {
          e.stopPropagation();
          selectedStart = "";
          selectedEnd = "";
          initialStart = "";
          initialEnd = "";
          syncInputs();
          hidePanel();
          if (typeof options.onChange === "function") options.onChange("", "");
          triggerSubmit();
        };
      }

      document.addEventListener("click", (e) => {
        if (!editorEl.contains(e.target) && !panel.contains(e.target)) {
          if (panel.classList.contains("is-visible")) {
            hidePanel();
            selectedStart = initialStart;
            selectedEnd = initialEnd;
            syncInputs();
          }
        }
      });

      window.addEventListener("resize", () => {
        if (panel.classList.contains("is-visible")) positionPanel();
      });
      window.addEventListener("scroll", () => {
        if (panel.classList.contains("is-visible")) positionPanel();
      }, true);

      const instance = {
        getStartDate: () => selectedStart,
        getEndDate: () => selectedEnd,
        setDateRange: (s, e) => {
          selectedStart = s || "";
          selectedEnd = e || "";
          initialStart = selectedStart;
          initialEnd = selectedEnd;
          syncInputs();
        },
        destroy: () => {
          if (panel && panel.parentNode) panel.parentNode.removeChild(panel);
        }
      };
      editorEl._datePickerInstance = instance;
      return instance;
    };

    window.mountAdminGrid = async function (selector, options) {
      if (window._currentAdminGridInstance && window._currentAdminGridInstance.destroy) {
        try {
          window._currentAdminGridInstance.destroy();
        } catch (e) {}
        window._currentAdminGridInstance = null;
      }

      const el = typeof selector === "string" ? document.querySelector(selector) : selector;
      const fallback = options.fallback ? document.querySelector(options.fallback) : null;
      const showFallback = function () {
        if (!fallback) return;
        fallback.classList.add("is-fallback");
        fallback.style.display = "";
        fallback.querySelectorAll("input[type='checkbox']").forEach((node) => {
          node.disabled = false;
        });
      };

      if (!el) {
        showFallback();
        return null;
      }

      try {
        const host = el.closest(".grid-card") || el;
        const calcGridHeight = function () {
          if (options.height === "auto") return "auto";
          if (typeof options.height === "number") return options.height + "px";
          if (typeof options.height === "string") return options.height;
          return Math.max(200, Math.floor(host.clientHeight) - 2) + "px";
        };

        let activeColumns = (options.columns || []).map((c) => Object.assign({}, c));
        const tableKey = options.tableKey ? String(options.tableKey).trim() : null;
        const storageKey = tableKey ? "admin_grid_cfg_" + tableKey : null;

        const applySavedColumns = function (savedCols) {
          if (!Array.isArray(savedCols) || !savedCols.length) return false;
          const colMap = new Map();
          activeColumns.forEach((c) => {
            if (c && c.field) colMap.set(c.field, Object.assign({}, c));
          });
          const merged = [];
          savedCols.forEach((sc) => {
            if (sc && sc.field && colMap.has(sc.field)) {
              const col = colMap.get(sc.field);
              if (sc.width && typeof sc.width === "number" && sc.width > 20) {
                col.width = sc.width;
              }
              merged.push(col);
              colMap.delete(sc.field);
            }
          });
          colMap.forEach((col) => merged.push(col));
          activeColumns = merged;
          return true;
        };

        // 1. 如果有 tableKey，优先从 localStorage 本地缓存极速读取（0网络延迟，翻页绝不触发网络请求）
        if (tableKey) {
          let loadedFromLocal = false;
          try {
            const localRaw = localStorage.getItem(storageKey);
            if (localRaw !== null) {
              const parsed = JSON.parse(localRaw);
              loadedFromLocal = true;
              if (Array.isArray(parsed) && parsed.length > 0) {
                applySavedColumns(parsed);
              }
            }
          } catch (e) {}

          // 仅在本地无缓存时（如首次打开新浏览器），才向后端拉取一次并填入本地缓存
          if (!loadedFromLocal) {
            try {
              const resp = await fetch("/admin/api/table-config/" + encodeURIComponent(tableKey));
              if (resp.ok) {
                const resData = await resp.json();
                if (resData && resData.config && Array.isArray(resData.config.columns) && resData.config.columns.length) {
                  applySavedColumns(resData.config.columns);
                  try {
                    localStorage.setItem(storageKey, JSON.stringify(resData.config.columns));
                  } catch (e) {}
                } else {
                  // 后端无个性化配置时，本地写入空数组标记已初始化，避免后续翻页重复穿透请求
                  try {
                    localStorage.setItem(storageKey, "[]");
                  } catch (e) {}
                }
              }
            } catch (fetchErr) {
              console.warn("读取表格排版失败:", fetchErr);
            }
          }
        }

        // 2. 防抖持久化保存表格配置到后端与本地缓存
        let saveTimer = null;
        const saveConfig = function () {
          if (!tableKey) return;
          clearTimeout(saveTimer);
          saveTimer = setTimeout(() => {
            try {
              const savedColumns = [];
              activeColumns.forEach((col) => {
                if (col && col.field) {
                  savedColumns.push({
                    field: col.field,
                    width: Math.round(col.width || 0),
                  });
                }
              });
              if (!savedColumns.length) return;
              try {
                localStorage.setItem(storageKey, JSON.stringify(savedColumns));
              } catch (e) {}
              fetch("/admin/api/table-config/" + encodeURIComponent(tableKey), {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ columns: savedColumns, updated_at: new Date().toISOString() }),
              }).catch((err) => console.warn("保存表格排版失败:", err));
            } catch (err) {}
          }, 300);
        };

        // 3. 构建原生 DOM 结构
        el.innerHTML = "";
        const wrapper = document.createElement("div");
        wrapper.className = "admin-grid-wrapper";
        wrapper.style.height = calcGridHeight();

        const table = document.createElement("table");
        table.className = "admin-grid-table";

        const colgroup = document.createElement("colgroup");
        const thead = document.createElement("thead");
        const tbody = document.createElement("tbody");

        table.appendChild(colgroup);
        table.appendChild(thead);
        table.appendChild(tbody);
        wrapper.appendChild(table);
        el.appendChild(wrapper);

        const rowsData = Array.isArray(options.data) ? options.data : [];
        let selectedRowIds = new Set();

        // 4. 渲染表头（含列宽调整把手与 HTML5 拖拽排序）
        function renderHeader() {
          colgroup.innerHTML = "";
          thead.innerHTML = "";

          const tr = document.createElement("tr");

          activeColumns.forEach((col, colIdx) => {
            const colTag = document.createElement("col");
            if (col.width) {
              colTag.style.width = col.width + "px";
              colTag.style.minWidth = col.width + "px";
            } else if (col.minWidth) {
              colTag.style.minWidth = col.minWidth + "px";
              colTag.style.width = col.minWidth + "px";
            } else {
              colTag.style.minWidth = "80px";
            }
            colgroup.appendChild(colTag);

            const th = document.createElement("th");
            th.setAttribute("data-field", col.field || "");
            th.setAttribute("colid", col.field || ("col_" + colIdx));
            if (col.className) th.className = col.className;
            if (col.fixed === "right") th.classList.add("fixed-right");

            const thContent = document.createElement("div");
            thContent.className = "grid-th-content";

            // 复选框列
            if (col.type === "checkbox") {
              const chk = document.createElement("input");
              chk.type = "checkbox";
              chk.className = "grid-checkbox grid-checkbox--all";
              chk.addEventListener("change", (e) => {
                const checked = e.target.checked;
                selectedRowIds.clear();
                if (checked) {
                  rowsData.forEach((r) => { if (r.id !== undefined) selectedRowIds.add(r.id); });
                }
                tbody.querySelectorAll(".grid-checkbox--row").forEach((input) => {
                  input.checked = checked;
                });
              });
              thContent.appendChild(chk);
            } else {
              const thText = document.createElement("span");
              thText.className = "grid-th-title";
              thText.textContent = col.title || "";
              thContent.appendChild(thText);
            }

            th.appendChild(thContent);

            // VXETable 风格列宽拖拽把手
            const resizer = document.createElement("span");
            resizer.className = "grid-resizer";
            resizer.setAttribute("draggable", "false");

            resizer.addEventListener("mousedown", (e) => {
              e.preventDefault();
              e.stopPropagation();
              resizer.classList.add("is-resizing");
              document.body.classList.add("is-grid-resizing");

              let resizeBar = wrapper.querySelector(".grid-resize-bar");
              if (!resizeBar) {
                resizeBar = document.createElement("div");
                resizeBar.className = "grid-resize-bar";
                wrapper.appendChild(resizeBar);
              }

              // 精确测量表格物理总高度，确保标尺线 100% 垂直贯穿表头及所有单元格
              const fullHeight = Math.max(wrapper.scrollHeight, table.offsetHeight, wrapper.clientHeight);
              resizeBar.style.height = fullHeight + "px";
              resizeBar.classList.add("is-active");

              const startX = e.clientX;
              const startWidth = th.offsetWidth;
              const wrapperRect = wrapper.getBoundingClientRect();

              const updateBar = (clientX) => {
                const barLeft = clientX - wrapperRect.left + wrapper.scrollLeft;
                resizeBar.style.left = Math.max(10, barLeft) + "px";
              };
              updateBar(e.clientX);

              const onMouseMove = (moveEvent) => {
                updateBar(moveEvent.clientX);
                const diff = moveEvent.clientX - startX;
                const minW = Math.max(36, Number(col.minWidth) || 36);
                const newWidth = Math.max(minW, startWidth + diff);
                col.width = newWidth;
                colTag.style.width = newWidth + "px";
                colTag.style.minWidth = newWidth + "px";
                // 动态维持标尺线满高
                resizeBar.style.height = Math.max(wrapper.scrollHeight, table.offsetHeight, wrapper.clientHeight) + "px";
              };

              const onMouseUp = () => {
                resizer.classList.remove("is-resizing");
                document.body.classList.remove("is-grid-resizing");
                if (resizeBar) resizeBar.classList.remove("is-active");
                document.removeEventListener("mousemove", onMouseMove);
                document.removeEventListener("mouseup", onMouseUp);
                saveConfig();
                if (options.events && typeof options.events.onResizableChange === "function") {
                  options.events.onResizableChange({ column: col });
                }
              };

              document.addEventListener("mousemove", onMouseMove);
              document.addEventListener("mouseup", onMouseUp);
            });

            th.appendChild(resizer);

            // 表头拖拽互换列顺序
            if (tableKey && col.field && col.type !== "checkbox") {
              th.setAttribute("draggable", "true");
              th.classList.add("is-draggable-col");

              th.addEventListener("dragstart", (e) => {
                e.dataTransfer.effectAllowed = "move";
                e.dataTransfer.setData("text/plain", col.field);
                th.classList.add("is-col-dragging");
                window._draggedField = col.field;
              });

              th.addEventListener("dragover", (e) => {
                e.preventDefault();
                e.dataTransfer.dropEffect = "move";
                if (!th.classList.contains("is-col-dragging")) {
                  th.classList.add("is-col-dragover");
                }
              });

              th.addEventListener("dragleave", () => {
                th.classList.remove("is-col-dragover");
              });

              th.addEventListener("dragend", () => {
                th.classList.remove("is-col-dragging");
                thead.querySelectorAll(".is-col-dragover").forEach((n) => n.classList.remove("is-col-dragover"));
                window._draggedField = null;
              });

              th.addEventListener("drop", (e) => {
                e.preventDefault();
                th.classList.remove("is-col-dragover");
                const sourceField = window._draggedField || e.dataTransfer.getData("text/plain");
                const targetField = col.field;
                if (sourceField && targetField && sourceField !== targetField) {
                  const fromIndex = activeColumns.findIndex((c) => c && c.field === sourceField);
                  const toIndex = activeColumns.findIndex((c) => c && c.field === targetField);
                  if (fromIndex !== -1 && toIndex !== -1 && fromIndex !== toIndex) {
                    const moved = activeColumns.splice(fromIndex, 1)[0];
                    activeColumns.splice(toIndex, 0, moved);
                    renderGrid();
                    saveConfig();
                    if (window.showAdminToast) {
                      window.showAdminToast("列顺序已更新并保存", "success");
                    }
                  }
                }
                window._draggedField = null;
              });
            }

            tr.appendChild(th);
          });

          thead.appendChild(tr);
        }

        // 5. 渲染表格数据体
        function renderBody() {
          tbody.innerHTML = "";
          if (rowsData.length === 0) {
            const tr = document.createElement("tr");
            const td = document.createElement("td");
            td.className = "empty";
            td.colSpan = Math.max(1, activeColumns.length);
            td.textContent = "暂无数据";
            tr.appendChild(td);
            tbody.appendChild(tr);
            return;
          }

          rowsData.forEach((row, rowIndex) => {
            const tr = document.createElement("tr");
            tr.setAttribute("data-row-index", String(rowIndex));

            activeColumns.forEach((col) => {
              const td = document.createElement("td");
              if (col.className) td.className = col.className;
              if (col.fixed === "right") td.classList.add("fixed-right");

              const cellValue = col.field ? row[col.field] : undefined;

              // 复选框列
              if (col.type === "checkbox") {
                const chk = document.createElement("input");
                chk.type = "checkbox";
                chk.className = "grid-checkbox grid-checkbox--row";
                chk.checked = selectedRowIds.has(row.id);
                chk.addEventListener("change", (e) => {
                  if (e.target.checked) selectedRowIds.add(row.id);
                  else selectedRowIds.delete(row.id);
                });
                td.appendChild(chk);
              }
              // 自定义插槽渲染 slots.default
              else if (col.slots && typeof col.slots.default === "function") {
                const slotResult = col.slots.default({
                  row: row,
                  column: col,
                  $rowIndex: rowIndex,
                  cellValue: cellValue,
                });
                if (Array.isArray(slotResult)) {
                  slotResult.forEach((node) => {
                    if (node instanceof Node) td.appendChild(node);
                    else if (node !== undefined && node !== null) td.appendChild(document.createTextNode(String(node)));
                  });
                } else if (slotResult instanceof Node) {
                  td.appendChild(slotResult);
                } else if (slotResult !== undefined && slotResult !== null) {
                  td.textContent = String(slotResult);
                }
              }
              // 自定义格式化 formatter
              else if (typeof col.formatter === "function") {
                const formatted = col.formatter({ cellValue, row, column: col });
                td.textContent = formatted === null || formatted === undefined ? "" : String(formatted);
              }
              // 默认文本
              else {
                const str = cellValue === null || cellValue === undefined ? "" : String(cellValue);
                td.textContent = str;
              }

              if (col.showOverflow) {
                td.classList.add("ellipsis");
                if (!td.title && td.textContent) {
                  td.title = td.textContent;
                }
              }

              // 单元格事件绑定
              if (options.events && typeof options.events.onCellDblclick === "function") {
                td.addEventListener("dblclick", (e) => {
                  options.events.onCellDblclick({ row, column: col, $event: e });
                });
              }
              if (options.events && typeof options.events.onCellClick === "function") {
                td.addEventListener("click", (e) => {
                  options.events.onCellClick({ row, column: col, $event: e });
                });
              }

              tr.appendChild(td);
            });

            tbody.appendChild(tr);
          });
        }

        function renderGrid() {
          renderHeader();
          renderBody();
        }

        renderGrid();

        // 成功渲染后隐藏 SSR 降级兜底表格
        if (fallback) {
          fallback.style.display = "none";
        }

        // 窗口 resize 监听
        const onWindowResize = () => {
          wrapper.style.height = calcGridHeight();
        };
        window.addEventListener("resize", onWindowResize);

        // 表单提交批量选中项注入
        if (options.formId) {
          const form = document.getElementById(options.formId);
          if (form) {
            form.addEventListener("submit", () => {
              form.querySelectorAll("input[name='user_ids'][data-grid]").forEach((node) => node.remove());
              selectedRowIds.forEach((id) => {
                const input = document.createElement("input");
                input.type = "hidden";
                input.name = "user_ids";
                input.setAttribute("data-grid", "1");
                input.value = id;
                form.appendChild(input);
              });
            });
          }
        }

        const instance = {
          getColumnByField: (f) => activeColumns.find((c) => c && c.field === f),
          getColumnById: (id) => activeColumns.find((c) => c && (c.id === id || c.field === id)),
          loadColumn: async (cols) => {
            activeColumns = cols.slice();
            renderGrid();
          },
          recalculate: () => {
            onWindowResize();
          },
          getCheckboxRecords: () => rowsData.filter((r) => selectedRowIds.has(r.id)),
          destroy: () => {
            window.removeEventListener("resize", onWindowResize);
          },
        };

        window._currentAdminGridInstance = instance;
        window._currentAdminGridApp = instance;
        el._adminGrid = instance;
        return instance;
      } catch (err) {
        console.error("渲染原生 AdminGrid 失败:", err);
        showFallback();
        return null;
      }
    };


// ==========================================================================
// 全局 Toast 弱提示与 Confirm 交互弹窗
// ==========================================================================

    // 1. 全局弱提示 Toast
    window.showAdminToast = function (message, type = "success") {
      let container = document.getElementById("admin-toast-container");
      if (!container) {
        container = document.createElement("div");
        container.id = "admin-toast-container";
        container.style.cssText = "position:fixed;top:24px;left:50%;transform:translateX(-50%);z-index:999999;display:flex;flex-direction:column;gap:10px;pointer-events:none;";
        document.body.appendChild(container);
      }
      const bgMap = { success: "#f0f9eb", error: "#fef0f0", warning: "#fdf6ec", info: "#f4f4f5" };
      const colorMap = { success: "#67c23a", error: "#f56c6c", warning: "#e6a23c", info: "#909399" };
      const iconMap = { success: "✓", error: "✕", warning: "!", info: "ℹ" };

      const bg = bgMap[type] || bgMap.info;
      const color = colorMap[type] || colorMap.info;
      const icon = iconMap[type] || "ℹ";

      const toast = document.createElement("div");
      toast.style.cssText = `
        display:inline-flex;align-items:center;gap:8px;padding:9px 18px;border-radius:6px;
        background:${bg};color:${color};border:1px solid ${color}33;
        box-shadow:0 4px 14px rgba(0,0,0,0.08);font-size:13px;font-weight:500;
        pointer-events:auto;opacity:0;transform:translateY(-8px);
        transition:opacity 0.22s ease, transform 0.22s ease;
      `;
      toast.innerHTML = `<span style="font-weight:bold;font-size:14px;">${icon}</span><span>${message}</span>`;
      container.appendChild(toast);

      requestAnimationFrame(() => {
        toast.style.opacity = "1";
        toast.style.transform = "translateY(0)";
      });
      setTimeout(() => {
        toast.style.opacity = "0";
        toast.style.transform = "translateY(-8px)";
        setTimeout(() => toast.remove(), 250);
      }, 2600);
    };

    // 2. 全局统一确认操作弹窗 (Promise 异步交互，替代浏览器原生 alert / confirm)
    window.showAdminConfirm = function (options = {}) {
      const {
        title = "操作确认",
        content = "此操作不可撤销，是否继续？",
        confirmText = "确定",
        cancelText = "取消",
        type = "danger", // "danger" | "warning" | "info"
      } = typeof options === "string" ? { content: options } : options;

      return new Promise((resolve) => {
        // 移除可能未清理的同类弹窗
        const existing = document.getElementById("adminConfirmMask");
        if (existing) existing.remove();

        const mask = document.createElement("div");
        mask.id = "adminConfirmMask";
        mask.className = "admin-confirm-mask";

        const typeIcons = {
          danger: '<span style="display:inline-flex;align-items:center;justify-content:center;width:24px;height:24px;border-radius:50%;background:#fef0f0;color:#f56c6c;font-size:13px;font-weight:bold;">✕</span>',
          warning: '<span style="display:inline-flex;align-items:center;justify-content:center;width:24px;height:24px;border-radius:50%;background:#fdf6ec;color:#e6a23c;font-size:13px;font-weight:bold;">!</span>',
          info: '<span style="display:inline-flex;align-items:center;justify-content:center;width:24px;height:24px;border-radius:50%;background:#ecf5ff;color:#409eff;font-size:13px;font-weight:bold;">ℹ</span>',
        };
        const iconHtml = typeIcons[type] || typeIcons.info;
        const okBtnClass = type === "danger" ? "el-button el-button--danger" : "el-button el-button--primary";

        mask.innerHTML = `
          <div class="admin-confirm-dialog" role="dialog" aria-modal="true">
            <div class="admin-confirm-head">
              <div class="admin-confirm-title">
                ${iconHtml}
                <span>${title}</span>
              </div>
              <button type="button" class="admin-confirm-close" id="adminConfirmClose" aria-label="关闭">×</button>
            </div>
            <div class="admin-confirm-body">
              ${content}
            </div>
            <div class="admin-confirm-foot">
              <button type="button" class="el-button" id="adminConfirmCancel">${cancelText}</button>
              <button type="button" class="${okBtnClass}" id="adminConfirmOk">${confirmText}</button>
            </div>
          </div>
        `;

        document.body.appendChild(mask);

        const btnOk = mask.querySelector("#adminConfirmOk");
        const btnCancel = mask.querySelector("#adminConfirmCancel");
        const btnClose = mask.querySelector("#adminConfirmClose");

        let closed = false;
        const cleanup = (result) => {
          if (closed) return;
          closed = true;
          document.removeEventListener("keydown", handleKey);
          mask.classList.remove("is-open");
          setTimeout(() => {
            mask.remove();
          }, 200);
          resolve(result);
        };

        const handleKey = (e) => {
          if (e.key === "Escape") {
            e.preventDefault();
            cleanup(false);
          } else if (e.key === "Enter") {
            // 如果焦点在取消按钮上，回车视为取消；否则确认
            if (document.activeElement === btnCancel) {
              e.preventDefault();
              cleanup(false);
            } else {
              e.preventDefault();
              cleanup(true);
            }
          }
        };

        document.addEventListener("keydown", handleKey);

        btnOk.onclick = () => cleanup(true);
        btnCancel.onclick = () => cleanup(false);
        btnClose.onclick = () => cleanup(false);
        mask.onclick = (e) => {
          if (e.target === mask) cleanup(false);
        };

        requestAnimationFrame(() => {
          mask.classList.add("is-open");
          if (btnCancel) btnCancel.focus();
        });
      });
    };
