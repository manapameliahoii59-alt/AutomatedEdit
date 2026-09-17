"""用户策划解密密钥与策划 LLM 配置。"""

from __future__ import annotations

from typing import TypedDict

from sqlalchemy.orm import Session

from app.config import settings
from app.models import LlmChannel, LlmGroup, UserSecret
from app.services.plan_crypto import generate_plan_decrypt_key

PLAN_LLM_PROVIDER_DEEPSEEK = "deepseek"
PLAN_LLM_PROVIDER_OPENCODE_GO = "opencode_go"
PLAN_LLM_PROVIDER_XIAOMI = "xiaomi"
PLAN_LLM_PROVIDER_ZHIPU = "zhipu"
PLAN_LLM_PROVIDER_SILICONFLOW = "siliconflow"
PLAN_LLM_PROVIDER_TONGYI = "tongyi"
PLAN_LLM_PROVIDERS = frozenset(
    {
        PLAN_LLM_PROVIDER_DEEPSEEK,
        PLAN_LLM_PROVIDER_OPENCODE_GO,
        PLAN_LLM_PROVIDER_XIAOMI,
        PLAN_LLM_PROVIDER_ZHIPU,
        PLAN_LLM_PROVIDER_SILICONFLOW,
        PLAN_LLM_PROVIDER_TONGYI,
    }
)

# 管理后台下拉：(value, label)；value = provider|model
PLAN_LLM_PRESET_CHOICES: tuple[tuple[str, str], ...] = (
    (
        f"{PLAN_LLM_PROVIDER_DEEPSEEK}|deepseek-flash",
        "官方 DeepSeek / deepseek-flash（V4.1 Flash）",
    ),
    (
        f"{PLAN_LLM_PROVIDER_DEEPSEEK}|deepseek-v4-pro",
        "官方 DeepSeek / deepseek-v4-pro",
    ),
    (
        f"{PLAN_LLM_PROVIDER_OPENCODE_GO}|deepseek-v4-flash",
        "OpenCode Go / deepseek-v4-flash",
    ),
    (
        f"{PLAN_LLM_PROVIDER_OPENCODE_GO}|deepseek-v4-pro",
        "OpenCode Go / deepseek-v4-pro",
    ),
    (
        f"{PLAN_LLM_PROVIDER_OPENCODE_GO}|mimo-v2.5",
        "OpenCode Go / MiMo-V2.5",
    ),
    (
        f"{PLAN_LLM_PROVIDER_XIAOMI}|mimo-v2.5",
        "小米 MiMo / mimo-v2.5",
    ),
    (
        f"{PLAN_LLM_PROVIDER_ZHIPU}|glm-5.3-flash",
        "智谱 GLM / glm-5.3-flash",
    ),
    (
        f"{PLAN_LLM_PROVIDER_ZHIPU}|glm-4.7-flash",
        "智谱 GLM / glm-4.7-flash",
    ),
    (
        f"{PLAN_LLM_PROVIDER_SILICONFLOW}|Qwen/Qwen3.8-27B",
        "硅基流动 / Qwen/Qwen3.8-27B",
    ),
    (
        f"{PLAN_LLM_PROVIDER_SILICONFLOW}|deepseek-ai/DeepSeek-V4-Flash",
        "硅基流动 / deepseek-ai/DeepSeek-V4-Flash",
    ),
    (
        f"{PLAN_LLM_PROVIDER_SILICONFLOW}|deepseek-ai/DeepSeek-V3.2",
        "硅基流动 / deepseek-ai/DeepSeek-V3.2",
    ),
    (
        f"{PLAN_LLM_PROVIDER_TONGYI}|qwen3.7-flash",
        "通义千问 / qwen3.7-flash",
    ),
)
_PLAN_LLM_PRESET_VALUES = {value for value, _label in PLAN_LLM_PRESET_CHOICES}


class PlanLlmConfig(TypedDict):
    provider: str
    api_url: str
    model: str
    keys: str
    thinking_enabled: bool


def ensure_user_secret(db: Session, user_id: int) -> UserSecret:
    row = db.query(UserSecret).filter(UserSecret.user_id == user_id).first()
    if row is None:
        row = UserSecret(
            user_id=user_id,
            plan_decrypt_key=generate_plan_decrypt_key(),
            plan_llm_provider=PLAN_LLM_PROVIDER_DEEPSEEK,
            plan_llm_model="",
            plan_thinking_enabled=False,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row
    if not (row.plan_decrypt_key or "").strip():
        row.plan_decrypt_key = generate_plan_decrypt_key()
        db.commit()
        db.refresh(row)
    return row


def normalize_plan_llm_provider(value: str | None) -> str:
    key = str(value or "").strip().lower()
    if key in ("siliconflow", "silicon", "sf"):
        return PLAN_LLM_PROVIDER_SILICONFLOW
    if key in ("tongyi", "qwen", "dashscope", "aliyun"):
        return PLAN_LLM_PROVIDER_TONGYI
    if key in PLAN_LLM_PROVIDERS:
        return key
    return PLAN_LLM_PROVIDER_DEEPSEEK


# 官方 DeepSeek 通道旧 flash 名称 → 当前可用模型 ID（deepseek-flash）
_DEEPSEEK_FLASH_ALIASES = frozenset({"deepseek-v4-flash", "deepseek-v4.1-flash"})


def normalize_plan_llm_model(value: str | None, *, provider: str) -> str:
    model = str(value or "").strip()
    if model:
        if (
            provider == PLAN_LLM_PROVIDER_DEEPSEEK
            and model in _DEEPSEEK_FLASH_ALIASES
        ):
            return "deepseek-flash"
        return model
    if provider == PLAN_LLM_PROVIDER_OPENCODE_GO:
        return (settings.opencode_go_model or "deepseek-v4-flash").strip()
    if provider == PLAN_LLM_PROVIDER_XIAOMI:
        return (settings.xiaomi_mimo_model or "mimo-v2.5").strip()
    if provider == PLAN_LLM_PROVIDER_ZHIPU:
        return (settings.zhipu_model or "glm-5.3-flash").strip()
    if provider == PLAN_LLM_PROVIDER_SILICONFLOW:
        return (settings.siliconflow_model or "deepseek-ai/DeepSeek-V4-Flash").strip()
    if provider == PLAN_LLM_PROVIDER_TONGYI:
        return (settings.tongyi_model or "qwen3.7-flash").strip()
    return (settings.deepseek_model or "deepseek-flash").strip()


def encode_plan_llm_preset(provider: str, model: str) -> str:
    p = normalize_plan_llm_provider(provider)
    m = normalize_plan_llm_model(model, provider=p)
    value = f"{p}|{m}"
    if value in _PLAN_LLM_PRESET_VALUES:
        return value
    # 自定义模型仍拼成同格式，下拉无匹配时编辑页可回落到默认 flash
    return f"{p}|{m}"


def decode_plan_llm_preset(value: str | None) -> tuple[str, str]:
    text = str(value or "").strip()
    if "|" in text:
        provider, model = text.split("|", 1)
        provider = normalize_plan_llm_provider(provider)
        model = normalize_plan_llm_model(model, provider=provider)
        return provider, model
    return PLAN_LLM_PROVIDER_DEEPSEEK, normalize_plan_llm_model(
        "", provider=PLAN_LLM_PROVIDER_DEEPSEEK
    )


def plan_llm_preset_label(provider: str, model: str) -> str:
    value = encode_plan_llm_preset(provider, model)
    for preset, label in PLAN_LLM_PRESET_CHOICES:
        if preset == value:
            return label
    p = normalize_plan_llm_provider(provider)
    m = normalize_plan_llm_model(model, provider=p)
    if p == PLAN_LLM_PROVIDER_OPENCODE_GO:
        prefix = "OpenCode Go"
    elif p == PLAN_LLM_PROVIDER_XIAOMI:
        prefix = "小米 MiMo"
    elif p == PLAN_LLM_PROVIDER_ZHIPU:
        prefix = "智谱 GLM"
    elif p == PLAN_LLM_PROVIDER_SILICONFLOW:
        prefix = "硅基流动"
    elif p == PLAN_LLM_PROVIDER_TONGYI:
        prefix = "通义千问"
    else:
        prefix = "官方 DeepSeek"
    return f"{prefix} / {m}"


def resolve_deepseek_keys(db: Session, user_id: int) -> str:
    """兼容旧调用：仅返回策划 API Keys。"""
    return resolve_plan_llm_config(db, user_id)["keys"]


def default_api_url_for_provider(provider: str) -> str:
    p = normalize_plan_llm_provider(provider)
    if p == PLAN_LLM_PROVIDER_OPENCODE_GO:
        return (
            settings.opencode_go_api_url
            or "https://opencode.ai/zen/go/v1/chat/completions"
        ).strip()
    if p == PLAN_LLM_PROVIDER_XIAOMI:
        return (
            settings.xiaomi_mimo_api_url
            or "https://api.xiaomimimo.com/v1/chat/completions"
        ).strip()
    if p == PLAN_LLM_PROVIDER_ZHIPU:
        return (
            settings.zhipu_api_url
            or "https://open.bigmodel.cn/api/paas/v4/chat/completions"
        ).strip()
    if p == PLAN_LLM_PROVIDER_SILICONFLOW:
        return (
            settings.siliconflow_api_url
            or "https://api.siliconflow.cn/v1/chat/completions"
        ).strip()
    if p == PLAN_LLM_PROVIDER_TONGYI:
        return (
            settings.tongyi_api_url
            or "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
        ).strip()
    return (
        settings.deepseek_api_url
        or "https://api.deepseek.com/chat/completions"
    ).strip()


def resolve_plan_llm_config(db: Session, user_id: int) -> PlanLlmConfig:
    """按用户后台配置解析策划通道 / URL / 模型 / Keys。"""
    row = ensure_user_secret(db, user_id)
    provider = normalize_plan_llm_provider(getattr(row, "plan_llm_provider", None))
    model = normalize_plan_llm_model(
        getattr(row, "plan_llm_model", None), provider=provider
    )
    user_keys = (row.deepseek_keys or "").strip()
    if not user_keys and provider == PLAN_LLM_PROVIDER_TONGYI:
        user_keys = (getattr(row, "dashscope_key", "") or "").strip()
    keys = user_keys or (settings.deepseek_api_keys or "").strip()
    api_url = default_api_url_for_provider(provider)

    return {
        "provider": provider,
        "api_url": api_url,
        "model": model,
        "keys": keys,
        "thinking_enabled": bool(getattr(row, "plan_thinking_enabled", False)),
    }


def resolve_plan_llm_group(db: Session, user_id: int) -> dict | None:
    """按用户配置解析混合模式多渠道策略组。

    若用户配置了 plan_group_id 则优先使用；未配置时使用 is_default 的组；
    若用户显式配置为 0（单模型模式），或无可用渠道组，则返回 None（走原有单模型逻辑）。
    """
    row = ensure_user_secret(db, user_id)
    group: LlmGroup | None = None
    group_id = getattr(row, "plan_group_id", None)
    if group_id == 0:
        # 显式指定单模型模式
        return None
    if group_id:
        group = db.query(LlmGroup).filter(LlmGroup.id == group_id).first()
    if group is None:
        group = db.query(LlmGroup).filter(LlmGroup.is_default == True).first()

    if group is not None:
        raw_ids = [
            int(x.strip())
            for x in (group.channel_ids or "").split(",")
            if x.strip().isdigit()
        ]
        if raw_ids:
            channels_in_db = (
                db.query(LlmChannel)
                .filter(LlmChannel.id.in_(raw_ids), LlmChannel.is_active == True)
                .all()
            )
            ch_map = {c.id: c for c in channels_in_db}
            sorted_channels = [ch_map[cid] for cid in raw_ids if cid in ch_map]
            if sorted_channels:
                channels_data = []
                for ch in sorted_channels:
                    keys = (ch.api_keys or "").strip()
                    if not keys:
                        keys = (settings.deepseek_api_keys or "").strip()
                    channels_data.append(
                        {
                            "id": ch.id,
                            "name": ch.name,
                            "provider": normalize_plan_llm_provider(ch.provider),
                            "model_name": normalize_plan_llm_model(
                                ch.model_name, provider=ch.provider
                            ),
                            "api_url": ch.api_url.strip()
                            if ch.api_url
                            else default_api_url_for_provider(ch.provider),
                            "keys": keys,
                            "thinking_enabled": bool(ch.thinking_enabled),
                        }
                    )
                return {
                    "group_id": group.id,
                    "group_name": group.name,
                    "dispatch_mode": str(group.dispatch_mode or "serial").strip().lower(),
                    "max_loops_per_channel": max(1, int(group.max_loops_per_channel or 2)),
                    "channels": channels_data,
                }

    return None


def test_channel_connection(
    *,
    provider: str,
    api_url: str,
    model_name: str,
    api_key: str,
    thinking_enabled: bool = False,
    timeout_sec: float = 12.0,
) -> tuple[bool, str, int]:
    """快速测试大模型连通性，返回 (success, message, elapsed_ms)。"""
    import time
    import httpx

    key = str(api_key or "").strip()
    if not key:
        return False, "未提供 API Key", 0
    # 若有多个 key，测试第一个
    first_key = [k.strip() for k in key.split(",") if k.strip()][0]
    p = normalize_plan_llm_provider(provider)
    url = (api_url or "").strip() or default_api_url_for_provider(p)
    model = (model_name or "").strip() or normalize_plan_llm_model("", provider=p)
    headers = {"Content-Type": "application/json"}
    if p == PLAN_LLM_PROVIDER_ZHIPU:
        headers["Authorization"] = f"Bearer {first_key}"
    elif p == PLAN_LLM_PROVIDER_XIAOMI:
        headers["api-key"] = first_key
    else:
        headers["Authorization"] = f"Bearer {first_key}"

    payload: dict = {
        "model": model,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 10,
    }
    if p == PLAN_LLM_PROVIDER_ZHIPU:
        payload["thinking"] = {"type": "enabled"}
    elif thinking_enabled:
        payload["thinking"] = {"type": "enabled"}

    t0 = time.monotonic()
    try:
        with httpx.Client(timeout=timeout_sec) as client:
            resp = client.post(url, headers=headers, json=payload)
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            if resp.status_code == 200:
                return True, f"连接成功 (HTTP 200, 耗时 {elapsed_ms}ms)", elapsed_ms
            return False, f"接口返回 HTTP {resp.status_code}: {resp.text[:140]}", elapsed_ms
    except Exception as exc:
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        return False, f"网络或请求异常: {exc}", elapsed_ms

