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

    go_mimo = encode_plan_llm_preset("opencode_go", "mimo-v2.5")
    gp, gm = decode_plan_llm_preset(go_mimo)
    assert gp == "opencode_go"
    assert gm == "mimo-v2.5"
    assert plan_llm_preset_label(gp, gm) == "OpenCode Go / MiMo-V2.5"

    xiaomi = encode_plan_llm_preset("xiaomi", "mimo-v2.5")
    xp, xm = decode_plan_llm_preset(xiaomi)
    assert xp == "xiaomi"
    assert xm == "mimo-v2.5"
    assert "小米 MiMo" in plan_llm_preset_label(xp, xm)

    zhipu = encode_plan_llm_preset("zhipu", "glm-5.3-flash")
    zp, zm = decode_plan_llm_preset(zhipu)
    assert zp == "zhipu"
    assert zm == "glm-5.3-flash"
    assert plan_llm_preset_label(zp, zm) == "智谱 GLM / glm-5.3-flash"

    zhipu_47 = encode_plan_llm_preset("zhipu", "glm-4.7-flash")
    zp47, zm47 = decode_plan_llm_preset(zhipu_47)
    assert zp47 == "zhipu"
    assert zm47 == "glm-4.7-flash"
    assert plan_llm_preset_label(zp47, zm47) == "智谱 GLM / glm-4.7-flash"

    sf_qwen = encode_plan_llm_preset("siliconflow", "Qwen/Qwen3.8-27B")
    sfp1, sfm1 = decode_plan_llm_preset(sf_qwen)
    assert sfp1 == "siliconflow"
    assert sfm1 == "Qwen/Qwen3.8-27B"
    assert plan_llm_preset_label(sfp1, sfm1) == "硅基流动 / Qwen/Qwen3.8-27B"

    sf_v4 = encode_plan_llm_preset("siliconflow", "deepseek-ai/DeepSeek-V4-Flash")
    sfp2, sfm2 = decode_plan_llm_preset(sf_v4)
    assert sfp2 == "siliconflow"
    assert sfm2 == "deepseek-ai/DeepSeek-V4-Flash"
    assert plan_llm_preset_label(sfp2, sfm2) == "硅基流动 / deepseek-ai/DeepSeek-V4-Flash"

    sf_v3 = encode_plan_llm_preset("siliconflow", "deepseek-ai/DeepSeek-V3.2")
    sfp3, sfm3 = decode_plan_llm_preset(sf_v3)
    assert sfp3 == "siliconflow"
    assert sfm3 == "deepseek-ai/DeepSeek-V3.2"
    assert plan_llm_preset_label(sfp3, sfm3) == "硅基流动 / deepseek-ai/DeepSeek-V3.2"

    ty_qwen = encode_plan_llm_preset("tongyi", "qwen3.7-flash")
    typ, tym = decode_plan_llm_preset(ty_qwen)
    assert typ == "tongyi"
    assert tym == "qwen3.7-flash"
    assert plan_llm_preset_label(typ, tym) == "通义千问 / qwen3.7-flash"

    ty_omni = encode_plan_llm_preset("tongyi", "qwen3.8-omni-flash")
    ty_op, ty_om = decode_plan_llm_preset(ty_omni)
    assert ty_op == "tongyi"
    assert ty_om == "qwen3.8-omni-flash"
    assert plan_llm_preset_label(ty_op, ty_om) == "通义千问 / Qwen3.8-Omni-Flash"


def test_plan_llm_preset_deepseek_flash_normalized():
    from app.services.plan_secrets import (
        PLAN_LLM_PRESET_CHOICES,
        decode_plan_llm_preset,
        encode_plan_llm_preset,
        plan_llm_preset_label,
    )

    preset_values = {value for value, _label in PLAN_LLM_PRESET_CHOICES}
    # 官方 DeepSeek flash 统一为 deepseek-flash
    assert "deepseek|deepseek-flash" in preset_values
    assert "deepseek|deepseek-v4-flash" not in preset_values
    assert "deepseek|deepseek-v4.1-flash" not in preset_values
    # OpenCode Go 的 V4.1 flash 选项已移除
    assert "opencode_go|deepseek-v4.1-flash" not in preset_values

    # 历史/旧名自动归一为 deepseek-flash
    for legacy in ("deepseek-v4-flash", "deepseek-v4.1-flash"):
        assert encode_plan_llm_preset("deepseek", legacy) == (
            "deepseek|deepseek-flash"
        )
        provider, model = decode_plan_llm_preset(f"deepseek|{legacy}")
        assert provider == "deepseek"
        assert model == "deepseek-flash"

    assert plan_llm_preset_label("deepseek", "deepseek-v4.1-flash") == (
        "官方 DeepSeek / deepseek-flash（V4.1 Flash）"
    )

    # OpenCode Go 的 deepseek-v4-flash 不受影响
    assert encode_plan_llm_preset("opencode_go", "deepseek-v4-flash") == (
        "opencode_go|deepseek-v4-flash"
    )


def test_resolve_plan_llm_config_xiaomi(monkeypatch):
    from app.services.plan_secrets import resolve_plan_llm_config

    class _XiaomiSecret:
        deepseek_keys = "mimo-key"
        plan_decrypt_key = "abcd" * 16
        plan_llm_provider = "xiaomi"
        plan_llm_model = "mimo-v2.5"

    class _Db:
        def query(self, *_args):
            return self

        def filter(self, *_args):
            return self

        def first(self):
            return _XiaomiSecret()

    monkeypatch.setattr(
        "app.services.plan_secrets.settings.xiaomi_mimo_api_url",
        "https://api.xiaomimimo.com/v1/chat/completions",
    )
    cfg = resolve_plan_llm_config(_Db(), 1)
    assert cfg["provider"] == "xiaomi"
    assert cfg["model"] == "mimo-v2.5"
    assert cfg["keys"] == "mimo-key"
    assert "xiaomimimo.com" in cfg["api_url"]


def test_resolve_plan_llm_config_zhipu(monkeypatch):
    from app.services.plan_secrets import resolve_plan_llm_config

    class _ZhipuSecret:
        deepseek_keys = "zhipu-key"
        plan_decrypt_key = "abcd" * 16
        plan_llm_provider = "zhipu"
        plan_llm_model = ""

    class _Db:
        def query(self, *_args):
            return self

        def filter(self, *_args):
            return self

        def first(self):
            return _ZhipuSecret()

    monkeypatch.setattr(
        "app.services.plan_secrets.settings.zhipu_api_url",
        "https://open.bigmodel.cn/api/paas/v4/chat/completions",
    )
    cfg = resolve_plan_llm_config(_Db(), 1)
    assert cfg["provider"] == "zhipu"
    assert cfg["model"] == "glm-5.3-flash"  # 空 model 回落通道默认
    assert cfg["keys"] == "zhipu-key"
    assert "bigmodel.cn" in cfg["api_url"]
    assert cfg["thinking_enabled"] is False

    _ZhipuSecret.plan_thinking_enabled = True
    cfg_on = resolve_plan_llm_config(_Db(), 1)
    assert cfg_on["thinking_enabled"] is True



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

    content3, _e3, err3 = plan_director._call_deepseek(
        api_url="https://api.xiaomimimo.com/v1/chat/completions",
        model_name="mimo-v2.5",
        compressed_script="x",
        count=1,
        group_type="U",
        key_pool=pool,
        min_duration_seconds=150,
        max_duration_seconds=300,
        plan_mode="long",
        provider="xiaomi",
        llm_session_id="",
    )
    assert err3 is None
    assert content3 == "{}"
    assert captured["json"]["model"] == "mimo-v2.5"
    assert captured["json"].get("thinking") == {"type": "disabled"}
    assert captured["headers"].get("api-key") == "sk-x"
    assert "x-opencode-session" not in captured["headers"]

    content4, _e4, err4 = plan_director._call_deepseek(
        api_url="https://open.bigmodel.cn/api/paas/v4/chat/completions",
        model_name="glm-5.3-flash",
        compressed_script="x",
        count=1,
        group_type="U",
        key_pool=pool,
        min_duration_seconds=150,
        max_duration_seconds=300,
        plan_mode="long",
        provider="zhipu",
        llm_session_id="",
    )
    assert err4 is None
    assert content4 == "{}"
    assert captured["json"]["model"] == "glm-5.3-flash"
    # 智谱 GLM-5.3-flash 始终思考，不支持 disabled：显式开启并压低推理档位
    assert captured["json"].get("thinking") == {"type": "enabled"}
    assert captured["json"].get("reasoning_effort") == "low"
    # 智谱走标准 Bearer 认证，无特殊请求头
    assert captured["headers"].get("Authorization") == "Bearer sk-x"
    assert "api-key" not in captured["headers"]
    assert "x-opencode-session" not in captured["headers"]

    content5, _e5, err5 = plan_director._call_deepseek(
        api_url="https://open.bigmodel.cn/api/paas/v4/chat/completions",
        model_name="glm-4.7-flash",
        compressed_script="x",
        count=1,
        group_type="U",
        key_pool=pool,
        min_duration_seconds=150,
        max_duration_seconds=300,
        plan_mode="long",
        provider="zhipu",
        llm_session_id="",
        thinking_enabled=False,
    )
    assert err5 is None
    # 智谱旧型号默认关闭思考
    assert captured["json"].get("thinking") == {"type": "disabled"}
    assert "reasoning_effort" not in captured["json"]

    # 智谱 GLM-4.7-flash: 显式开启思考
    content6, _e6, err6 = plan_director._call_deepseek(
        api_url="https://open.bigmodel.cn/api/paas/v4/chat/completions",
        model_name="glm-4.7-flash",
        compressed_script="x",
        count=1,
        group_type="U",
        key_pool=pool,
        min_duration_seconds=150,
        max_duration_seconds=300,
        plan_mode="long",
        provider="zhipu",
        llm_session_id="",
        thinking_enabled=True,
    )
    assert err6 is None
    assert captured["json"].get("thinking") == {"type": "enabled"}

    # 智谱 GLM-5.3-flash: 即使用户关闭思考，也强制开启并压低档位（因为 API 强制要求）
    content7, _e7, err7 = plan_director._call_deepseek(
        api_url="https://open.bigmodel.cn/api/paas/v4/chat/completions",
        model_name="glm-5.3-flash",
        compressed_script="x",
        count=1,
        group_type="U",
        key_pool=pool,
        min_duration_seconds=150,
        max_duration_seconds=300,
        plan_mode="long",
        provider="zhipu",
        llm_session_id="",
        thinking_enabled=False,
    )
    assert err7 is None
    assert captured["json"].get("thinking") == {"type": "enabled"}
    assert captured["json"].get("reasoning_effort") == "low"

    # 硅基流动: 默认不传 thinking，开启时传 enabled
    content8, _e8, err8 = plan_director._call_deepseek(
        api_url="https://api.siliconflow.cn/v1/chat/completions",
        model_name="Qwen/Qwen3.8-27B",
        compressed_script="x",
        count=1,
        group_type="U",
        key_pool=pool,
        min_duration_seconds=150,
        max_duration_seconds=300,
        plan_mode="long",
        provider="siliconflow",
        llm_session_id="",
        thinking_enabled=False,
    )
    assert err8 is None
    assert "thinking" not in captured["json"]
    assert captured["headers"]["Authorization"] == "Bearer sk-x"

    content9, _e9, err9 = plan_director._call_deepseek(
        api_url="https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        model_name="qwen3.7-flash",
        compressed_script="x",
        count=1,
        group_type="U",
        key_pool=pool,
        min_duration_seconds=150,
        max_duration_seconds=300,
        plan_mode="long",
        provider="tongyi",
        llm_session_id="",
        thinking_enabled=True,
    )
    assert err9 is None
    assert captured["json"].get("thinking") == {"type": "enabled"}
    assert captured["json"].get("enable_thinking") is True
    assert captured["headers"]["Authorization"] == "Bearer sk-x"

    content10, _e10, err10 = plan_director._call_deepseek(
        api_url="https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        model_name="qwen3.8-omni-flash",
        compressed_script="x",
        count=1,
        group_type="U",
        key_pool=pool,
        min_duration_seconds=150,
        max_duration_seconds=300,
        plan_mode="long",
        provider="tongyi",
        llm_session_id="",
        thinking_enabled=False,
    )
    assert err10 is None
    assert captured["json"].get("thinking") == {"type": "disabled"}
    assert captured["json"].get("enable_thinking") is False
    assert captured["json"].get("modalities") == ["text"]
    assert captured["headers"]["Authorization"] == "Bearer sk-x"


def test_resolve_plan_llm_config_siliconflow_and_tongyi(monkeypatch):
    from app.services.plan_secrets import (
        normalize_plan_llm_provider,
        normalize_plan_llm_model,
        default_api_url_for_provider,
        resolve_plan_llm_config,
    )

    # 别名归一化
    assert normalize_plan_llm_provider("siliconflow") == "siliconflow"
    assert normalize_plan_llm_provider("silicon") == "siliconflow"
    assert normalize_plan_llm_provider("sf") == "siliconflow"
    assert normalize_plan_llm_provider("tongyi") == "tongyi"
    assert normalize_plan_llm_provider("qwen") == "tongyi"
    assert normalize_plan_llm_provider("dashscope") == "tongyi"
    assert normalize_plan_llm_provider("aliyun") == "tongyi"

    # 默认模型与 URL
    assert "siliconflow.cn" in default_api_url_for_provider("siliconflow")
    assert "dashscope.aliyuncs.com" in default_api_url_for_provider("tongyi")
    assert normalize_plan_llm_model("", provider="siliconflow") == "deepseek-ai/DeepSeek-V4-Flash"
    assert normalize_plan_llm_model("", provider="tongyi") == "qwen3.7-flash"
    assert normalize_plan_llm_model("Qwen/Qwen3.8-27B", provider="siliconflow") == "Qwen/Qwen3.8-27B"
    assert normalize_plan_llm_model("deepseek-ai/DeepSeek-V3.2", provider="siliconflow") == "deepseek-ai/DeepSeek-V3.2"

    class _MockSFSecret:
        plan_decrypt_key = "abc"
        plan_llm_provider = "siliconflow"
        plan_llm_model = "Qwen/Qwen3.8-27B"
        deepseek_keys = "sf-key-123"
        dashscope_key = ""
        plan_thinking_enabled = False

    class _MockDbSF:
        def query(self, *_args):
            return self
        def filter(self, *_args):
            return self
        def first(self):
            return _MockSFSecret()

    cfg_sf = resolve_plan_llm_config(_MockDbSF(), 1)
    assert cfg_sf["provider"] == "siliconflow"
    assert cfg_sf["model"] == "Qwen/Qwen3.8-27B"
    assert cfg_sf["keys"] == "sf-key-123"
    assert "siliconflow.cn" in cfg_sf["api_url"]

    # 通义千问：deepseek_keys 为空时回退到 dashscope_key
    class _MockTYSecret:
        plan_decrypt_key = "abc"
        plan_llm_provider = "tongyi"
        plan_llm_model = "qwen3.7-flash"
        deepseek_keys = ""
        dashscope_key = "ds-fallback-key"
        plan_thinking_enabled = True

    class _MockDbTY:
        def query(self, *_args):
            return self
        def filter(self, *_args):
            return self
        def first(self):
            return _MockTYSecret()

    cfg_ty = resolve_plan_llm_config(_MockDbTY(), 2)
    assert cfg_ty["provider"] == "tongyi"
    assert cfg_ty["model"] == "qwen3.7-flash"
    assert cfg_ty["keys"] == "ds-fallback-key"
    assert cfg_ty["thinking_enabled"] is True
    assert "dashscope.aliyuncs.com" in cfg_ty["api_url"]

    # 通义千问：环境变量 DASHSCOPE_API_KEY 回退与 omni 模型 modalities 校验
    import os
    import queue
    from unittest.mock import patch
    from app.services import plan_director

    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-env-dashscope-123")

    class _MockTYSecretEnv:
        plan_decrypt_key = "abc"
        plan_llm_provider = "tongyi"
        plan_llm_model = "qwen3.8-omni-flash"
        deepseek_keys = ""
        dashscope_key = ""
        plan_thinking_enabled = False

    class _MockDbTYEnv:
        def query(self, *_args):
            return self
        def filter(self, *_args):
            return self
        def first(self):
            return _MockTYSecretEnv()

    cfg_omni = resolve_plan_llm_config(_MockDbTYEnv(), 3)
    assert cfg_omni["model"] == "qwen3.8-omni-flash"
    assert cfg_omni["keys"] == "sk-env-dashscope-123"

    # 验证调用 _call_deepseek 时自动带上 modalities=["text"]
    captured_omni: dict = {}
    def _fake_client_post_omni(_self, url, headers=None, json=None):
        captured_omni["url"] = url
        captured_omni["headers"] = headers
        captured_omni["json"] = json
        class _R:
            status_code = 200
            def json(self):
                return {"choices": [{"message": {"content": '{"starts":[],"ends":[]}'}}]}
        return _R()

    omni_pool = queue.Queue()
    omni_pool.put("sk-omni-key")
    with patch("httpx.Client.post", _fake_client_post_omni):
        content, _elapsed, err = plan_director._call_deepseek(
            api_url="https://maas.qianwenaiapi.com/compatible-mode/v1/chat/completions",
            model_name="qwen3.8-omni-flash",
            compressed_script="script_text",
            count=1,
            group_type="A",
            key_pool=omni_pool,
            min_duration_seconds=60,
            max_duration_seconds=120,
            provider="tongyi",
        )
    assert err is None
    assert captured_omni["json"].get("modalities") == ["text"]
    assert captured_omni["json"].get("model") == "qwen3.8-omni-flash"
    assert captured_omni["headers"]["Authorization"] == "Bearer sk-omni-key"


