from __future__ import annotations

from quant_collector_app.storage_core.market_repository import upsert_klines


class _RecordingConnection:
    def __init__(self) -> None:
        self.batch_sizes: list[int] = []

    def executemany(self, _sql, parameters) -> None:
        self.batch_sizes.append(len(list(parameters)))


def test_large_kline_upsert_is_consumed_in_bounded_batches():
    connection = _RecordingConnection()

    upsert_klines(
        connection,
        ({"open_time_utc_ms": index} for index in range(12_001)),
    )

    assert connection.batch_sizes == [5_000, 5_000, 2_001]
