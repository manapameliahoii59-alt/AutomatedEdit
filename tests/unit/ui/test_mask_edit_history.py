from app.data.models.mask_region import MaskRegion
from app.ui.components.mask_edit_history import MaskEditHistory


def _region(label: str) -> MaskRegion:
    return MaskRegion(
        nx=0.1,
        ny=0.1,
        nw=0.2,
        nh=0.2,
        start_ms=0,
        end_ms=1000,
        label=label,
    )


class TestMaskEditHistory:
    def test_undo_redo(self):
        history = MaskEditHistory()
        history.set_current([_region("A")], record_undo=False)
        history.set_current([_region("A"), _region("B")])
        assert len(history.current()) == 2

        undone = history.undo()
        assert undone is not None
        assert len(undone) == 1
        assert undone[0].label == "A"

        redone = history.redo()
        assert redone is not None
        assert len(redone) == 2

    def test_can_undo_redo_flags(self):
        history = MaskEditHistory()
        assert not history.can_undo()
        history.set_current([_region("A")])
        assert history.can_undo()
        assert not history.can_redo()


class TestMaskRegion:
    def test_clamped(self):
        region = MaskRegion(
            nx=-0.1,
            ny=0.9,
            nw=0.5,
            nh=0.5,
            start_ms=0,
            end_ms=1000,
        )
        clamped = region.clamped()
        assert clamped.nx == 0.0
        assert clamped.ny == 0.9
        assert clamped.nw == 0.5
        assert clamped.nh == 0.1

    def test_display_text(self):
        region = _region("区域1")
        assert "区域1" in region.display_text()
        assert "00:00" in region.display_text()
        assert "单帧" in region.display_text()
