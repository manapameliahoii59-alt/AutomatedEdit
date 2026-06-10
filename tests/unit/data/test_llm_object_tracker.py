from app.data.services.llm_object_tracker import (
    _extract_json_object,
    _parse_bbox_payload,
    merge_supplement_keyframes,
    resolve_dashscope_api_key,
)


class TestMergeSupplementKeyframes:
    def test_keeps_cv_and_adds_beyond_range(self):
        cv = [(0, 0.1, 0.1, 0.2, 0.2), (5000, 0.3, 0.1, 0.2, 0.2)]
        llm = [(8000, 0.5, 0.1, 0.2, 0.2), (10000, 0.6, 0.1, 0.2, 0.2)]
        merged = merge_supplement_keyframes(cv, llm)
        assert merged == cv + llm

    def test_skips_overlapping_times(self):
        cv = [(0, 0.1, 0.1, 0.2, 0.2), (5000, 0.3, 0.1, 0.2, 0.2)]
        llm = [(5000, 0.9, 0.9, 0.1, 0.1), (8000, 0.5, 0.1, 0.2, 0.2)]
        merged = merge_supplement_keyframes(cv, llm)
        assert len(merged) == 3
        assert merged[-1][0] == 8000

    def test_fills_before_cv_range(self):
        cv = [(5000, 0.3, 0.1, 0.2, 0.2)]
        llm = [(1000, 0.1, 0.1, 0.2, 0.2)]
        merged = merge_supplement_keyframes(cv, llm)
        assert merged[0][0] == 1000
        assert merged[1][0] == 5000


class TestParseBboxPayload:
    def test_xywh_format(self):
        bbox = _parse_bbox_payload({"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4})
        assert bbox == (0.1, 0.2, 0.3, 0.4)

    def test_bbox_2d_format(self):
        bbox = _parse_bbox_payload({"bbox_2d": [0.1, 0.2, 0.4, 0.6]})
        assert bbox is not None
        assert bbox[0] == 0.1
        assert bbox[1] == 0.2
        assert abs(bbox[2] - 0.3) < 1e-6
        assert abs(bbox[3] - 0.4) < 1e-6

    def test_not_found(self):
        assert _parse_bbox_payload({"found": False}) is None

    def test_extract_json_from_fence(self):
        payload = _extract_json_object('说明\n```json\n{"x":0.1,"y":0.2,"w":0.3,"h":0.4}\n```')
        assert payload is not None
        assert payload["w"] == 0.3


class TestResolveDashscopeApiKey:
    def test_reads_config_value_not_config_item(self):
        key = resolve_dashscope_api_key()
        assert key
        assert key.startswith("sk-")
        assert "ConfigItem" not in key
