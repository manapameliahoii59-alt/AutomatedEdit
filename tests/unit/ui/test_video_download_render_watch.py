"""下载页自动渲染：策划就绪一部即入队，后完成的不因先渲完的被漏掉。"""

import pytest


@pytest.fixture
def vm(qapp, mocker, tmp_path):
    mocker.patch(
        "app.ui.views.video_download.view_model.VideoDownloadViewModel._load_settings_from_server"
    )
    from app.ui.views.video_download.view_model import VideoDownloadViewModel

    return VideoDownloadViewModel()


def test_render_watch_hands_off_ready_incrementally(vm, mocker, tmp_path):
    a = tmp_path / "剧A"
    b = tmp_path / "剧B"
    a.mkdir()
    b.mkdir()
    key_a = str(a.resolve())
    key_b = str(b.resolve())

    planned = {key_a}  # 仅 A 已有策划

    def fake_locate(folder):
        return folder if folder in planned else None

    mocker.patch(
        "app.common.drama_artifact_paths.locate_production_plan",
        side_effect=fake_locate,
    )
    mocker.patch(
        "app.ui.views.video_download.view_model.QTimer.singleShot",
        lambda *_a, **_k: None,
    )

    handoffs = []
    vm.clipHandoffRequested.connect(
        lambda folders, run_plan, run_render, switch_tab: handoffs.append(
            (list(folders), run_plan, run_render, switch_tab)
        )
    )

    vm._enqueue_render_watch([str(a), str(b)])
    assert len(handoffs) == 1
    assert handoffs[0][0] == [key_a]
    assert handoffs[0][1] is False
    assert handoffs[0][2] is True
    assert key_a in vm._render_submitted_folders
    assert vm._pending_render_folders == [key_b]

    # 模拟：A 已渲完，B 此时才策划完 —— 再次轮询仍应入队 B
    planned.add(key_b)
    vm._try_render_pending_planned()
    assert len(handoffs) == 2
    assert handoffs[1][0] == [key_b]
    assert key_b in vm._render_submitted_folders
    assert vm._pending_render_folders == []
    assert vm._render_poll_active is False


def test_render_watch_does_not_double_submit(vm, mocker, tmp_path):
    a = tmp_path / "剧A"
    a.mkdir()
    key_a = str(a.resolve())
    mocker.patch(
        "app.common.drama_artifact_paths.locate_production_plan",
        return_value=key_a,
    )
    mocker.patch(
        "app.ui.views.video_download.view_model.QTimer.singleShot",
        lambda *_a, **_k: None,
    )
    handoffs = []
    vm.clipHandoffRequested.connect(
        lambda folders, run_plan, run_render, switch_tab: handoffs.append(folders)
    )

    vm._enqueue_render_watch([str(a)])
    vm._enqueue_render_watch([str(a)])
    assert len(handoffs) == 1
    assert handoffs[0] == [key_a]
