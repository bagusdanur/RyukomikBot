import asyncio
import unittest
from io import BytesIO
from unittest.mock import AsyncMock, patch

from PIL import Image

from raw_rate_analysis import (
    RawWorkload, classify_workload, measure_raw_workload,
    suggest_assignment_rate, suggested_rate,
)


def _png_bytes(width, height):
    buffer = BytesIO()
    Image.new("RGB", (width, height), color="white").save(buffer, format="PNG")
    return buffer.getvalue()


class _FakeContent:
    def __init__(self, payload):
        self._payload = payload

    async def read(self, _size=-1):
        return self._payload

    async def iter_chunked(self, _size):
        yield self._payload


class _FakeResponse:
    def __init__(self, status, payload):
        self.status = status
        self.content = _FakeContent(payload)

    async def read(self):
        return await self.content.read()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False


class _FakeSession:
    def __init__(self, responses):
        self.responses = responses  # url -> (status, payload bytes)

    def get(self, url, headers=None, allow_redirects=False):
        status, payload = self.responses[url]
        # Simulate a source whose format only decodes from the full body
        # (e.g. extended/animated-container WebP): truncate range requests.
        if headers and "Range" in headers:
            payload = payload[:40]
        return _FakeResponse(status, payload)


class _FakeDownloader:
    def __init__(self, manga, chapters, images_by_chapter):
        self.manga, self.chapters, self.images_by_chapter = manga, chapters, images_by_chapter

    async def search_manga(self, _query):
        return [self.manga]

    async def get_chapter_list(self, _manga_id):
        return self.chapters

    async def get_chapter_images(self, _manga_id, chapter_id):
        return self.images_by_chapter[chapter_id]


class _NoResultsDownloader:
    async def search_manga(self, _query):
        return []


class RawRateAnalysisTests(unittest.TestCase):
    def test_light_chapter_uses_minimum(self):
        label, level, _ = classify_workload(RawWorkload(12, 12, 48_000, 4_000, 0))
        self.assertEqual((label, suggested_rate(4_000, 8_000, RawWorkload(12, 12, 48_000, 4_000, 0))), ("Ringan", 4_000))

    def test_tall_images_raise_workload(self):
        label, level, _ = classify_workload(RawWorkload(16, 16, 140_000, 11_000, 3))
        self.assertEqual(label, "Sedang")
        self.assertEqual(suggested_rate(5_000, 10_000, RawWorkload(16, 16, 140_000, 11_000, 3)), 7_500)

    def test_medium_uses_rounded_midpoint(self):
        _label, level, _ = classify_workload(RawWorkload(20, 20, 120_000, 6_000, 0))
        self.assertEqual(suggested_rate(9_000, 18_000, RawWorkload(20, 20, 120_000, 6_000, 0)), 11_000)

    def test_one_tall_page_is_only_a_small_adjustment(self):
        raw = RawWorkload(11, 11, 65_000, 13_745, 1)
        self.assertEqual(suggested_rate(9_000, 18_000, raw), 10_000)

    def test_short_chapter_with_many_tall_pages_stays_at_owner_standard(self):
        raw = RawWorkload(11, 11, 112_000, 14_000, 4)
        self.assertEqual(suggested_rate(9_000, 18_000, raw), 11_000)


class MeasureRawWorkloadTests(unittest.TestCase):
    def test_measures_dimensions_from_range_requests(self):
        urls = ["https://example.test/1.png", "https://example.test/2.png"]
        session = _FakeSession({
            urls[0]: (200, _png_bytes(800, 3000)),
            urls[1]: (206, _png_bytes(800, 9000)),
        })
        workload = asyncio.run(measure_raw_workload(urls, session=session))
        self.assertEqual(workload.page_count, 2)
        self.assertEqual(workload.measured_pages, 2)
        self.assertEqual(workload.max_height, 9000)
        self.assertEqual(workload.tall_pages, 1)

    def test_falls_back_to_full_download_when_partial_fails_to_decode(self):
        # Some sources (extended/animated-container WebP) refuse to decode
        # from a truncated range read no matter the byte count; _FakeSession
        # simulates that by truncating any request sent with a Range header.
        url = "https://example.test/tall.png"
        session = _FakeSession({url: (200, _png_bytes(800, 15670))})
        workload = asyncio.run(measure_raw_workload([url], session=session))
        self.assertEqual(workload.measured_pages, 1)
        self.assertEqual(workload.max_height, 15670)

    def test_unreadable_image_is_skipped_not_fatal(self):
        urls = ["https://example.test/1.png", "https://example.test/broken.png"]
        session = _FakeSession({
            urls[0]: (200, _png_bytes(800, 3000)),
            urls[1]: (404, b""),
        })
        workload = asyncio.run(measure_raw_workload(urls, session=session))
        self.assertEqual(workload.page_count, 2)
        self.assertEqual(workload.measured_pages, 1)


class SuggestAssignmentRateTests(unittest.TestCase):
    def test_resolved_rate_is_bounded_by_role_range(self):
        downloader = _FakeDownloader(
            {"id": "m1", "title": "Project"},
            [{"id": "chapter-1"}],
            {"chapter-1": ["https://example.test/1.png"] * 20},
        )
        canned = RawWorkload(20, 20, 20 * 9_000, 9_000, 1)
        with patch("raw_rate_analysis.measure_raw_workload", AsyncMock(return_value=canned)):
            result = asyncio.run(suggest_assignment_rate(
                "Project", ["1"], "TS", 5_000, 10_000, {"asura": downloader},
            ))
        self.assertEqual(result["status"], "resolved")
        self.assertEqual(result["workload"], classify_workload(canned)[0])
        self.assertTrue(5_000 <= result["rate_per_chapter"] <= 10_000)

    def test_no_images_status_when_chapter_has_no_pages(self):
        downloader = _FakeDownloader({"id": "m1", "title": "Project"}, [{"id": "chapter-1"}], {"chapter-1": []})
        with patch("raw_rate_analysis.measure_raw_workload", AsyncMock()) as measure:
            result = asyncio.run(suggest_assignment_rate(
                "Project", ["1"], "TL", 4_000, 8_000, {"asura": downloader},
            ))
        self.assertEqual(result["status"], "no_images")
        measure.assert_not_called()

    def test_unresolved_title_short_circuits_without_measuring(self):
        with patch("raw_rate_analysis.measure_raw_workload", AsyncMock()) as measure:
            result = asyncio.run(suggest_assignment_rate(
                "Unknown Project", ["1"], "TL", 4_000, 8_000, {"asura": _NoResultsDownloader()},
            ))
        self.assertEqual(result["status"], "not_found")
        measure.assert_not_called()
