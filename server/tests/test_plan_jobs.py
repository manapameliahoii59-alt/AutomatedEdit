import sys
import time
from pathlib import Path

SERVER_ROOT = Path(__file__).resolve().parents[1]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))


class _FakeSecret:
    deepseek_keys = "sk-test"
    plan_decrypt_key = "abcd" * 16


class _FakeDb:
    def __init__(self):
        self.row = _FakeSecret()

    def query(self, *_args):
        return self

    def filter(self, *_args):
        return self

    def first(self):
        return self.row


def test_plan_job_completes_with_mocked_run_plan(monkeypatch):
    from app.services import plan_jobs

    monkeypatch.setattr(
        plan_jobs,
        "ensure_user_secret",
        lambda _db, _uid: _FakeSecret(),
    )
    monkeypatch.setattr(
        plan_jobs,
        "run_plan",
        lambda **_kwargs: [{"title": "demo", "files_config": {"x": 1}}],
    )

    job = plan_jobs.create_plan_job(_FakeDb(), user_id=7, payload={"project_name": "demo", "steps": [], "ordered_files": ["1.mp4"]})

    deadline = time.time() + 5
    while time.time() < deadline:
        record = plan_jobs.get_plan_job(job.id, 7)
        assert record is not None
        if record.status in {"done", "failed"}:
            break
        time.sleep(0.05)

    record = plan_jobs.get_plan_job(job.id, 7)
    assert record.status == "done"
    assert record.result is not None
    assert "ciphertext" in record.result
    assert "nonce" in record.result
