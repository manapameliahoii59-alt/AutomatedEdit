from app.core.render_queue import CANCEL_MESSAGE, RenderQueue
from app.data.services.render_service import RenderCancelled, RenderService


class TestRenderQueueCancel:
    def setup_method(self):
        RenderQueue._instance = None
        self.queue = RenderQueue.instance()

    def test_request_cancel_skips_pending_tasks(self):
        errors = []

        def make_task(name):
            def task():
                return name

            return task

        self.queue.submit(
            make_task("first"), on_error=lambda msg: errors.append(("first", msg))
        )
        self.queue.submit(
            make_task("second"), on_error=lambda msg: errors.append(("second", msg))
        )

        self.queue.request_cancel()

        assert ("second", CANCEL_MESSAGE) in errors
        assert self.queue.is_cancelled()

    def test_runs_second_after_first_completes(self, qtbot):
        """第一部完成后必须自动开渲第二部（不依赖 TaskManager）。"""
        done = []

        def make_task(name):
            def task():
                return name

            return task

        self.queue.submit(
            make_task("first"),
            on_success=lambda r: done.append(r),
        )
        self.queue.submit(
            make_task("second"),
            on_success=lambda r: done.append(r),
        )

        qtbot.waitUntil(lambda: done == ["first", "second"], timeout=3000)
        qtbot.waitUntil(lambda: not self.queue.is_busy(), timeout=2000)

    def test_runs_queued_job_even_if_success_callback_raises(self, qtbot):
        """一部剧成功回调异常时，仍应继续渲染队列中的下一部。"""
        done = []

        def make_task(name):
            def task():
                return name

            return task

        def ok_then_raise(result):
            done.append(("ok", result))
            raise RuntimeError("toast boom")

        def ok_second(result):
            done.append(("ok", result))

        self.queue.submit(make_task("first"), on_success=ok_then_raise)
        self.queue.submit(make_task("second"), on_success=ok_second)

        qtbot.waitUntil(lambda: ("ok", "second") in done, timeout=3000)
        assert ("ok", "first") in done
        qtbot.waitUntil(lambda: not self.queue.is_busy(), timeout=2000)

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

    def test_chained_submit_in_success_callback(self, qtbot):
        """模拟批量渲染时在 on_success 中链式提交下一部，验证所有任务的回调均被完整触发。"""
        results = []

        def submit_chain(i: int, total: int):
            if i >= total:
                return
            self.queue.submit(
                lambda i=i: f"drama_{i}",
                on_success=lambda res, i=i: (
                    results.append(res),
                    submit_chain(i + 1, total),
                ),
            )

        submit_chain(0, 4)

        qtbot.waitUntil(
            lambda: results == ["drama_0", "drama_1", "drama_2", "drama_3"],
            timeout=4000,
        )
        qtbot.waitUntil(lambda: not self.queue.is_busy(), timeout=2000)

    def test_chained_submit_in_error_callback(self, qtbot):
        """模拟在 on_error 回调中链式提交下一部，验证异常链式流转正常。"""
        errors = []

        def submit_fail_chain(i: int, total: int):
            if i >= total:
                return

            def task(i=i):
                raise RuntimeError(f"fail_{i}")

            self.queue.submit(
                task,
                on_error=lambda msg, i=i: (
                    errors.append(f"err_{i}"),
                    submit_fail_chain(i + 1, total),
                ),
            )

        submit_fail_chain(0, 3)

        qtbot.waitUntil(
            lambda: errors == ["err_0", "err_1", "err_2"],
            timeout=4000,
        )
        qtbot.waitUntil(lambda: not self.queue.is_busy(), timeout=2000)
