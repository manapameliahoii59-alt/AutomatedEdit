"""Unit tests for FunASR component registry validation (packaged-build guard)."""

from app.data.services.transcription_service import (
    REQUIRED_FUNASR_COMPONENTS,
    TranscriptionService,
)


class _FakeTables:
    """Minimal stand-in for funasr.register.tables."""

    def __init__(self, **overrides):
        for table_name, keys in REQUIRED_FUNASR_COMPONENTS.items():
            setattr(self, table_name, {key: object() for key in keys})
        for table_name, registry in overrides.items():
            setattr(self, table_name, registry)


def test_missing_asr_components_returns_empty_when_all_registered():
    tables = _FakeTables()
    assert TranscriptionService._missing_asr_components(tables) == []


def test_missing_asr_components_detects_unregistered_frontend_and_tokenizer():
    tables = _FakeTables(
        frontend_classes={},
        tokenizer_classes={"SentencepiecesTokenizer": object()},
    )
    missing = TranscriptionService._missing_asr_components(tables)
    assert "frontend_classes:WavFrontend" in missing
    assert "frontend_classes:WavFrontendOnline" in missing
    assert "tokenizer_classes:SentencepiecesTokenizer" not in missing


def test_missing_asr_components_handles_missing_table_attribute():
    tables = _FakeTables()
    del tables.encoder_classes
    missing = TranscriptionService._missing_asr_components(tables)
    assert "encoder_classes:SenseVoiceEncoderSmall" in missing
    assert "encoder_classes:FSMN" in missing
