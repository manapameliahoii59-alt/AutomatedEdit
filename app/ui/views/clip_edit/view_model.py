import os
import time
import uuid

from PySide6.QtCore import Signal

from app.common.clip_progress import format_plan_progress, format_render_progress
from app.common.export_paths import resolve_clip_export_root
from app.common.my_logger import my_logger as logger
from app.common.plan_settings import apply_plan_settings_dict, plan_settings_patch
from app.common.overlay_text_settings import (
    apply_overlay_from_clip_edit_dict,
    clip_edit_settings_patch,
)
from app.common.error_sanitizer import (
    sanitize_plan_error,
    sanitize_render_error,
    sanitize_transcribe_error,
    sanitize_transcribe_warning,
    sanitize_ui_error,
)
from app.core.render_queue import CANCEL_MESSAGE, render_queue
from app.core.task_manager import task_manager
from app.core.view_model import ViewModel
from app.data.api.api import get_api
from app.data.models.batch_execution_record import (
    BatchExecutionSummary,
    DramaTimingRecord,
)
from app.data.models.drama_project import DramaProject, DramaStatus
from app.data.services.drama_folder_service import DramaFolderError, scan_drama_folder
from app.data.services.transcription_service import TranscriptionService
from app.data.services.ai_director_service import AIDirectorService
from app.data.services.render_service import RenderService, RenderResult
from app.data.services.usage_service import UsageService
from app.data.services.quota_service import QuotaService


def _format_plan_result_message(project_name: str, result: dict | None = None) -> str:
    """策划完成文案；条数不足时明确提示。"""
    if not isinstance(result, dict):
        return f"《{project_name}》策划完成"
    count = int(result.get("count") or 0)
    target = int(result.get("target") or 0)
    if result.get("underfilled") and target > 0 and count < target:
        return (
            f"《{project_name}》策划完成：仅通过 {count}/{target} 条。"
            "部分候选因时长不在范围内或切点台词未匹配剧本被过滤，可重试策划。"
        )
    if target > 0:
        return f"《{project_name}》策划完成：{count}/{target} 条"
    return f"《{project_name}》策划完成"


class ClipEditViewModel(ViewModel):
    projectsChanged = Signal(list)
    loadingChanged = Signal(bool, str, str)  # loading, title, content
    loadingContentChanged = Signal(str)
    stageProgressChanged = Signal(str, str, str)  # project_id, step, text
    messageReceived = Signal(str)
    errorOccurred = Signal(str)
    settingsLoaded = Signal(dict)  # clip_edit namespace from server
    batchExecutionStarted = Signal(object)  # BatchExecutionSummary
    batchExecutionUpdated = Signal(object, str, int, int)  # record, action_text, current_index, total_count
    batchExecutionFinished = Signal(object)  # BatchExecutionSummary

    def __init__(self, parent=None):
        super().__init__(parent)
        self._projects: list[DramaProject] = []
        self._status: dict[str, dict] = {}
        self._progress_labels: dict[str, dict[str, str]] = {}
        self._active_tasks = 0
        self._loading_project_id: str | None = None
        self._loading_base_content = ""
        self._batch_cancel_requested = False
        self._current_batch_summary: BatchExecutionSummary | None = None
        self.projectsChanged.emit(self._projects)
        self._load_settings_from_server()

    def _load_settings_from_server(self) -> None:
        def _do():
            api = get_api()
            if not api._token:
                return None
            return api.get_settings()

        def _on_success(data):
            if not data:
                return
            apply_plan_settings_dict(data.get("plan"))
            clip_edit = data.get("clip_edit") or {}
            apply_overlay_from_clip_edit_dict(clip_edit)
            self.settingsLoaded.emit(clip_edit)

        task_manager.submit_task(_do, on_success=_on_success, on_error=lambda _m: None)

    def save_export_name_tag(self, tag: str) -> None:
        """本地已写入 cfg 后，后台同步文件名标识到服务端。"""
        api = get_api()
        if not api._token:
            return
        patch = clip_edit_settings_patch(export_name_tag=tag)

        def _do():
            get_api().update_settings(patch)
            return True

        def _on_error(msg: str):
            self.errorOccurred.emit(
                sanitize_ui_error(
                    msg, stage="settings_sync", friendly="文件名标识同步失败，请检查网络后重试"
                )
            )

        task_manager.submit_task(_do, on_success=lambda _ok: None, on_error=_on_error)

    def save_export_name_format(self, date_format: str, seq_format: str) -> None:
        """本地已写入 cfg 后，后台同步文件名日期/序号格式到服务端。"""
        api = get_api()
        if not api._token:
            return
        patch = clip_edit_settings_patch(
            export_date_format=date_format,
            export_seq_format=seq_format,
        )

        def _do():
            get_api().update_settings(patch)
            return True

        def _on_error(msg: str):
            self.errorOccurred.emit(
                sanitize_ui_error(
                    msg, stage="settings_sync", friendly="文件名格式同步失败，请检查网络后重试"
                )
            )

        task_manager.submit_task(_do, on_success=lambda _ok: None, on_error=_on_error)

    def save_output_resolution(self, resolution: str) -> None:
        """本地已写入 cfg 后，后台同步成片分辨率到服务端。"""
        api = get_api()
        if not api._token:
            return
        patch = clip_edit_settings_patch(output_resolution=resolution)
        if not patch.get("clip_edit"):
            return

        def _do():
            get_api().update_settings(patch)
            return True

        def _on_error(msg: str):
            self.errorOccurred.emit(
                sanitize_ui_error(
                    msg, stage="settings_sync", friendly="成片分辨率同步失败，请检查网络后重试"
                )
            )

        task_manager.submit_task(_do, on_success=lambda _ok: None, on_error=_on_error)

    def save_overlay_text_settings(
        self,
        *,
        overlay_title: dict,
        overlay_disclaimer: dict,
    ) -> None:
        """本地已写入 cfg 后，后台同步画面叠字到服务端。"""
        api = get_api()
        if not api._token:
            return
        patch = clip_edit_settings_patch(
            overlay_title=overlay_title,
            overlay_disclaimer=overlay_disclaimer,
        )

        def _do():
            get_api().update_settings(patch)
            return True

        def _on_error(msg: str):
            self.errorOccurred.emit(
                sanitize_ui_error(
                    msg, stage="settings_sync", friendly="画面文字设置同步失败，请检查网络后重试"
                )
            )

        task_manager.submit_task(_do, on_success=lambda _ok: None, on_error=_on_error)

    def save_overlay_text_library(self, library: dict) -> None:
        """同步整份画面文字组库到服务端。"""
        api = get_api()
        if not api._token:
            return
        patch = clip_edit_settings_patch(overlay_text_library=library)

        def _do():
            get_api().update_settings(patch)
            return True

        def _on_error(msg: str):
            self.errorOccurred.emit(
                sanitize_ui_error(
                    msg, stage="settings_sync", friendly="画面文字组同步失败，请检查网络后重试"
                )
            )

        task_manager.submit_task(_do, on_success=lambda _ok: None, on_error=_on_error)

    def save_plan_settings(
        self,
        *,
        mode: str | None = None,
        clip_count: int | None = None,
        max_duration_sec: int | None = None,
        short_clip_count: int | None = None,
        short_max_duration_sec: int | None = None,
        mixed_clip_count: int | None = None,
        mixed_max_duration_sec: int | None = None,
        global_speed: float | None = None,
    ) -> None:
        """本地已写入 cfg 后，后台同步到服务端用户设置。"""
        api = get_api()
        if not api._token:
            return
        patch = plan_settings_patch(
            mode=mode,
            clip_count=clip_count,
            max_duration_sec=max_duration_sec,
            short_clip_count=short_clip_count,
            short_max_duration_sec=short_max_duration_sec,
            mixed_clip_count=mixed_clip_count,
            mixed_max_duration_sec=mixed_max_duration_sec,
            global_speed=global_speed,
        )
        if not patch.get("plan"):
            return

        def _do():
            get_api().update_settings(patch)
            return True

        def _on_error(msg: str):
            self.errorOccurred.emit(
                sanitize_ui_error(
                    msg, stage="settings_sync", friendly="策划设置同步失败，请检查网络后重试"
                )
            )

        task_manager.submit_task(_do, on_success=lambda _ok: None, on_error=_on_error)

    @staticmethod
    def _format_elapsed(seconds: float) -> str:
        if seconds < 60:
            return f"{seconds:.1f} 秒"
        minutes, secs = divmod(int(seconds), 60)
        if minutes < 60:
            return f"{minutes} 分 {secs} 秒"
        hours, minutes = divmod(minutes, 60)
        return f"{hours} 小时 {minutes} 分 {secs} 秒"

    def get_stage_progress(self, project_id: str, step: str) -> str:
        return self._progress_labels.get(project_id, {}).get(step, "")

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
        if status != DramaStatus.IN_PROGRESS:
            self._progress_labels.get(project_id, {}).pop(step, None)
        self.projectsChanged.emit(self._projects)

    def _set_stage_progress(self, project_id: str, step: str, text: str) -> None:
        self._progress_labels.setdefault(project_id, {})[step] = text
        st = self._ensure_status(project_id)
        st[step] = DramaStatus.IN_PROGRESS
        self.stageProgressChanged.emit(project_id, step, text)
        if project_id == self._loading_project_id:
            prefix = f"{self._loading_base_content}\n" if self._loading_base_content else ""
            self.loadingContentChanged.emit(f"{prefix}{text}")

    def _make_plan_progress_handler(self, project_id: str):
        last_at = 0.0

        def _handler(info: dict) -> None:
            nonlocal last_at
            now = time.time()
            if now - last_at < 0.8:
                return
            last_at = now
            self._set_stage_progress(project_id, "plan", format_plan_progress(info))

        return _handler

    def _make_render_progress_handler(self, project_id: str):
        last_at = 0.0

        def _handler(info: dict) -> None:
            nonlocal last_at
            now = time.time()
            if now - last_at < 0.8:
                return
            last_at = now
            self._set_stage_progress(project_id, "render", format_render_progress(info))

        return _handler

    def remove_project(self, project_id: str):
        self._projects = [p for p in self._projects if p.id != project_id]
        self._status.pop(project_id, None)
        self._progress_labels.pop(project_id, None)
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
        if self._active_tasks > 0:
            self._active_tasks -= 1
        if self._active_tasks <= 0:
            self._active_tasks = 0
            if not render_queue.is_busy():
                self._loading_project_id = None
                self._loading_base_content = ""
                self.loadingChanged.emit(False, "", "")

    def _finish_loading_if_idle(self) -> None:
        """渲染队列空闲且无活跃任务时关闭进度条（避免收尾竞态卡住）。"""
        if self._active_tasks <= 0 and not render_queue.is_busy():
            self._active_tasks = 0
            self._loading_project_id = None
            self._loading_base_content = ""
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
        project_id: str | None = None,
        index: int = 1,
        total: int = 1,
    ) -> None:
        self._loading_project_id = project_id
        self._loading_base_content = self._progress_content(index, total, project_name)
        self.loadingChanged.emit(True, title, self._loading_base_content)

    def _format_render_message(self, project_name: str, result: RenderResult) -> str:
        cost_str = ""
        if result.total_seconds > 0:
            speed_str = f"，速度 {result.speed_ratio:.1f}x" if result.speed_ratio > 0 else ""
            cost_str = f"（耗时 {result.total_seconds:.1f}s{speed_str}）"
        if result.success_count == result.total:
            return f"《{project_name}》渲染完成{cost_str}，已保存至：{result.output_dir}"
        failed = result.total - result.success_count
        return (
            f"《{project_name}》渲染完成 {result.success_count}/{result.total} 条"
            f"（失败 {failed} 条）{cost_str}，已保存至：{result.output_dir}"
        )

    def _report_clip_done(self, project_name: str) -> None:
        if project_name:
            UsageService.report_clip_drama(project_name)

    def _report_plan_done(self, project_name: str) -> None:
        if project_name:
            from app.common.plan_settings import resolve_active_plan_params

            mode = resolve_active_plan_params().get("mode")
            UsageService.report_plan_drama(project_name, plan_mode=mode)

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
        self._batch_cancel_requested = True
        render_queue.request_cancel()

    def _is_render_cancelled(self, msg: str) -> bool:
        return msg == CANCEL_MESSAGE or "渲染已取消" in msg

    def _emit_render_error(self, msg: str, *, drama_name: str = "", prefix: str = "渲染失败") -> None:
        if self._is_render_cancelled(msg):
            cancel_msg = f"《{drama_name}》渲染已取消" if drama_name else "渲染已取消"
            self.messageReceived.emit(cancel_msg)
        else:
            self.errorOccurred.emit(sanitize_render_error(msg, drama_name=drama_name))

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
            self._show_progress(
                "正在渲染",
                pname,
                project_id=pid,
                index=index,
                total=total,
            )

        progress_handler = self._make_render_progress_handler(pid)
        started = render_queue.submit(
            lambda: RenderService.render(
                project,
                should_cancel=render_queue.is_cancelled,
                register_proc=render_queue.register_proc,
                progress_callback=progress_handler,
            ),
            on_success=on_success,
            on_error=on_error,
            on_start=_on_start,
        )
        # 已有任务在渲时，立刻标成排队中，避免第二部一直显示「待处理」
        if not started:
            self._set_stage_progress(pid, "render", "排队中")

    def start_transcribe(self, project_id: str):
        project = next((p for p in self._projects if p.id == project_id), None)
        if not project:
            self.errorOccurred.emit("未找到该剧目")
            return

        try:
            warnings = TranscriptionService.check_environment()
        except ImportError as e:
            self.errorOccurred.emit(sanitize_transcribe_error(e, drama_name=project.name))
            return

        if warnings:
            sanitized_warnings = [
                w for w in (sanitize_transcribe_warning(w) for w in warnings) if w
            ]
            sanitized_warnings = list(dict.fromkeys(sanitized_warnings))
            if sanitized_warnings:
                self.messageReceived.emit("环境提示：\n- " + "\n- ".join(sanitized_warnings))

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
            self.errorOccurred.emit(sanitize_transcribe_error(msg, drama_name=project.name))

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
        self._show_progress("正在策划", project.name, project_id=project_id)
        self._add_task()

        plan_handler = self._make_plan_progress_handler(project_id)

        def _do():
            return AIDirectorService.plan(project, progress_callback=plan_handler)

        def _on_success(result):
            self._remove_task()
            self._update_status(project_id, "plan", DramaStatus.DONE)
            UsageService.report("plan")
            self._report_plan_done(project.name)
            self.messageReceived.emit(_format_plan_result_message(project.name, result))

        def _on_error(msg):
            self._remove_task()
            self._update_status(project_id, "plan", DramaStatus.PENDING)
            self.errorOccurred.emit(sanitize_plan_error(msg, drama_name=project.name))

        task_manager.submit_task(
            _do,
            on_success=_on_success,
            on_error=_on_error,
        )

    def start_render(self, project_id: str):
        project = next((p for p in self._projects if p.id == project_id), None)
        if not project:
            self.errorOccurred.emit("未找到该剧目")
            return

        st = self._ensure_status(project_id)
        if st.get("plan") != DramaStatus.DONE:
            self.messageReceived.emit("请先完成策划")
            return
        if not self._ensure_can_clip(project.name):
            return

        self._show_progress("正在渲染", project.name, project_id=project_id)
        self._add_task()

        def _on_success(result: RenderResult):
            self._remove_task()
            self._update_status(project_id, "render", DramaStatus.DONE)
            UsageService.report("render", success=result.success_count > 0)
            self._report_clip_done(project.name)
            self.messageReceived.emit(self._format_render_message(project.name, result))
            self._finish_loading_if_idle()

        def _on_error(msg):
            self._remove_task()
            self._update_status(project_id, "render", DramaStatus.PENDING)
            self._emit_render_error(msg, drama_name=project.name)
            self._finish_loading_if_idle()

        self._submit_render(project, on_success=_on_success, on_error=_on_error)

    def benchmark_encode_speed(self, project_id: str, *, cpu_only: bool = False) -> None:
        """测试所选剧目渲染速度；默认 CPU/GPU 对比，cpu_only 时只测 CPU。"""
        project = next((p for p in self._projects if p.id == project_id), None)
        if not project:
            self.errorOccurred.emit("未找到该剧目")
            return
        st = self._ensure_status(project_id)
        if st.get("plan") != DramaStatus.DONE:
            self.messageReceived.emit("请先完成策划后再测试渲染速度")
            return

        title = "测试CPU渲染速度" if cpu_only else "测试编码速度"
        self._show_progress(title, project.name, project_id=project_id)
        self._add_task()

        def _do():
            return RenderService.benchmark_encode_speed(
                project,
                cpu_only=cpu_only,
                progress_callback=self._make_render_progress_handler(project_id),
                should_cancel=render_queue.is_cancelled,
            )

        def _on_success(result):
            self._remove_task()
            self.messageReceived.emit(result.message)
            self._finish_loading_if_idle()

        def _on_error(msg):
            self._remove_task()
            if self._is_render_cancelled(msg):
                self.messageReceived.emit("编码速度测试已取消")
            else:
                self.errorOccurred.emit(
                    sanitize_ui_error(
                        msg, stage="render_test", friendly="编码速度测试失败，请稍后重试"
                    )
                )
            self._finish_loading_if_idle()

        task_manager.submit_task(_do, on_success=_on_success, on_error=_on_error)

    def batch_transcribe(self, project_ids: list[str]):
        queue: list[DramaProject] = []
        skipped = 0
        for pid in project_ids:
            project = next((p for p in self._projects if p.id == pid), None)
            if not project:
                skipped += 1
                continue
            queue.append(project)

        if not queue:
            self.messageReceived.emit("没有符合条件的项目可执行识别")
            return

        results = {"success": 0, "fail": 0}
        total = len(queue)
        records = [
            DramaTimingRecord(
                project_id=p.id,
                project_name=p.name,
                episode_count=p.episode_count,
            )
            for p in queue
        ]
        summary = BatchExecutionSummary(task_type="transcribe", records=records)
        self._current_batch_summary = summary
        self._batch_cancel_requested = False
        batch_started_at = time.perf_counter()
        self.batchExecutionStarted.emit(summary)

        def _run_at(index: int) -> None:
            if self._batch_cancel_requested:
                for i in range(index, total):
                    records[i].transcribe_status = "cancelled"
                summary.is_cancelled = True
                summary.total_elapsed = time.perf_counter() - batch_started_at
                self.batchExecutionFinished.emit(summary)
                self.messageReceived.emit("批量识别已取消")
                self._finish_loading_if_idle()
                return

            if index >= total:
                summary.total_elapsed = time.perf_counter() - batch_started_at
                self.batchExecutionFinished.emit(summary)
                self._emit_batch_summary("批量识别完成", results, skipped)
                self._finish_loading_if_idle()
                return

            project = queue[index]
            rec = records[index]
            pid = project.id
            pname = project.name
            rec.transcribe_status = "in_progress"
            item_started_at = time.perf_counter()
            self._update_status(pid, "transcribe", DramaStatus.IN_PROGRESS)
            self._show_progress("正在识别", pname, index=index + 1, total=total)
            self.batchExecutionUpdated.emit(
                rec,
                f"正在识别第 {index + 1}/{total} 部：《{pname}》…",
                index,
                total,
            )
            self._add_task()

            def _on_success(_ok, pid=pid, index=index, rec=rec, t0=item_started_at):
                self._remove_task()
                elapsed = time.perf_counter() - t0
                rec.transcribe_time = elapsed
                rec.transcribe_status = "done"
                self._update_status(pid, "transcribe", DramaStatus.DONE)
                results["success"] += 1
                self.batchExecutionUpdated.emit(
                    rec,
                    f"《{rec.project_name}》识别完成（耗时 {elapsed:.1f}s）",
                    index + 1,
                    total,
                )
                _run_at(index + 1)

            def _on_error(msg, pid=pid, pname=pname, index=index, rec=rec, t0=item_started_at):
                self._remove_task()
                elapsed = time.perf_counter() - t0
                rec.transcribe_time = elapsed
                if self._batch_cancel_requested or "取消" in str(msg):
                    rec.transcribe_status = "cancelled"
                    rec.error_msg = "已取消"
                    self._update_status(pid, "transcribe", DramaStatus.PENDING)
                    _run_at(index)
                    return
                rec.transcribe_status = "failed"
                rec.error_msg = sanitize_transcribe_error(msg, drama_name=pname)
                self._update_status(pid, "transcribe", DramaStatus.PENDING)
                results["fail"] += 1
                self.errorOccurred.emit(rec.error_msg)
                self.batchExecutionUpdated.emit(
                    rec,
                    f"《{rec.project_name}》识别失败",
                    index + 1,
                    total,
                )
                _run_at(index + 1)

            task_manager.submit_task(
                lambda p=project: TranscriptionService.transcribe(
                    p, should_cancel=lambda: self._batch_cancel_requested
                ),
                on_success=_on_success,
                on_error=_on_error,
            )

        _run_at(0)

    def batch_plan(self, project_ids: list[str]):
        queue: list[DramaProject] = []
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
            queue.append(project)

        if not queue:
            self.messageReceived.emit("没有符合条件的项目可执行策划")
            return

        results = {"success": 0, "fail": 0}
        total = len(queue)
        records = [
            DramaTimingRecord(
                project_id=p.id,
                project_name=p.name,
                episode_count=p.episode_count,
            )
            for p in queue
        ]
        summary = BatchExecutionSummary(task_type="plan", records=records)
        self._current_batch_summary = summary
        self._batch_cancel_requested = False
        batch_started_at = time.perf_counter()
        self.batchExecutionStarted.emit(summary)

        def _run_at(index: int) -> None:
            if self._batch_cancel_requested:
                for i in range(index, total):
                    records[i].plan_status = "cancelled"
                summary.is_cancelled = True
                summary.total_elapsed = time.perf_counter() - batch_started_at
                self.batchExecutionFinished.emit(summary)
                self.messageReceived.emit("批量策划已取消")
                self._finish_loading_if_idle()
                return

            if index >= total:
                summary.total_elapsed = time.perf_counter() - batch_started_at
                self.batchExecutionFinished.emit(summary)
                self._emit_batch_summary("批量策划完成", results, skipped)
                self._finish_loading_if_idle()
                return

            project = queue[index]
            rec = records[index]
            pid = project.id
            pname = project.name

            if not self._ensure_can_plan(pname):
                rec.plan_status = "skipped"
                rec.error_msg = "策划配额不足"
                self.batchExecutionUpdated.emit(
                    rec,
                    f"《{pname}》配额不足，跳过策划",
                    index + 1,
                    total,
                )
                _run_at(index + 1)
                return

            rec.plan_status = "in_progress"
            item_started_at = time.perf_counter()
            self._update_status(pid, "plan", DramaStatus.IN_PROGRESS)
            self._show_progress(
                "正在策划",
                pname,
                project_id=pid,
                index=index + 1,
                total=total,
            )
            self.batchExecutionUpdated.emit(
                rec,
                f"正在策划第 {index + 1}/{total} 部：《{pname}》…",
                index,
                total,
            )
            self._add_task()
            plan_handler = self._make_plan_progress_handler(pid)

            def _on_success(result, pid=pid, pname=pname, index=index, rec=rec, t0=item_started_at):
                self._remove_task()
                elapsed = time.perf_counter() - t0
                rec.plan_time = elapsed
                rec.plan_status = "done"
                self._update_status(pid, "plan", DramaStatus.DONE)
                UsageService.report("plan")
                self._report_plan_done(pname)
                results["success"] += 1
                self.messageReceived.emit(_format_plan_result_message(pname, result))
                self.batchExecutionUpdated.emit(
                    rec,
                    f"《{rec.project_name}》策划完成（耗时 {elapsed:.1f}s）",
                    index + 1,
                    total,
                )
                _run_at(index + 1)

            def _on_error(msg, pid=pid, pname=pname, index=index, rec=rec, t0=item_started_at):
                self._remove_task()
                elapsed = time.perf_counter() - t0
                rec.plan_time = elapsed
                if self._batch_cancel_requested or "取消" in str(msg):
                    rec.plan_status = "cancelled"
                    rec.error_msg = "已取消"
                    self._update_status(pid, "plan", DramaStatus.PENDING)
                    _run_at(index)
                    return
                rec.plan_status = "failed"
                rec.error_msg = sanitize_plan_error(msg, drama_name=pname)
                self._update_status(pid, "plan", DramaStatus.PENDING)
                results["fail"] += 1
                self.errorOccurred.emit(rec.error_msg)
                self.batchExecutionUpdated.emit(
                    rec,
                    f"《{rec.project_name}》策划失败",
                    index + 1,
                    total,
                )
                _run_at(index + 1)

            task_manager.submit_task(
                lambda p=project, h=plan_handler: AIDirectorService.plan(
                    p, progress_callback=h, should_cancel=lambda: self._batch_cancel_requested
                ),
                on_success=_on_success,
                on_error=_on_error,
            )

        _run_at(0)

    def batch_render(self, project_ids: list[str]):
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

        results = {"success": 0, "fail": 0}
        total = len(valid)
        records = [
            DramaTimingRecord(
                project_id=p.id,
                project_name=p.name,
                episode_count=p.episode_count,
            )
            for p in valid
        ]
        summary = BatchExecutionSummary(task_type="render", records=records)
        self._current_batch_summary = summary
        self._batch_cancel_requested = False
        batch_started_at = time.perf_counter()
        self.batchExecutionStarted.emit(summary)

        def _run_at(index: int) -> None:
            if self._batch_cancel_requested:
                for i in range(index, total):
                    records[i].render_status = "cancelled"
                summary.is_cancelled = True
                summary.total_elapsed = time.perf_counter() - batch_started_at
                self.batchExecutionFinished.emit(summary)
                self.messageReceived.emit("批量渲染已取消")
                self._finish_loading_if_idle()
                return

            if index >= total:
                summary.total_elapsed = time.perf_counter() - batch_started_at
                self.batchExecutionFinished.emit(summary)
                root = resolve_clip_export_root()
                self._emit_batch_summary(
                    f"批量渲染完成（导出目录：{root}）", results, skipped
                )
                self._finish_loading_if_idle()
                return

            project = valid[index]
            rec = records[index]
            pid = project.id
            pname = project.name

            if not self._ensure_can_clip(pname):
                rec.render_status = "skipped"
                rec.error_msg = "剪辑次数不足或未授权"
                self.batchExecutionUpdated.emit(
                    rec,
                    f"《{pname}》未获剪辑授权，跳过渲染",
                    index + 1,
                    total,
                )
                _run_at(index + 1)
                return

            rec.render_status = "in_progress"
            item_started_at = time.perf_counter()
            self._update_status(pid, "render", DramaStatus.IN_PROGRESS)
            self._show_progress(
                "正在渲染",
                pname,
                project_id=pid,
                index=index + 1,
                total=total,
            )
            self.batchExecutionUpdated.emit(
                rec,
                f"正在渲染第 {index + 1}/{total} 部：《{pname}》…",
                index,
                total,
            )
            self._add_task()

            def _on_success(result: RenderResult, pid=pid, pname=pname, index=index, rec=rec, t0=item_started_at):
                self._remove_task()
                elapsed = (
                    result.total_seconds
                    if getattr(result, "total_seconds", 0) > 0
                    else (time.perf_counter() - t0)
                )
                rec.render_time = elapsed
                rec.render_status = "done"
                self._update_status(pid, "render", DramaStatus.DONE)
                results["success"] += 1
                self._report_clip_done(pname)
                self.batchExecutionUpdated.emit(
                    rec,
                    f"《{rec.project_name}》渲染完成（耗时 {elapsed:.1f}s）",
                    index + 1,
                    total,
                )
                _run_at(index + 1)

            def _on_error(msg, pid=pid, pname=pname, index=index, rec=rec, t0=item_started_at):
                self._remove_task()
                elapsed = time.perf_counter() - t0
                rec.render_time = elapsed
                if self._is_render_cancelled(msg) or self._batch_cancel_requested:
                    rec.render_status = "cancelled"
                    rec.error_msg = "已取消"
                    self._update_status(pid, "render", DramaStatus.PENDING)
                    _run_at(index)
                    return
                rec.render_status = "failed"
                rec.error_msg = sanitize_render_error(msg, drama_name=pname)
                self.errorOccurred.emit(rec.error_msg)
                self._update_status(pid, "render", DramaStatus.PENDING)
                results["fail"] += 1
                self.batchExecutionUpdated.emit(
                    rec,
                    f"《{rec.project_name}》渲染失败",
                    index + 1,
                    total,
                )
                _run_at(index + 1)

            self._submit_render(
                project,
                on_success=_on_success,
                on_error=_on_error,
                index=index + 1,
                total=total,
            )

        _run_at(0)

    def _emit_batch_summary(self, prefix: str, results: dict, skipped: int):
        parts = [f"{prefix}：成功 {results['success']} 个"]
        if results["fail"]:
            parts.append(f"失败 {results['fail']} 个")
        if skipped:
            parts.append(f"跳过 {skipped} 个")
        self.messageReceived.emit("，".join(parts))

    def batch_all(self, project_ids: list[str]):
        queue: list[DramaProject] = []
        for pid in project_ids:
            project = next((p for p in self._projects if p.id == pid), None)
            if project:
                queue.append(project)

        if not queue:
            self.messageReceived.emit("没有符合条件的项目可执行一键流程")
            return

        total = len(queue)
        records = [
            DramaTimingRecord(
                project_id=p.id,
                project_name=p.name,
                episode_count=p.episode_count,
            )
            for p in queue
        ]
        summary = BatchExecutionSummary(task_type="all", records=records)
        self._current_batch_summary = summary
        self._batch_cancel_requested = False
        batch_started_at = time.perf_counter()
        self.batchExecutionStarted.emit(summary)

        def _run_next(index: int) -> None:
            if self._batch_cancel_requested:
                for i in range(index, total):
                    r = records[i]
                    if r.transcribe_status == "pending":
                        r.transcribe_status = "cancelled"
                    if r.plan_status == "pending":
                        r.plan_status = "cancelled"
                    if r.render_status == "pending":
                        r.render_status = "cancelled"
                summary.is_cancelled = True
                summary.total_elapsed = time.perf_counter() - batch_started_at
                self.batchExecutionFinished.emit(summary)
                self.messageReceived.emit("一键执行已取消")
                self._finish_loading_if_idle()
                return

            if index >= total:
                summary.total_elapsed = time.perf_counter() - batch_started_at
                self.batchExecutionFinished.emit(summary)
                root = resolve_clip_export_root()
                self.messageReceived.emit(
                    f"一键执行全部完成！成功 {summary.success_count}/{total} 部，"
                    f"总耗时 {self._format_elapsed(summary.total_elapsed)}（导出目录：{root}）"
                )
                self._finish_loading_if_idle()
                return

            project = queue[index]
            rec = records[index]
            pid = project.id
            pname = project.name

            # --- Stage 1: 识别 ---
            rec.transcribe_status = "in_progress"
            self._update_status(pid, "transcribe", DramaStatus.IN_PROGRESS)
            self._show_progress("正在识别", pname, index=index + 1, total=total)
            self.batchExecutionUpdated.emit(
                rec,
                f"一键执行 (1/3 阶段：识别) · 正在识别第 {index + 1}/{total} 部：《{pname}》…",
                index,
                total,
            )
            self._add_task()
            t_trans_start = time.perf_counter()

            def step1():
                TranscriptionService.transcribe(
                    project,
                    should_cancel=lambda: self._batch_cancel_requested,
                )
                return True

            def step1_done(_ok):
                self._remove_task()
                rec.transcribe_time = time.perf_counter() - t_trans_start
                rec.transcribe_status = "done"
                self._update_status(pid, "transcribe", DramaStatus.DONE)
                UsageService.report("batch_all_transcribe")
                self.batchExecutionUpdated.emit(
                    rec,
                    f"《{pname}》识别完成（{rec.transcribe_time:.1f}s）",
                    index,
                    total,
                )

                if self._batch_cancel_requested:
                    _run_next(index + 1)
                    return

                # --- Stage 2: 策划 ---
                rec.plan_status = "in_progress"
                self._update_status(pid, "plan", DramaStatus.IN_PROGRESS)
                self._show_progress(
                    "正在策划",
                    pname,
                    project_id=pid,
                    index=index + 1,
                    total=total,
                )
                self.batchExecutionUpdated.emit(
                    rec,
                    f"一键执行 (2/3 阶段：策划) · 正在策划第 {index + 1}/{total} 部：《{pname}》…",
                    index,
                    total,
                )
                self._add_task()
                t_plan_start = time.perf_counter()
                plan_handler = self._make_plan_progress_handler(pid)

                def step2():
                    return AIDirectorService.plan(
                        project,
                        progress_callback=plan_handler,
                        should_cancel=lambda: self._batch_cancel_requested,
                    )

                def step2_done(plan_res):
                    self._remove_task()
                    rec.plan_time = time.perf_counter() - t_plan_start
                    rec.plan_status = "done"
                    self._update_status(pid, "plan", DramaStatus.DONE)
                    UsageService.report("batch_all_plan")
                    self._report_plan_done(pname)
                    self.batchExecutionUpdated.emit(
                        rec,
                        f"《{pname}》策划完成（{rec.plan_time:.1f}s）",
                        index,
                        total,
                    )

                    if self._batch_cancel_requested:
                        _run_next(index + 1)
                        return

                    if not self._ensure_can_clip(pname):
                        rec.render_status = "skipped"
                        rec.error_msg = "剪辑次数不足或未授权"
                        self.batchExecutionUpdated.emit(
                            rec,
                            f"《{pname}》未获剪辑授权，跳过渲染",
                            index + 1,
                            total,
                        )
                        _run_next(index + 1)
                        return

                    # --- Stage 3: 渲染 ---
                    rec.render_status = "in_progress"
                    self._update_status(pid, "render", DramaStatus.IN_PROGRESS)
                    self._show_progress(
                        "正在渲染",
                        pname,
                        project_id=pid,
                        index=index + 1,
                        total=total,
                    )
                    self.batchExecutionUpdated.emit(
                        rec,
                        f"一键执行 (3/3 阶段：渲染) · 正在渲染第 {index + 1}/{total} 部：《{pname}》…",
                        index,
                        total,
                    )
                    self._add_task()
                    t_render_start = time.perf_counter()

                    def step3_done(render_res: RenderResult):
                        self._remove_task()
                        rec.render_time = (
                            render_res.total_seconds
                            if getattr(render_res, "total_seconds", 0) > 0
                            else (time.perf_counter() - t_render_start)
                        )
                        rec.render_status = "done"
                        self._update_status(pid, "render", DramaStatus.DONE)
                        UsageService.report("batch_all_render", success=render_res.success_count > 0)
                        self._report_clip_done(pname)
                        self.batchExecutionUpdated.emit(
                            rec,
                            f"《{pname}》一键执行完成（总耗时 {rec.total_time:.1f}s）",
                            index + 1,
                            total,
                        )
                        _run_next(index + 1)

                    def step3_err(msg):
                        self._remove_task()
                        rec.render_time = time.perf_counter() - t_render_start
                        if self._is_render_cancelled(msg) or self._batch_cancel_requested:
                            rec.render_status = "cancelled"
                            rec.error_msg = "已取消"
                            self._update_status(pid, "render", DramaStatus.PENDING)
                            _run_next(index)
                            return
                        rec.render_status = "failed"
                        rec.error_msg = sanitize_render_error(msg, drama_name=pname)
                        self.errorOccurred.emit(rec.error_msg)
                        self._update_status(pid, "render", DramaStatus.PENDING)
                        self.batchExecutionUpdated.emit(
                            rec,
                            f"《{pname}》渲染失败",
                            index + 1,
                            total,
                        )
                        _run_next(index + 1)

                    self._submit_render(
                        project,
                        on_success=step3_done,
                        on_error=step3_err,
                        index=index + 1,
                        total=total,
                    )

                def step2_err(msg):
                    self._remove_task()
                    rec.plan_time = time.perf_counter() - t_plan_start
                    if self._batch_cancel_requested or "取消" in str(msg):
                        rec.plan_status = "cancelled"
                        rec.render_status = "cancelled"
                        rec.error_msg = "已取消"
                        self._update_status(pid, "plan", DramaStatus.PENDING)
                        _run_next(index)
                        return
                    rec.plan_status = "failed"
                    rec.render_status = "skipped"
                    rec.error_msg = sanitize_plan_error(msg, drama_name=pname)
                    self._update_status(pid, "plan", DramaStatus.PENDING)
                    self.errorOccurred.emit(rec.error_msg)
                    self.batchExecutionUpdated.emit(
                        rec,
                        f"《{pname}》策划失败，跳过渲染",
                        index + 1,
                        total,
                    )
                    _run_next(index + 1)

                task_manager.submit_task(step2, on_success=step2_done, on_error=step2_err)

            def step1_err(msg):
                self._remove_task()
                rec.transcribe_time = time.perf_counter() - t_trans_start
                if self._batch_cancel_requested or "取消" in str(msg):
                    rec.transcribe_status = "cancelled"
                    rec.plan_status = "cancelled"
                    rec.render_status = "cancelled"
                    rec.error_msg = "已取消"
                    self._update_status(pid, "transcribe", DramaStatus.PENDING)
                    _run_next(index)
                    return
                rec.transcribe_status = "failed"
                rec.plan_status = "skipped"
                rec.render_status = "skipped"
                rec.error_msg = sanitize_transcribe_error(msg, drama_name=pname)
                self._update_status(pid, "transcribe", DramaStatus.PENDING)
                self.errorOccurred.emit(rec.error_msg)
                self.batchExecutionUpdated.emit(
                    rec,
                    f"《{pname}》识别失败，跳过后续步骤",
                    index + 1,
                    total,
                )
                _run_next(index + 1)

            task_manager.submit_task(step1, on_success=step1_done, on_error=step1_err)

        _run_next(0)

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

    def import_and_run_clip_pipeline(
        self,
        folder_paths: list[str],
        *,
        run_plan: bool = True,
        run_render: bool = True,
    ) -> int:
        """从下载页导入已识别剧目，并按需执行策划与渲染。"""
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

        if not run_plan and not run_render:
            self.messageReceived.emit(
                f"已从下载页自动导入 {len(imported_ids)} 个剧目到自动化剪辑"
            )
            return len(imported_ids)

        total = len(imported_ids)
        for index, pid in enumerate(imported_ids, 1):
            project = next((p for p in self._projects if p.id == pid), None)
            if not project:
                continue
            if run_plan:
                self._run_pipeline_after_transcribe(
                    project,
                    index=index,
                    total=total,
                    run_render=run_render,
                )
            elif run_render:
                self._run_render_only(project, index=index, total=total)

        if run_plan and run_render:
            hint = "正在执行策划与渲染…"
        elif run_plan:
            hint = "正在执行策划…"
        else:
            hint = "正在执行渲染…"
        self.messageReceived.emit(
            f"已从下载页自动导入 {len(imported_ids)} 个剧目，{hint}"
        )
        return len(imported_ids)

    def _run_pipeline_after_transcribe(
        self,
        project: DramaProject,
        *,
        index: int = 1,
        total: int = 1,
        run_render: bool = True,
    ):
        pid = project.id
        pname = project.name
        self._update_status(pid, "transcribe", DramaStatus.DONE)
        if not self._ensure_can_plan(pname):
            return

        def step2():
            return AIDirectorService.plan(
                project,
                progress_callback=self._make_plan_progress_handler(pid),
            )

        def step2_done(result):
            self._update_status(pid, "plan", DramaStatus.DONE)
            UsageService.report("batch_all_plan")
            self._report_plan_done(pname)
            if not run_render:
                self._remove_task()
                self.messageReceived.emit(_format_plan_result_message(pname, result))
                return
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
                self._finish_loading_if_idle()

            def step3_err(msg):
                self._remove_task()
                self._update_status(pid, "render", DramaStatus.PENDING)
                if self._is_render_cancelled(msg):
                    self.messageReceived.emit(f"《{pname}》渲染已取消")
                else:
                    self.errorOccurred.emit(sanitize_render_error(msg, drama_name=pname))
                self._finish_loading_if_idle()

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
            self.errorOccurred.emit(sanitize_plan_error(msg, drama_name=pname))

        self._add_task()
        self._show_progress(
            "正在策划",
            pname,
            project_id=pid,
            index=index,
            total=total,
        )
        self._update_status(pid, "plan", DramaStatus.IN_PROGRESS)
        task_manager.submit_task(step2, on_success=step2_done, on_error=step2_err)

    def _run_render_only(
        self,
        project: DramaProject,
        *,
        index: int = 1,
        total: int = 1,
    ) -> None:
        """策划已完成时仅执行渲染（用于下载页增量策划后的批量收尾）。"""
        from app.common.drama_artifact_paths import locate_production_plan

        pid = project.id
        pname = project.name
        self._update_status(pid, "transcribe", DramaStatus.DONE)
        if not locate_production_plan(project.folder_path):
            self.errorOccurred.emit(f"《{pname}》尚未策划，无法渲染")
            return
        self._update_status(pid, "plan", DramaStatus.DONE)
        if not self._ensure_can_clip(pname):
            self._update_status(pid, "render", DramaStatus.PENDING)
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
            self._finish_loading_if_idle()

        def step3_err(msg):
            self._remove_task()
            self._update_status(pid, "render", DramaStatus.PENDING)
            if self._is_render_cancelled(msg):
                self.messageReceived.emit(f"《{pname}》渲染已取消")
            else:
                self.errorOccurred.emit(sanitize_render_error(msg, drama_name=pname))
            self._finish_loading_if_idle()

        self._add_task()
        logger.debug(
            "提交渲染-only: 《{}》 ({}/{}) folder={}",
            pname,
            index,
            total,
            project.folder_path,
        )
        self._submit_render(
            project,
            on_success=step3_done,
            on_error=step3_err,
            index=index,
            total=total,
        )

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
                return AIDirectorService.plan(
                    project,
                    progress_callback=self._make_plan_progress_handler(pid),
                )

            def step2_done(result):
                self._update_status(pid, "plan", DramaStatus.DONE)
                UsageService.report("batch_all_plan")
                self._report_plan_done(pname)
                if not self._ensure_can_clip(pname):
                    self._remove_task()
                    self.messageReceived.emit(_format_plan_result_message(pname, result))
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
                    self._finish_loading_if_idle()

                def step3_err(msg):
                    self._remove_task()
                    self._update_status(pid, "render", DramaStatus.PENDING)
                    if self._is_render_cancelled(msg):
                        self.messageReceived.emit(f"《{pname}》渲染已取消")
                    else:
                        self.errorOccurred.emit(sanitize_render_error(msg, drama_name=pname))
                    self._finish_loading_if_idle()

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
                self.errorOccurred.emit(sanitize_plan_error(msg, drama_name=pname))

            self._show_progress(
                "正在策划",
                pname,
                project_id=pid,
                index=index,
                total=total,
            )
            self._update_status(pid, "plan", DramaStatus.IN_PROGRESS)
            task_manager.submit_task(step2, on_success=step2_done, on_error=step2_err)

        def step1_err(msg):
            self._remove_task()
            self._update_status(pid, "transcribe", DramaStatus.PENDING)
            self.errorOccurred.emit(sanitize_transcribe_error(msg, drama_name=pname))

        self._add_task()
        self._show_progress("正在识别", pname, index=index, total=total)
        self._update_status(pid, "transcribe", DramaStatus.IN_PROGRESS)
        task_manager.submit_task(step1, on_success=step1_done, on_error=step1_err)
