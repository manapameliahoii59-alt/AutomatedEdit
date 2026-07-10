from app.common.clip_progress import format_plan_progress, format_render_progress


class TestClipProgressFormat:
    def test_plan_progress_simple(self):
        text = format_plan_progress({"current": 8, "total": 15, "detail": "ignored"})
        assert text == "策划中 8/15 条"

    def test_render_cache_progress(self):
        text = format_render_progress({"phase": "cache", "current": 3, "total": 10})
        assert text == "预处理 3/10 集"

    def test_render_clip_progress(self):
        text = format_render_progress(
            {"phase": "render", "current": 5, "total": 17, "detail": "demo.mp4"}
        )
        assert text == "渲染中 5/17 条"
