import os
import time
import uuid

from PySide6.QtCore import Signal

from app.core.render_queue import CANCEL_MESSAGE, render_queue
from app.core.task_manager import task_manager
from app.core.view_model import ViewModel
from app.data.models.drama_project import DramaProject, DramaStatus
from app.data.services.drama_folder_service import DramaFolderError, scan_drama_folder
from app.data.services.transcription_service import TranscriptionService
from app.data.services.ai_director_service import AIDirectorService
from app.common.export_paths import resolve_clip_export_root
from app.data.services.render_service import RenderService, RenderResult
from app.data.services.usage_service import UsageService
from app.data.services.quota_service import QuotaService


class ClipEditViewModel(ViewModel):
    projectsChanged = Signal(list)
    loadingChanged = Signal(bool, str, str)  # loading, title, content
    messageReceived = Signal(str)
    errorOccurred = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._projects: list[DramaProject] = []
        self._status: dict[str, dict] = {}
        self._active_tasks = 0
        self.projectsChanged.emit(self._projects)

    def get_projects(self) -> list[DramaProject]:
        return list(self._projects)

    def _ensure_status(self, project_id: str) -> dict:
        if project_id not in self._status:
            self._status[project_id] = {
                "transcribe": DramaStatus.PENDING,
                "plan": DramaStatus.PENDING,
                "render": DramaStatus.PENDING,
            }
        return self._status[project_id]

    @staticmethod
    def _detect_disk_status(folder_path: str, *, transcribe_done: bool = False) -> dict:
        """根据剧目目录内产物文件推断识别/策划进度。"""
        from app.common.drama_artifact_paths import locate_production_plan, locate_script_data

        transcribed = transcribe_done or locate_script_data(folder_path) is not None
        planned = transcribed and locate_production_plan(folder_path) is not None
        return {
            "transcribe": DramaStatus.DONE if transcribed else DramaStatus.PENDING,
            "plan": DramaStatus.DONE if planned else DramaStatus.PENDING,
            "render": DramaStatus.PENDING,
        }

    @staticmethod
    def _format_import_status_hint(status: dict) -> str:
        hints = []
        if status.get("transcribe") == DramaStatus.DONE:
            hints.append("已识别")
        if status.get("plan") == DramaStatus.DONE:
            hints.append("已策划")
        return f"（{'、'.join(hints)}）" if hints else ""

    def _update_status(self, project_id: str, step: str, status: DramaStatus):
        st = self._ensure_status(project_id)
        st[step] = status
        self.projectsChanged.emit(self._projects)

    def remove_project(self, project_id: str):
        self._projects = [p for p in self._projects if p.id != project_id]
        self._status.pop(project_id, None)
        self.projectsChanged.emit(self._projects)

    def import_drama_folder(
        self,
        folder_path: str,
        *,
        transcribe_done: bool = False,
        emit_message: bool = True,
    ) -> DramaProject | None:
        try:
            scan = scan_drama_folder(folder_path)
        except DramaFolderError as exc:
            if emit_message:
                self.errorOccurred.emit(str(exc))
            return None

        disk_status = self._detect_disk_status(
            scan.folder_path, transcribe_done=transcribe_done
        )
        status_hint = self._format_import_status_hint(disk_status)

        existing = next(
            (p for p in self._projects if p.folder_path == scan.folder_path), None
        )
        if existing:
            existing.name = scan.name
            existing.episode_count = scan.episode_count
            existing.video_files = scan.video_files
            st = self._ensure_status(existing.id)
            st.update(disk_status)
            self.projectsChanged.emit(self._projects)
            if emit_message:
                self.messageReceived.emit(
                    f"已更新《{scan.name}》，共 {scan.episode_count} 集{status_hint}。"
                )
            return existing

        project = DramaProject(
            id=uuid.uuid4().hex,
            name=scan.name,
            episode_count=scan.episode_count,
            folder_path=scan.folder_path,
            video_files=scan.video_files,
        )
        self._projects.append(project)
        st = self._ensure_status(project.id)
        st.update(disk_status)
        self.projectsChanged.emit(self._projects)
        if emit_message:
            self.messageReceived.emit(
                f"已导入《{scan.name}》，共 {scan.episode_count} 集{status_hint}。"
            )
        return project

    def _add_task(self):
        self._active_tasks += 1

    def _remove_task(self):
        self._active_tasks -= 1
        if self._active_tasks == 0:
            self.loadingChanged.emit(False, "", "")

    def _progress_content(self, index: int, total: int, name: str) -> str:
        if total <= 1:
            return f"《{name}》"
        return f"第 {index}/{total} 部：《{name}》"

    def _show_progress(
        self,
        title: str,
        project_name: str,
        *,
        index: int = 1,
        total: int = 1,
    ) -> None:
        self.loadingChanged.emit(
            True,
            title,
            self._progress_content(index, total, project_name),
        )

    def _format_render_message(self, project_name: str, result: RenderResult) -> str:
        if result.success_count == result.total:
            return f"《{project_name}》渲染完成，已保存至：{result.output_dir}"
        failed = result.total - result.success_count
        return (
            f"《{project_name}》渲染完成 {result.success_count}/{result.total} 条，"
            f"失败 {failed} 条，已保存至：{result.output_dir}"
        )

    def _report_clip_done(self, project_name: str) -> None:
        if project_name:
            UsageService.report_clip_drama(project_name)

    def _report_plan_done(self, project_name: str) -> None:
        if project_name:
            UsageService.report_plan_drama(project_name)

    def _ensure_can_plan(self, project_name: str) -> bool:
        allowed, message = QuotaService.instance().check_remote("plan", project_name)
        if not allowed:
            self.errorOccurred.emit(message)
            return False
        return True

    def _ensure_can_clip(self, project_name: str) -> bool:
        allowed, message = QuotaService.instance().check_remote("clip", project_name)
        if not allowed:
            self.errorOccurred.emit(message)
            return False
        return True

    def request_cancel(self) -> None:
        render_queue.request_cancel()

    def _is_render_cancelled(self, msg: str) -> bool:
        return msg == CANCEL_MESSAGE or "渲染已取消" in msg

    def _emit_render_error(self, msg: str, *, prefix: str = "渲染失败") -> None:
        if self._is_render_cancelled(msg):
            self.messageReceived.emit("渲染已取消")
        else:
            self.errorOccurred.emit(f"{prefix}：{msg}" if prefix else msg)

    @staticmethod
    def _format_elapsed(seconds: float) -> str:
        if seconds < 60:
            return f"{seconds:.1f} 秒"
        minutes, secs = divmod(int(seconds), 60)
        if minutes < 60:
            return f"{minutes} 分 {secs} 秒"
        hours, minutes = divmod(minutes, 60)
        return f"{hours} 小时 {minutes} 分 {secs} 秒"

    def _append_render_timing(
        self,
        message: str,
        *,
        project_name: str,
        started_at: float | None,
    ) -> str:
        if started_at is None:
            return message
        elapsed = self._format_elapsed(time.perf_counter() - started_at)
        print(f"⏱ 《{project_name}》渲染耗时：{elapsed}", flush=True)
        return f"{message}\n耗时：{elapsed}"

    def _submit_render(
        self,
        project: DramaProject,
        *,
        on_success,
        on_error,
        index: int = 1,
        total: int = 1,
    ) -> None:
        pid = project.id
        pname = project.name

        def _on_start():
            self._update_status(pid, "render", DramaStatus.IN_PROGRESS)
            self._show_progress("正在渲染", pname, index=index, total=total)

        render_queue.submit(
            lambda: RenderService.render(
                project,
                should_cancel=render_queue.is_cancelled,
                register_proc=render_queue.register_proc,
            ),
            on_success=on_success,
            on_error=on_error,
            on_start=_on_start,
        )

    def start_transcribe(self, project_id: str):
        project = next((p for p in self._projects if p.id == project_id), None)
        if not project:
            self.errorOccurred.emit("未找到该剧目")
            return

        try:
            warnings = TranscriptionService.check_environment()
        except ImportError as e:
            self.errorOccurred.emit(f"识别环境检查未通过：{e}")
            return

        if warnings:
            self.messageReceived.emit("环境提示：\n- " + "\n- ".join(warnings))

        self._update_status(project_id, "transcribe", DramaStatus.IN_PROGRESS)
        self._show_progress("正在识别", project.name)
        self._add_task()

        def _do():
            TranscriptionService.transcribe(project)
            return True

        def _on_success(_ok):
            self._remove_task()
            self._update_status(project_id, "transcribe", DramaStatus.DONE)
            UsageService.report("transcribe")
            self.messageReceived.emit(f"《{project.name}》识别完成")

        def _on_error(msg):
            self._remove_task()
            self._update_status(project_id, "transcribe", DramaStatus.PENDING)
            self.errorOccurred.emit(f"识别失败：{msg}")

        task_manager.submit_task(
            _do,
            on_success=_on_success,
            on_error=_on_error,
        )

    def start_planning(self, project_id: str):
        project = next((p for p in self._projects if p.id == project_id), None)
        if not project:
            self.errorOccurred.emit("未找到该剧目")
            return

        st = self._ensure_status(project_id)
        if st.get("transcribe") != DramaStatus.DONE:
            self.messageReceived.emit("请先完成识别视频")
            return
        if not self._ensure_can_plan(project.name):
            return

        self._update_status(project_id, "plan", DramaStatus.IN_PROGRESS)
        self._show_progress("正在策划", project.name)
        self._add_task()

        def _do():
            AIDirectorService.plan(project)
            return True

        def _on_success(_ok):
            self._remove_task()
            self._update_status(project_id, "plan", DramaStatus.DONE)
            UsageService.report("plan")
            self._report_plan_done(project.name)
            self.messageReceived.emit(f"《{project.name}》策划完成")

        def _on_error(msg):
            self._remove_task()
            self._update_status(project_id, "plan", DramaStatus.PENDING)
            self.errorOccurred.emit(f"策划失败：{msg}")

        task_manager.submit_task(
            _do,
            on_success=_on_success,
            on_error=_on_error,
        )

    def start_render(self, project_id: str, *, timed: bool = False):
        project = next((p for p in self._projects if p.id == project_id), None)
        if not project:
            self.errorOccurred.emit("未找到该剧目")
            return

        st = self._ensure_status(project_id)
        if st.get("plan") != DramaStatus.DONE:
            self.messageReceived.emit("请先完成 AI 策划")
            return
        if not self._ensure_can_clip(project.name):
            return

        started_at = time.perf_counter() if timed else None
        if timed:
            print(f"⏱ 开始计时渲染《{project.name}》", flush=True)

        self._show_progress("正在渲染", project.name)
        self._add_task()

        def _on_success(result: RenderResult):
            self._remove_task()
            self._update_status(project_id, "render", DramaStatus.DONE)
            UsageService.report("render", success=result.success_count > 0)
            self._report_clip_done(project.name)
            message = self._format_render_message(project.name, result)
            message = self._append_render_timing(
                message,
                project_name=project.name,
                started_at=started_at,
            )
            self.messageReceived.emit(message)

        def _on_error(msg):
            self._remove_task()
            self._update_status(project_id, "render", DramaStatus.PENDING)
            if timed and started_at is not None and not self._is_render_cancelled(msg):
                elapsed = self._format_elapsed(time.perf_counter() - started_at)
                print(f"⏱ 《{project.name}》渲染失败，耗时：{elapsed}", flush=True)
            self._emit_render_error(msg)

        self._submit_render(project, on_success=_on_success, on_error=_on_error)

    def batch_transcribe(self, project_ids: list[str]):
        valid = []
        skipped = 0
        for pid in project_ids:
            project = next((p for p in self._projects if p.id == pid), None)
            if not project:
                skipped += 1
                continue
            try:
                TranscriptionService.check_environment()
            except ImportError:
                skipped += 1
                continue
            valid.append(project)

        if not valid:
            self.messageReceived.emit("没有符合条件的项目可执行识别")
            return

        results = {"success": 0, "fail": 0}
        total = len(valid)
        for index, project in enumerate(valid, 1):
            self._update_status(project.id, "transcribe", DramaStatus.IN_PROGRESS)
            self._show_progress("正在识别", project.name, index=index, total=total)
            self._add_task()

            pid = project.id
            pname = project.name

            def _on_success(_ok, pid=pid, pname=pname):
                self._remove_task()
                self._update_status(pid, "transcribe", DramaStatus.DONE)
                results["success"] += 1
                if self._active_tasks == 0:
                    self._emit_batch_summary("批量识别完成", results, skipped)

            def _on_error(msg, pid=pid, pname=pname):
                self._remove_task()
                self._update_status(pid, "transcribe", DramaStatus.PENDING)
                results["fail"] += 1
                if self._active_tasks == 0:
                    self._emit_batch_summary("批量识别完成", results, skipped)

            task_manager.submit_task(
                lambda p=project: TranscriptionService.transcribe(p),
                on_success=_on_success,
                on_error=_on_error,
            )

    def batch_plan(self, project_ids: list[str]):
        valid = []
        skipped = 0
        for pid in project_ids:
            project = next((p for p in self._projects if p.id == pid), None)
            if not project:
                skipped += 1
                continue
            st = self._ensure_status(pid)
            if st.get("transcribe") != DramaStatus.DONE:
                skipped += 1
                continue
            valid.append(project)

        if not valid:
            self.messageReceived.emit("没有符合条件的项目可执行策划")
            return

        results = {"success": 0, "fail": 0}
        total = len(valid)
        for index, project in enumerate(valid, 1):
            if not self._ensure_can_plan(project.name):
                skipped += 1
                continue
            self._update_status(project.id, "plan", DramaStatus.IN_PROGRESS)
            self._show_progress("正在策划", project.name, index=index, total=total)
            self._add_task()

            pid = project.id
            pname = project.name

            def _on_success(_ok, pid=pid, pname=pname):
                self._remove_task()
                self._update_status(pid, "plan", DramaStatus.DONE)
                UsageService.report("plan")
                self._report_plan_done(pname)
                results["success"] += 1
                if self._active_tasks == 0:
                    self._emit_batch_summary("批量策划完成", results, skipped)

            def _on_error(msg, pid=pid, pname=pname):
                self._remove_task()
                self._update_status(pid, "plan", DramaStatus.PENDING)
                results["fail"] += 1
                if self._active_tasks == 0:
                    self._emit_batch_summary("批量策划完成", results, skipped)

            task_manager.submit_task(
                lambda p=project: AIDirectorService.plan(p),
                on_success=_on_success,
                on_error=_on_error,
            )

    def batch_render(self, project_ids: list[str], *, timed: bool = False):
        valid = []
        skipped = 0
        for pid in project_ids:
            project = next((p for p in self._projects if p.id == pid), None)
            if not project:
                skipped += 1
                continue
            st = self._ensure_status(pid)
            if st.get("plan") != DramaStatus.DONE:
                skipped += 1
                continue
            valid.append(project)

        if not valid:
            self.messageReceived.emit("没有符合条件的项目可执行渲染")
            return

        batch_started = time.perf_counter() if timed else None
        item_started: dict[str, float] = {}
        if timed:
            print(f"⏱ 开始批量渲染计时（{len(valid)} 个剧目）", flush=True)

        results = {"success": 0, "fail": 0}
        total = len(valid)
        for index, project in enumerate(valid, 1):
            if not self._ensure_can_clip(project.name):
                skipped += 1
                continue
            self._add_task()
            if index == 1:
                self._show_progress("正在渲染", project.name, index=index, total=total)

            pid = project.id
            pname = project.name
            if timed:
                item_started[pid] = time.perf_counter()

            def _finish_batch_summary(prefix: str) -> None:
                if timed and batch_started is not None:
                    total_elapsed = self._format_elapsed(
                        time.perf_counter() - batch_started
                    )
                    print(f"⏱ 批量渲染总耗时：{total_elapsed}", flush=True)
                    parts = [f"{prefix}：成功 {results['success']} 个"]
                    if results["fail"]:
                        parts.append(f"失败 {results['fail']} 个")
                    if skipped:
                        parts.append(f"跳过 {skipped} 个")
                    parts.append(f"总耗时 {total_elapsed}")
                    self.messageReceived.emit("，".join(parts))
                else:
                    self._emit_batch_summary(prefix, results, skipped)

            def _on_success(_result: RenderResult, pid=pid, pname=pname):
                self._remove_task()
                self._update_status(pid, "render", DramaStatus.DONE)
                results["success"] += 1
                self._report_clip_done(pname)
                if timed and pid in item_started:
                    elapsed = self._format_elapsed(time.perf_counter() - item_started[pid])
                    print(f"⏱ 《{pname}》渲染耗时：{elapsed}", flush=True)
                if self._active_tasks == 0:
                    root = resolve_clip_export_root()
                    _finish_batch_summary(f"批量渲染完成（导出目录：{root}）")

            def _on_error(msg, pid=pid, pname=pname):
                self._remove_task()
                self._update_status(pid, "render", DramaStatus.PENDING)
                results["fail"] += 1
                if timed and pid in item_started and not self._is_render_cancelled(msg):
                    elapsed = self._format_elapsed(time.perf_counter() - item_started[pid])
                    print(f"⏱ 《{pname}》渲染失败，耗时：{elapsed}", flush=True)
                if self._active_tasks == 0:
                    if self._is_render_cancelled(msg):
                        self.messageReceived.emit("渲染已取消")
                    _finish_batch_summary("批量渲染完成")

            self._submit_render(
                project,
                on_success=_on_success,
                on_error=_on_error,
                index=index,
                total=total,
            )

    def _emit_batch_summary(self, prefix: str, results: dict, skipped: int):
        parts = [f"{prefix}：成功 {results['success']} 个"]
        if results["fail"]:
            parts.append(f"失败 {results['fail']} 个")
        if skipped:
            parts.append(f"跳过 {skipped} 个")
        self.messageReceived.emit("，".join(parts))

    def batch_all(self, project_ids: list[str]):
        projects = []
        for pid in project_ids:
            project = next((p for p in self._projects if p.id == pid), None)
            if project:
                projects.append(project)
        total = len(projects)
        for index, project in enumerate(projects, 1):
            self._run_pipeline(project, index=index, total=total)

    def import_drama_folders(self, folder_paths: list[str]) -> int:
        """批量导入剧目文件夹（不自动执行剪辑流程）。"""
        imported = 0
        for folder in folder_paths:
            project = self.import_drama_folder(folder, emit_message=False)
            if project:
                imported += 1

        if imported:
            self.messageReceived.emit(f"已导入 {imported} 个剧目到自动化剪辑")
        else:
            self.messageReceived.emit("未找到可导入的剧目文件夹")
        return imported

    def import_and_run_clip_pipeline(self, folder_paths: list[str]) -> int:
        """从下载页导入已识别剧目，并执行策划与渲染。"""
        imported_ids: list[str] = []
        for folder in folder_paths:
            project = self.import_drama_folder(
                folder, transcribe_done=True, emit_message=False
            )
            if project:
                imported_ids.append(project.id)

        if not imported_ids:
            self.messageReceived.emit("没有可导入剪辑的剧目（识别可能未成功）")
            return 0

        total = len(imported_ids)
        for index, pid in enumerate(imported_ids, 1):
            project = next((p for p in self._projects if p.id == pid), None)
            if project:
                self._run_pipeline_after_transcribe(project, index=index, total=total)

        self.messageReceived.emit(
            f"已从下载页自动导入 {len(imported_ids)} 个剧目，正在执行 AI 策划与渲染…"
        )
        return len(imported_ids)

    def _run_pipeline_after_transcribe(
        self,
        project: DramaProject,
        *,
        index: int = 1,
        total: int = 1,
    ):
        pid = project.id
        pname = project.name
        self._update_status(pid, "transcribe", DramaStatus.DONE)
        if not self._ensure_can_plan(pname):
            return

        def step2():
            AIDirectorService.plan(project)
            return True

        def step2_done(_ok):
            self._update_status(pid, "plan", DramaStatus.DONE)
            UsageService.report("batch_all_plan")
            self._report_plan_done(pname)
            if not self._ensure_can_clip(pname):
                self._remove_task()
                return

            def step3_done(result: RenderResult):
                self._remove_task()
                self._update_status(pid, "render", DramaStatus.DONE)
                UsageService.report("batch_all_render", success=result.success_count > 0)
                self._report_clip_done(pname)
                self.messageReceived.emit(
                    f"《{pname}》自动剪辑完成。\n"
                    f"{self._format_render_message(pname, result)}"
                )

            def step3_err(msg):
                self._remove_task()
                self._update_status(pid, "render", DramaStatus.PENDING)
                if self._is_render_cancelled(msg):
                    self.messageReceived.emit(f"《{pname}》渲染已取消")
                else:
                    self.errorOccurred.emit(f"《{pname}》渲染失败：{msg}")

            self._submit_render(
                project,
                on_success=step3_done,
                on_error=step3_err,
                index=index,
                total=total,
            )

        def step2_err(msg):
            self._remove_task()
            self._update_status(pid, "plan", DramaStatus.PENDING)
            self.errorOccurred.emit(f"《{pname}》策划失败：{msg}")

        self._add_task()
        self._show_progress("正在策划", pname, index=index, total=total)
        self._update_status(pid, "plan", DramaStatus.IN_PROGRESS)
        task_manager.submit_task(step2, on_success=step2_done, on_error=step2_err)

    def _run_pipeline(
        self,
        project: DramaProject,
        *,
        index: int = 1,
        total: int = 1,
    ):
        pid = project.id
        pname = project.name

        def step1():
            TranscriptionService.transcribe(project)
            return True

        def step1_done(_ok):
            self._update_status(pid, "transcribe", DramaStatus.DONE)
            UsageService.report("batch_all_transcribe")

            def step2():
                AIDirectorService.plan(project)
                return True

            def step2_done(_ok):
                self._update_status(pid, "plan", DramaStatus.DONE)
                UsageService.report("batch_all_plan")
                self._report_plan_done(pname)
                if not self._ensure_can_clip(pname):
                    self._remove_task()
                    return

                def step3_done(result: RenderResult):
                    self._remove_task()
                    self._update_status(pid, "render", DramaStatus.DONE)
                    UsageService.report("batch_all_render", success=result.success_count > 0)
                    self._report_clip_done(pname)
                    self.messageReceived.emit(
                        f"《{pname}》一键执行完成。\n"
                        f"{self._format_render_message(pname, result)}"
                    )

                def step3_err(msg):
                    self._remove_task()
                    self._update_status(pid, "render", DramaStatus.PENDING)
                    if self._is_render_cancelled(msg):
                        self.messageReceived.emit(f"《{pname}》渲染已取消")
                    else:
                        self.errorOccurred.emit(f"《{pname}》渲染失败：{msg}")

                self._submit_render(
                    project,
                    on_success=step3_done,
                    on_error=step3_err,
                    index=index,
                    total=total,
                )

            def step2_err(msg):
                self._remove_task()
                self._update_status(pid, "plan", DramaStatus.PENDING)
                self.errorOccurred.emit(f"《{pname}》策划失败：{msg}")

            self._show_progress("正在策划", pname, index=index, total=total)
            self._update_status(pid, "plan", DramaStatus.IN_PROGRESS)
            task_manager.submit_task(step2, on_success=step2_done, on_error=step2_err)

        def step1_err(msg):
            self._remove_task()
            self._update_status(pid, "transcribe", DramaStatus.PENDING)
            self.errorOccurred.emit(f"《{pname}》识别失败：{msg}")

        self._add_task()
        self._show_progress("正在识别", pname, index=index, total=total)
        self._update_status(pid, "transcribe", DramaStatus.IN_PROGRESS)
        task_manager.submit_task(step1, on_success=step1_done, on_error=step1_err)
