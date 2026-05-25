from __future__ import annotations

import pandas as pd

from time_series_analysis.microstructure import BID_ASK_BOUNCE_ACF_THRESHOLD, microstructure_diagnostics


def test_microstructure_output_is_explicitly_a_proxy():
    frame = pd.DataFrame(
        {
            "close": [100.0, 101.0, 100.0, 101.0, 100.0, 101.0],
            "high": [101.2] * 6,
            "low": [99.8] * 6,
            "volume": [1, 2, 1, 2, 1, 2],
        }
    )
    result = microstructure_diagnostics(frame, "1m")
    assert result["is_high_frequency_kline"] is True
    assert "not true spread" in result["limitation"]
    assert "not a measured bid-ask spread" in result["bid_ask_bounce_proxy"]["interpretation"]
    assert result["bid_ask_bounce_proxy"]["diagnostic_threshold"] == BID_ASK_BOUNCE_ACF_THRESHOLD
    assert result["bid_ask_bounce_proxy"]["warning"] is True
