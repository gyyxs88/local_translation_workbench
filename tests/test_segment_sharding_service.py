from __future__ import annotations

from tools.local_translation_workbench.app.services.segment_sharding_service import SegmentShardingService


def test_segment_sharding_service_keeps_short_text_as_single_segment() -> None:
    service = SegmentShardingService()

    result = service.build_segments(body_source_text="第一段。\n\n第二段。")

    assert [item.segment_index for item in result] == [1]
    assert result[0].source_text == "第一段。\n\n第二段。"


def test_segment_sharding_service_splits_long_text_at_paragraph_boundaries() -> None:
    service = SegmentShardingService()
    body = f"{'甲' * 1200}\n\n{'乙' * 1200}\n\n{'丙' * 500}"

    result = service.build_segments(body_source_text=body)

    assert [item.segment_index for item in result] == [1, 2]
    assert result[0].source_text == f"{'甲' * 1200}\n\n{'乙' * 1200}"
    assert result[1].source_text == f"{'丙' * 500}"


def test_segment_sharding_service_merges_short_paragraphs_before_cutting() -> None:
    service = SegmentShardingService()
    body = f"{'甲' * 900}\n\n{'乙' * 900}\n\n{'丙' * 900}"

    result = service.build_segments(body_source_text=body)

    assert [item.segment_index for item in result] == [1, 2]
    assert result[0].source_text == f"{'甲' * 900}\n\n{'乙' * 900}"
    assert result[1].source_text == f"{'丙' * 900}"


def test_segment_sharding_service_falls_back_to_sentence_split_for_oversized_paragraph() -> None:
    service = SegmentShardingService()
    body = f"{'甲' * 2100}。{'乙' * 2100}。"

    result = service.build_segments(body_source_text=body)

    assert [item.segment_index for item in result] == [1, 2]
    assert result[0].source_text.endswith("。")
    assert result[1].source_text.endswith("。")
    assert all(len(item.source_text) <= service.HARD_MAX_CHARS for item in result)
