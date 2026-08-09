import queue
import sys
from pathlib import Path

SERVER_ROOT = Path(__file__).resolve().parents[1]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))


class _FakeSecret:
    deepseek_keys = "sk-user-key"
    plan_decrypt_key = "abcd" * 16
    plan_llm_provider = "deepseek"
    plan_llm_model = ""


class _FakeDb:
    def query(self, *_args):
        return self

    def filter(self, *_args):
        return self

    def first(self):
        return _FakeSecret()


def test_resolve_deepseek_keys_prefers_user_secret(monkeypatch):
    from app.services.plan_secrets import resolve_deepseek_keys

    monkeypatch.setattr("app.services.plan_secrets.settings.deepseek_api_keys", "sk-env-key")
    assert resolve_deepseek_keys(_FakeDb(), 1) == "sk-user-key"


def test_resolve_deepseek_keys_falls_back_to_env(monkeypatch):
    from app.services.plan_secrets import resolve_deepseek_keys

    class _EmptySecret:
        deepseek_keys = ""
        plan_decrypt_key = "abcd" * 16
        plan_llm_provider = "deepseek"
        plan_llm_model = ""

    class _Db:
        def query(self, *_args):
            return self

        def filter(self, *_args):
            return self

        def first(self):
            return _EmptySecret()

    monkeypatch.setattr("app.services.plan_secrets.settings.deepseek_api_keys", "sk-env-key")
    assert resolve_deepseek_keys(_Db(), 1) == "sk-env-key"


def test_resolve_plan_llm_config_opencode_go(monkeypatch):
    from app.services.plan_secrets import resolve_plan_llm_config

    class _GoSecret:
        deepseek_keys = "sk-go-key"
        plan_decrypt_key = "abcd" * 16
        plan_llm_provider = "opencode_go"
        plan_llm_model = "deepseek-v4-pro"

    class _Db:
        def query(self, *_args):
            return self

        def filter(self, *_args):
            return self

        def first(self):
            return _GoSecret()

    monkeypatch.setattr(
        "app.services.plan_secrets.settings.opencode_go_api_url",
        "https://opencode.ai/zen/go/v1/chat/completions",
    )
    cfg = resolve_plan_llm_config(_Db(), 1)
    assert cfg["provider"] == "opencode_go"
    assert cfg["model"] == "deepseek-v4-pro"
    assert cfg["keys"] == "sk-go-key"
    assert "opencode.ai/zen/go" in cfg["api_url"]


def test_plan_llm_preset_roundtrip():
    from app.services.plan_secrets import (
        decode_plan_llm_preset,
        encode_plan_llm_preset,
        plan_llm_preset_label,
    )

    value = encode_plan_llm_preset("opencode_go", "deepseek-v4-flash")
    provider, model = decode_plan_llm_preset(value)
    assert provider == "opencode_go"
    assert model == "deepseek-v4-flash"
    assert "OpenCode Go" in plan_llm_preset_label(provider, model)


def test_call_deepseek_payload_by_provider(monkeypatch):
    from app.services import plan_director

    captured: dict = {}

    class _Resp:
        status_code = 200

        def json(self):
            return {"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}]}

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, headers=None, json=None):
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            return _Resp()

    monkeypatch.setattr(plan_director.httpx, "Client", _Client)
    pool = queue.Queue()
    pool.put("sk-x")

    content, _elapsed, err = plan_director._call_deepseek(
        api_url="https://opencode.ai/zen/go/v1/chat/completions",
        model_name="deepseek-v4-flash",
        compressed_script="x",
        count=1,
        group_type="U",
        key_pool=pool,
        min_duration_seconds=150,
        max_duration_seconds=300,
        plan_mode="short",
        provider="opencode_go",
        llm_session_id="job123",
    )
    assert err is None
    assert content == "{}"
    assert captured["json"].get("thinking") == {"type": "disabled"}
    assert captured["headers"].get("x-opencode-session") == "job123"

    content2, _e2, err2 = plan_director._call_deepseek(
        api_url="https://api.deepseek.com/chat/completions",
        model_name="deepseek-v4-flash",
        compressed_script="x",
        count=1,
        group_type="U",
        key_pool=pool,
        min_duration_seconds=150,
        max_duration_seconds=300,
        plan_mode="long",
        provider="deepseek",
        llm_session_id="",
    )
    assert err2 is None
    assert content2 == "{}"
    assert captured["json"].get("thinking") == {"type": "disabled"}
    assert "x-opencode-session" not in captured["headers"]
