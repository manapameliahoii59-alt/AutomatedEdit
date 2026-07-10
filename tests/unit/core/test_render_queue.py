from unittest.mock import MagicMock

from app.core.render_queue import CANCEL_MESSAGE, RenderQueue
from app.data.services.render_service import RenderCancelled, RenderService


class TestRenderQueueCancel:
    def setup_method(self):
        RenderQueue._instance = None
        self.queue = RenderQueue.instance()

    def test_request_cancel_skips_pending_tasks(self):
        started = []
        errors = []

        def make_task(name):
            def task():
                started.append(name)
                return name

            return task

        self.queue.submit(make_task("first"), on_error=lambda msg: errors.append(("first", msg)))
        self.queue.submit(make_task("second"), on_error=lambda msg: errors.append(("second", msg)))

        self.queue.request_cancel()

        assert ("second", CANCEL_MESSAGE) in errors
        assert self.queue.is_cancelled()

    def test_render_raises_when_cancelled_before_plan(self, tmp_path, monkeypatch):
        project_path = tmp_path / "drama"
        project_path.mkdir()
        (project_path / "01.mp4").write_bytes(b"")
        (project_path / "production_plan_v3.json").write_text("[{}]", encoding="utf-8")

        from app.data.models.drama_project import DramaProject

        project = DramaProject(
            id="p1",
            name="测试剧",
            episode_count=1,
            folder_path=str(project_path),
            video_files=(str(project_path / "01.mp4"),),
        )

        monkeypatch.setattr(RenderService, "_prepare_font", staticmethod(lambda: None))
        monkeypatch.setattr(RenderService, "_has_nvenc", staticmethod(lambda _ffmpeg: False))
        monkeypatch.setattr(
            RenderService,
            "_render_single",
            staticmethod(lambda *args, **kwargs: False),
        )

        self.queue.request_cancel()
        try:
            RenderService.render(
                project,
                should_cancel=self.queue.is_cancelled,
                register_proc=self.queue.register_proc,
            )
            assert False, "expected RenderCancelled"
        except RenderCancelled as exc:
            assert "取消" in str(exc)
