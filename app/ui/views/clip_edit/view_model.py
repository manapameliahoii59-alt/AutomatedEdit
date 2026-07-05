import os
import uuid

from PySide6.QtCore import Signal

from app.core.task_manager import task_manager
from app.core.view_model import ViewModel
from app.data.models.drama_project import DramaProject, DramaStatus
from app.data.services.drama_folder_service import DramaFolderError, scan_drama_folder
from app.data.services.transcription_service import TranscriptionService
from app.data.services.ai_director_service import AIDirectorService
from app.common.export_paths import resolve_clip_export_root
from app.data.services.render_service import RenderService, RenderResult
from app.data.services.usage_service import UsageService


class ClipEditViewModel(ViewModel):
    projectsChanged = Signal(list)
    loadingChanged = Signal(bool)
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

        existing = next(
            (p for p in self._projects if p.folder_path == scan.folder_path), None
        )
        if existing:
            existing.name = scan.name
            existing.episode_count = scan.episode_count
            existing.video_files = scan.video_files
            st = self._ensure_status(existing.id)
            if transcribe_done:
                st["transcribe"] = DramaStatus.DONE
                st["plan"] = DramaStatus.PENDING
                st["render"] = DramaStatus.PENDING
            else:
                st["transcribe"] = DramaStatus.PENDING
                st["plan"] = DramaStatus.PENDING
                st["render"] = DramaStatus.PENDING
            self.projectsChanged.emit(self._projects)
            if emit_message:
                self.messageReceived.emit(f"已更新《{scan.name}》，共 {scan.episode_count} 集。")
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
        if transcribe_done:
            st["transcribe"] = DramaStatus.DONE
        self.projectsChanged.emit(self._projects)
        if emit_message:
            self.messageReceived.emit(f"已导入《{scan.name}》，共 {scan.episode_count} 集。")
        return project

    def _add_task(self):
        self._active_tasks += 1
        if self._active_tasks == 1:
            self.loadingChanged.emit(True)

    def _remove_task(self):
        self._active_tasks -= 1
        if self._active_tasks == 0:
            self.loadingChanged.emit(False)

    def _format_render_message(self, project_name: str, result: RenderResult) -> str:
        if result.success_count == result.total:
            return f"《{project_name}》渲染完成，已保存至：{result.output_dir}"
        failed = result.total - result.success_count
        return (
            f"《{project_name}》渲染完成 {result.success_count}/{result.total} 条，"
            f"失败 {failed} 条，已保存至：{result.output_dir}"
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

        self._update_status(project_id, "plan", DramaStatus.IN_PROGRESS)
        self._add_task()

        def _do():
            AIDirectorService.plan(project)
            return True

        def _on_success(_ok):
            self._remove_task()
            self._update_status(project_id, "plan", DramaStatus.DONE)
            UsageService.report("plan")
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

    def start_render(self, project_id: str):
        project = next((p for p in self._projects if p.id == project_id), None)
        if not project:
            self.errorOccurred.emit("未找到该剧目")
            return

        st = self._ensure_status(project_id)
        if st.get("plan") != DramaStatus.DONE:
            self.messageReceived.emit("请先完成 AI 策划")
            return

        self._update_status(project_id, "render", DramaStatus.IN_PROGRESS)
        self._add_task()

        def _do():
            return RenderService.render(project)

        def _on_success(result: RenderResult):
            self._remove_task()
            self._update_status(project_id, "render", DramaStatus.DONE)
            UsageService.report("render", success=result.success_count > 0)
            self.messageReceived.emit(self._format_render_message(project.name, result))

        def _on_error(msg):
            self._remove_task()
            self._update_status(project_id, "render", DramaStatus.PENDING)
            self.errorOccurred.emit(f"渲染失败：{msg}")

        task_manager.submit_task(
            _do,
            on_success=_on_success,
            on_error=_on_error,
        )

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
        for project in valid:
            self._update_status(project.id, "transcribe", DramaStatus.IN_PROGRESS)
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
        for project in valid:
            self._update_status(project.id, "plan", DramaStatus.IN_PROGRESS)
            self._add_task()

            pid = project.id
            pname = project.name

            def _on_success(_ok, pid=pid, pname=pname):
                self._remove_task()
                self._update_status(pid, "plan", DramaStatus.DONE)
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
        for project in valid:
            self._update_status(project.id, "render", DramaStatus.IN_PROGRESS)
            self._add_task()

            pid = project.id
            pname = project.name

            def _on_success(_result: RenderResult, pid=pid, pname=pname):
                self._remove_task()
                self._update_status(pid, "render", DramaStatus.DONE)
                results["success"] += 1
                if self._active_tasks == 0:
                    root = resolve_clip_export_root()
                    self._emit_batch_summary(
                        f"批量渲染完成（导出目录：{root}）", results, skipped
                    )

            def _on_error(msg, pid=pid, pname=pname):
                self._remove_task()
                self._update_status(pid, "render", DramaStatus.PENDING)
                results["fail"] += 1
                if self._active_tasks == 0:
                    self._emit_batch_summary("批量渲染完成", results, skipped)

            task_manager.submit_task(
                lambda p=project: RenderService.render(p),
                on_success=_on_success,
                on_error=_on_error,
            )

    def _emit_batch_summary(self, prefix: str, results: dict, skipped: int):
        parts = [f"{prefix}：成功 {results['success']} 个"]
        if results["fail"]:
            parts.append(f"失败 {results['fail']} 个")
        if skipped:
            parts.append(f"跳过 {skipped} 个")
        self.messageReceived.emit("，".join(parts))

    def batch_all(self, project_ids: list[str]):
        for pid in project_ids:
            project = next((p for p in self._projects if p.id == pid), None)
            if not project:
                continue
            self._run_pipeline(project)

    def import_drama_folders(self, folder_paths: list[str]) -> int:
        """批量导入剧目文件夹（不自动执行剪辑流程）。"""
        imported = 0
        for folder in folder_paths:
            transcribe_done = os.path.isfile(
                os.path.join(folder, "full_script_data.json")
            )
            project = self.import_drama_folder(
                folder,
                transcribe_done=transcribe_done,
                emit_message=False,
            )
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

        for pid in imported_ids:
            project = next((p for p in self._projects if p.id == pid), None)
            if project:
                self._run_pipeline_after_transcribe(project)

        self.messageReceived.emit(
            f"已从下载页自动导入 {len(imported_ids)} 个剧目，正在执行 AI 策划与渲染…"
        )
        return len(imported_ids)

    def _run_pipeline_after_transcribe(self, project: DramaProject):
        pid = project.id
        pname = project.name
        self._update_status(pid, "transcribe", DramaStatus.DONE)

        def step2():
            AIDirectorService.plan(project)
            return True

        def step2_done(_ok):
            self._update_status(pid, "plan", DramaStatus.DONE)
            UsageService.report("batch_all_plan")

            def step3():
                return RenderService.render(project)

            def step3_done(result: RenderResult):
                self._remove_task()
                self._update_status(pid, "render", DramaStatus.DONE)
                UsageService.report("batch_all_render", success=result.success_count > 0)
                self.messageReceived.emit(
                    f"《{pname}》自动剪辑完成。\n"
                    f"{self._format_render_message(pname, result)}"
                )

            def step3_err(msg):
                self._remove_task()
                self._update_status(pid, "render", DramaStatus.PENDING)
                self.errorOccurred.emit(f"《{pname}》渲染失败：{msg}")

            self._update_status(pid, "render", DramaStatus.IN_PROGRESS)
            task_manager.submit_task(step3, on_success=step3_done, on_error=step3_err)

        def step2_err(msg):
            self._remove_task()
            self._update_status(pid, "plan", DramaStatus.PENDING)
            self.errorOccurred.emit(f"《{pname}》策划失败：{msg}")

        self._add_task()
        self._update_status(pid, "plan", DramaStatus.IN_PROGRESS)
        task_manager.submit_task(step2, on_success=step2_done, on_error=step2_err)

    def _run_pipeline(self, project: DramaProject):
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

                def step3():
                    return RenderService.render(project)

                def step3_done(result: RenderResult):
                    self._remove_task()
                    self._update_status(pid, "render", DramaStatus.DONE)
                    UsageService.report("batch_all_render", success=result.success_count > 0)
                    self.messageReceived.emit(
                        f"《{pname}》一键执行完成。\n"
                        f"{self._format_render_message(pname, result)}"
                    )

                def step3_err(msg):
                    self._remove_task()
                    self._update_status(pid, "render", DramaStatus.PENDING)
                    self.errorOccurred.emit(f"《{pname}》渲染失败：{msg}")

                self._update_status(pid, "render", DramaStatus.IN_PROGRESS)
                task_manager.submit_task(step3, on_success=step3_done, on_error=step3_err)

            def step2_err(msg):
                self._remove_task()
                self._update_status(pid, "plan", DramaStatus.PENDING)
                self.errorOccurred.emit(f"《{pname}》策划失败：{msg}")

            self._update_status(pid, "plan", DramaStatus.IN_PROGRESS)
            task_manager.submit_task(step2, on_success=step2_done, on_error=step2_err)

        def step1_err(msg):
            self._remove_task()
            self._update_status(pid, "transcribe", DramaStatus.PENDING)
            self.errorOccurred.emit(f"《{pname}》识别失败：{msg}")

        self._add_task()
        self._update_status(pid, "transcribe", DramaStatus.IN_PROGRESS)
        task_manager.submit_task(step1, on_success=step1_done, on_error=step1_err)
