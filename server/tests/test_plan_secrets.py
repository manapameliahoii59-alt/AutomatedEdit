import sys
from pathlib import Path

SERVER_ROOT = Path(__file__).resolve().parents[1]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))


class _FakeSecret:
    deepseek_keys = "sk-user-key"
    plan_decrypt_key = "abcd" * 16


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

    class _Db:
        def query(self, *_args):
            return self

        def filter(self, *_args):
            return self

        def first(self):
            return _EmptySecret()

    monkeypatch.setattr("app.services.plan_secrets.settings.deepseek_api_keys", "sk-env-key")
    assert resolve_deepseek_keys(_Db(), 1) == "sk-env-key"
