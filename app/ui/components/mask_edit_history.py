from __future__ import annotations

from copy import deepcopy

from app.data.models.mask_region import MaskRegion


class MaskEditHistory:
    """打码区域编辑的撤销/重做栈。"""

    def __init__(self):
        self._undo: list[list[MaskRegion]] = []
        self._redo: list[list[MaskRegion]] = []
        self._current: list[MaskRegion] = []

    def reset(self, regions: list[MaskRegion] | None = None):
        self._undo.clear()
        self._redo.clear()
        self._current = deepcopy(regions or [])

    def current(self) -> list[MaskRegion]:
        return deepcopy(self._current)

    def can_undo(self) -> bool:
        return bool(self._undo)

    def can_redo(self) -> bool:
        return bool(self._redo)

    def set_current(self, regions: list[MaskRegion], *, record_undo: bool = True):
        if record_undo:
            self._undo.append(deepcopy(self._current))
            self._redo.clear()
        self._current = deepcopy(regions)

    def undo(self) -> list[MaskRegion] | None:
        if not self._undo:
            return None
        self._redo.append(deepcopy(self._current))
        self._current = self._undo.pop()
        return deepcopy(self._current)

    def redo(self) -> list[MaskRegion] | None:
        if not self._redo:
            return None
        self._undo.append(deepcopy(self._current))
        self._current = self._redo.pop()
        return deepcopy(self._current)
