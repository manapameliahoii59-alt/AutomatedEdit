"""用户策划解密密钥与策划 LLM 配置。"""

from __future__ import annotations

from typing import TypedDict

from sqlalchemy.orm import Session

from app.config import settings
from app.models import UserSecret
from app.services.plan_crypto import generate_plan_decrypt_key

PLAN_LLM_PROVIDER_DEEPSEEK = "deepseek"
PLAN_LLM_PROVIDER_OPENCODE_GO = "opencode_go"
PLAN_LLM_PROVIDERS = frozenset(
    {PLAN_LLM_PROVIDER_DEEPSEEK, PLAN_LLM_PROVIDER_OPENCODE_GO}
)

# 管理后台下拉：(value, label)；value = provider|model
PLAN_LLM_PRESET_CHOICES: tuple[tuple[str, str], ...] = (
    (
        f"{PLAN_LLM_PROVIDER_DEEPSEEK}|deepseek-v4-flash",
        "官方 DeepSeek / deepseek-v4-flash",
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
)
_PLAN_LLM_PRESET_VALUES = {value for value, _label in PLAN_LLM_PRESET_CHOICES}


class PlanLlmConfig(TypedDict):
    provider: str
    api_url: str
    model: str
    keys: str


def ensure_user_secret(db: Session, user_id: int) -> UserSecret:
    row = db.query(UserSecret).filter(UserSecret.user_id == user_id).first()
    if row is None:
        row = UserSecret(
            user_id=user_id,
            plan_decrypt_key=generate_plan_decrypt_key(),
            plan_llm_provider=PLAN_LLM_PROVIDER_DEEPSEEK,
            plan_llm_model="",
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
    if key in PLAN_LLM_PROVIDERS:
        return key
    return PLAN_LLM_PROVIDER_DEEPSEEK


def normalize_plan_llm_model(value: str | None, *, provider: str) -> str:
    model = str(value or "").strip()
    if model:
        return model
    if provider == PLAN_LLM_PROVIDER_OPENCODE_GO:
        return (settings.opencode_go_model or "deepseek-v4-flash").strip()
    return (settings.deepseek_model or "deepseek-v4-flash").strip()


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
    prefix = "OpenCode Go" if p == PLAN_LLM_PROVIDER_OPENCODE_GO else "官方 DeepSeek"
    return f"{prefix} / {m}"


def resolve_deepseek_keys(db: Session, user_id: int) -> str:
    """兼容旧调用：仅返回策划 API Keys。"""
    return resolve_plan_llm_config(db, user_id)["keys"]


def resolve_plan_llm_config(db: Session, user_id: int) -> PlanLlmConfig:
    """按用户后台配置解析策划通道 / URL / 模型 / Keys。"""
    row = ensure_user_secret(db, user_id)
    provider = normalize_plan_llm_provider(getattr(row, "plan_llm_provider", None))
    model = normalize_plan_llm_model(
        getattr(row, "plan_llm_model", None), provider=provider
    )
    user_keys = (row.deepseek_keys or "").strip()
    keys = user_keys or (settings.deepseek_api_keys or "").strip()

    if provider == PLAN_LLM_PROVIDER_OPENCODE_GO:
        api_url = (
            settings.opencode_go_api_url
            or "https://opencode.ai/zen/go/v1/chat/completions"
        ).strip()
    else:
        api_url = (
            settings.deepseek_api_url
            or "https://api.deepseek.com/chat/completions"
        ).strip()

    return {
        "provider": provider,
        "api_url": api_url,
        "model": model,
        "keys": keys,
    }
