import sys
import time
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

SERVER_ROOT = Path(__file__).resolve().parents[1]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))


class _FakeSecret:
    deepseek_keys = "sk-test"
    plan_decrypt_key = "abcd" * 16


def test_plan_job_completes_with_mocked_run_plan(monkeypatch):
    from sqlalchemy.pool import StaticPool

    from app.database import Base
    from app.services import plan_jobs

    # 同一 :memory: 库需 StaticPool，否则工作线程看不到建表结果
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    monkeypatch.setattr(plan_jobs, "SessionLocal", TestSession)
    monkeypatch.setattr(
        plan_jobs,
        "ensure_user_secret",
        lambda _db, _uid: _FakeSecret(),
    )
    monkeypatch.setattr(
        plan_jobs,
        "resolve_deepseek_keys",
        lambda _db, _uid: "sk-test",
    )
    monkeypatch.setattr(
        plan_jobs,
        "run_plan",
        lambda **_kwargs: [{"title": "demo", "files_config": {"x": 1}}],
    )

    db = TestSession()
    try:
        job = plan_jobs.create_plan_job(
            db,
            user_id=7,
            payload={"project_name": "demo", "steps": [], "ordered_files": ["1.mp4"]},
        )

        deadline = time.time() + 5
        while time.time() < deadline:
            db.expire_all()
            record = plan_jobs.get_plan_job(db, job.id, 7)
            assert record is not None
            if record.status in {"done", "failed"}:
                break
            time.sleep(0.05)

        db.expire_all()
        record = plan_jobs.get_plan_job(db, job.id, 7)
        assert record is not None
        assert record.status == "done"
        assert record.result is not None
        assert "ciphertext" in record.result
        assert "nonce" in record.result
    finally:
        db.close()


def test_fail_interrupted_jobs_marks_running(monkeypatch):
    from sqlalchemy.pool import StaticPool

    from app.database import Base
    from app.models import PlanJob
    from app.services import plan_jobs

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    monkeypatch.setattr(plan_jobs, "SessionLocal", TestSession)

    db = TestSession()
    try:
        db.add(
            PlanJob(
                id="job1",
                user_id=1,
                status="running",
                progress_json="{}",
                error="",
                result_json="",
            )
        )
        db.commit()
    finally:
        db.close()

    assert plan_jobs.fail_interrupted_jobs() == 1
    db = TestSession()
    try:
        row = db.get(PlanJob, "job1")
        assert row is not None
        assert row.status == "failed"
        assert "服务重启" in row.error
    finally:
        db.close()
