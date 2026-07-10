from app.data.services.series_list_client import SeriesListClient


class TestDownloadZipProgress:
    def test_progress_callback_receives_total_and_updates(self, monkeypatch, tmp_path):
        client = SeriesListClient.__new__(SeriesListClient)
        dest = tmp_path / "demo.zip"
        chunks = [b"a" * 1024, b"b" * 1024, b"c" * 1024]
        progress_calls: list[tuple[int, int | None, float]] = []

        class FakeResponse:
            headers = {"Content-Length": str(sum(len(c) for c in chunks))}

            @staticmethod
            def raise_for_status():
                return None

            @staticmethod
            def iter_content(chunk_size=0):
                yield from chunks

        monkeypatch.setattr(
            "app.data.services.series_list_client.requests.get",
            lambda *args, **kwargs: FakeResponse(),
        )

        result = client.download_zip_from_url(
            "http://example.com/file.zip",
            dest,
            timeout_ms=60_000,
            min_speed_kbps=0,
            warmup_sec=0,
            stall_sec=999,
            slow_window_sec=1,
            progress_callback=lambda downloaded, total, speed: progress_calls.append(
                (downloaded, total, speed)
            ),
        )

        assert dest.is_file()
        assert result["downloaded"] == sum(len(c) for c in chunks)
        assert progress_calls
        assert progress_calls[0][0] == 0
        assert progress_calls[0][1] == sum(len(c) for c in chunks)
        assert progress_calls[-1][0] == sum(len(c) for c in chunks)
