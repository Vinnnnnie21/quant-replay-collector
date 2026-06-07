from __future__ import annotations


def schema_version(conn) -> int:
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


def set_schema_version(conn, version: int) -> None:
    conn.execute(f"PRAGMA user_version={int(version)}")


def ensure_column(conn, table: str, column: str, column_type: str) -> None:
    cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")


def migrate_to_v1(conn) -> None:
    conn.executescript(
        """
        PRAGMA journal_mode=WAL;
        PRAGMA synchronous=NORMAL;

        CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY,
            symbol TEXT,
            interval TEXT,
            start_date_bjt TEXT,
            end_date_bjt TEXT,
            cursor_bar_index INTEGER,
            follow_latest INTEGER,
            speed REAL,
            last_opened_at TEXT,
            last_saved_at TEXT,
            app_version TEXT,
            initial_equity REAL,
            trade_notional REAL,
            fee_bps REAL,
            slippage_bps REAL,
            fill_mode TEXT
        );

        CREATE TABLE IF NOT EXISTS trades (
            trade_id TEXT PRIMARY KEY,
            session_id TEXT,
            symbol TEXT,
            interval TEXT,
            side TEXT,
            status TEXT,
            entry_event_id TEXT,
            exit_event_id TEXT,
            entry_bar_index INTEGER,
            exit_bar_index INTEGER,
            entry_bar_time_bjt TEXT,
            exit_bar_time_bjt TEXT,
            entry_real_time_bjt TEXT,
            exit_real_time_bjt TEXT,
            entry_price_proxy REAL,
            exit_price_proxy REAL,
            holding_bars INTEGER,
            final_return_pct REAL,
            fill_mode TEXT,
            fee_bps REAL,
            slippage_bps REAL,
            notional_quote REAL,
            quantity REAL,
            entry_price_raw REAL,
            exit_price_raw REAL,
            entry_fill_price REAL,
            exit_fill_price REAL,
            entry_fee_quote REAL,
            exit_fee_quote REAL,
            gross_pnl_quote REAL,
            net_pnl_quote REAL,
            gross_return_pct REAL,
            net_return_pct REAL,
            fee_return_pct REAL,
            created_at TEXT,
            updated_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_trades_session_status ON trades(session_id, status);

        CREATE TABLE IF NOT EXISTS trade_events (
            event_id TEXT PRIMARY KEY,
            session_id TEXT,
            trade_id TEXT,
            event_type TEXT,
            side TEXT,
            symbol TEXT,
            interval TEXT,
            bar_index INTEGER,
            bar_open_time_bjt TEXT,
            real_key_time_bjt TEXT,
            price_proxy REAL,
            label_tags_json TEXT,
            note TEXT,
            created_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_trade_events_session ON trade_events(session_id, created_at);

        CREATE TABLE IF NOT EXISTS event_windows (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT,
            event_id TEXT,
            offset INTEGER,
            is_event_bar INTEGER,
            bar_index INTEGER,
            bar_open_time_bjt TEXT,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume REAL,
            is_missing_padding INTEGER
        );
        CREATE INDEX IF NOT EXISTS idx_event_windows_event ON event_windows(event_id, offset);

        CREATE TABLE IF NOT EXISTS event_features (
            event_id TEXT PRIMARY KEY,
            session_id TEXT,
            trade_id TEXT,
            event_type TEXT,
            side TEXT,
            symbol TEXT,
            interval TEXT,
            price_proxy REAL,
            event_body REAL,
            event_upper_wick REAL,
            event_lower_wick REAL,
            event_range REAL,
            event_volume REAL,
            event_vol_ratio_5 REAL,
            pre_ret_3 REAL,
            pre_ret_5 REAL,
            pre_ret_10 REAL,
            pre_vol_3 REAL,
            pre_vol_5 REAL,
            pre_vol_10 REAL,
            prev_high10_dist_pct REAL,
            prev_low10_dist_pct REAL,
            bull_run_count INTEGER,
            bear_run_count INTEGER,
            event_upper_ratio REAL,
            event_lower_ratio REAL,
            event_body_ratio REAL,
            fwd_ret_1 REAL,
            fwd_ret_3 REAL,
            fwd_ret_5 REAL,
            fwd_ret_10 REAL,
            fwd_ret_1_side_adj REAL,
            fwd_ret_3_side_adj REAL,
            fwd_ret_5_side_adj REAL,
            fwd_ret_10_side_adj REAL,
            mfe_10 REAL,
            mae_10 REAL,
            manual_trade_final_return_pct REAL,
            manual_trade_holding_bars INTEGER,
            export_version TEXT,
            created_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_event_features_session ON event_features(session_id, created_at);

        CREATE TABLE IF NOT EXISTS account_equity (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT,
            sequence_no INTEGER,
            trade_id TEXT,
            event_id TEXT,
            equity_before REAL,
            realized_gross_pnl REAL,
            realized_fee REAL,
            realized_net_pnl REAL,
            equity_after REAL,
            equity_return_pct REAL,
            drawdown_pct REAL,
            created_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_account_equity_session ON account_equity(session_id, sequence_no);

        CREATE TABLE IF NOT EXISTS usdt_premium_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sample_time_bjt TEXT,
            p2p_buy_price_cny REAL,
            p2p_sell_price_cny REAL,
            p2p_avg_price_cny REAL,
            usd_cny_rate REAL,
            buy_premium_pct REAL,
            sell_premium_pct REAL,
            avg_premium_pct REAL,
            premium_pct REAL,
            fx_source TEXT,
            sample_status TEXT,
            error_message TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_usdt_sample_time ON usdt_premium_history(sample_time_bjt);
        """
    )

    ensure_column(conn, "usdt_premium_history", "buy_premium_pct", "REAL")
    ensure_column(conn, "usdt_premium_history", "sell_premium_pct", "REAL")
    ensure_column(conn, "usdt_premium_history", "avg_premium_pct", "REAL")
    ensure_column(conn, "usdt_premium_history", "fx_source", "TEXT")
    for column, column_type in {
        "symbol": "TEXT",
        "interval": "TEXT",
        "start_date_bjt": "TEXT",
        "end_date_bjt": "TEXT",
        "cursor_bar_index": "INTEGER",
        "follow_latest": "INTEGER",
        "speed": "REAL",
        "last_opened_at": "TEXT",
        "last_saved_at": "TEXT",
        "app_version": "TEXT",
        "initial_equity": "REAL",
        "trade_notional": "REAL",
        "fee_bps": "REAL",
        "slippage_bps": "REAL",
        "fill_mode": "TEXT",
    }.items():
        ensure_column(conn, "sessions", column, column_type)
    for column, column_type in {
        "symbol": "TEXT",
        "interval": "TEXT",
        "side": "TEXT",
        "entry_event_id": "TEXT",
        "exit_event_id": "TEXT",
        "entry_bar_index": "INTEGER",
        "exit_bar_index": "INTEGER",
        "entry_bar_time_bjt": "TEXT",
        "exit_bar_time_bjt": "TEXT",
        "entry_real_time_bjt": "TEXT",
        "exit_real_time_bjt": "TEXT",
        "entry_price_proxy": "REAL",
        "exit_price_proxy": "REAL",
        "holding_bars": "INTEGER",
        "final_return_pct": "REAL",
        "fill_mode": "TEXT",
        "fee_bps": "REAL",
        "slippage_bps": "REAL",
        "notional_quote": "REAL",
        "quantity": "REAL",
        "entry_price_raw": "REAL",
        "exit_price_raw": "REAL",
        "entry_fill_price": "REAL",
        "exit_fill_price": "REAL",
        "entry_fee_quote": "REAL",
        "exit_fee_quote": "REAL",
        "gross_pnl_quote": "REAL",
        "net_pnl_quote": "REAL",
        "gross_return_pct": "REAL",
        "net_return_pct": "REAL",
        "fee_return_pct": "REAL",
        "created_at": "TEXT",
        "updated_at": "TEXT",
    }.items():
        ensure_column(conn, "trades", column, column_type)


def migrate_to_v2(conn) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS klines (
            symbol TEXT NOT NULL,
            interval TEXT NOT NULL,
            open_time_utc_ms INTEGER NOT NULL,
            open_time_bjt TEXT,
            close_time_utc_ms INTEGER,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume REAL,
            source TEXT,
            downloaded_at TEXT,
            data_quality_status TEXT,
            PRIMARY KEY (symbol, interval, open_time_utc_ms)
        );
        CREATE INDEX IF NOT EXISTS idx_klines_symbol_interval_time
            ON klines(symbol, interval, open_time_utc_ms);

        CREATE TABLE IF NOT EXISTS data_quality_reports (
            report_id TEXT PRIMARY KEY,
            symbol TEXT,
            interval TEXT,
            start_time_bjt TEXT,
            end_time_bjt TEXT,
            expected_bars INTEGER,
            actual_bars INTEGER,
            missing_bars INTEGER,
            duplicated_bars INTEGER,
            invalid_rows INTEGER,
            first_open_time_bjt TEXT,
            last_open_time_bjt TEXT,
            created_at TEXT,
            report_json TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_quality_symbol_interval_time
            ON data_quality_reports(symbol, interval, created_at);
        """
    )


def migrate_to_v3(conn) -> None:
    conn.executescript(
        """
        CREATE INDEX IF NOT EXISTS idx_sessions_symbol_interval
            ON sessions(symbol, interval);
        CREATE INDEX IF NOT EXISTS idx_trades_session_symbol_interval
            ON trades(session_id, symbol, interval);
        CREATE INDEX IF NOT EXISTS idx_trade_events_trade_time
            ON trade_events(trade_id, bar_open_time_bjt);
        CREATE INDEX IF NOT EXISTS idx_trade_events_symbol_interval
            ON trade_events(symbol, interval);
        CREATE INDEX IF NOT EXISTS idx_event_windows_session_event
            ON event_windows(session_id, event_id);
        CREATE INDEX IF NOT EXISTS idx_event_features_symbol_interval
            ON event_features(symbol, interval);
        """
    )


def migrate_to_v4(conn) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS strategy_profiles (
            profile_id TEXT PRIMARY KEY,
            profile_version TEXT NOT NULL,
            name TEXT NOT NULL,
            mode TEXT NOT NULL,
            allowed_sides_json TEXT,
            allowed_symbols_json TEXT,
            allowed_intervals_json TEXT,
            entry_setup_rules_json TEXT,
            entry_filter_rules_json TEXT,
            risk_rules_json TEXT,
            exit_rules_json TEXT,
            invalidation_rules_json TEXT,
            expected_holding_bars INTEGER,
            selected_label TEXT,
            profile_payload_json TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_strategy_profiles_mode_updated
            ON strategy_profiles(mode, updated_at);

        CREATE TABLE IF NOT EXISTS observation_universe (
            sample_id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            profile_id TEXT,
            source_type TEXT NOT NULL CHECK (
                source_type IN (
                    'USER_TRADE', 'USER_EVENT', 'AUTO_CANDIDATE',
                    'SCHEDULED_BAR', 'MATCHED_CONTROL'
                )
            ),
            symbol TEXT NOT NULL,
            interval TEXT NOT NULL,
            bar_index INTEGER NOT NULL,
            event_time_bjt TEXT,
            user_action TEXT NOT NULL CHECK (
                user_action IN (
                    'OPEN_LONG', 'OPEN_SHORT', 'CLOSE_LONG',
                    'CLOSE_SHORT', 'HOLD', 'NO_ACTION'
                )
            ),
            side TEXT,
            linked_trade_id TEXT,
            linked_event_id TEXT,
            is_user_trade INTEGER NOT NULL DEFAULT 0,
            is_candidate INTEGER NOT NULL DEFAULT 0,
            is_matched_control INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_observation_session_market_bar
            ON observation_universe(session_id, symbol, interval, bar_index);
        CREATE INDEX IF NOT EXISTS idx_observation_profile_action
            ON observation_universe(profile_id, user_action);

        CREATE TABLE IF NOT EXISTS strategy_samples (
            strategy_sample_id TEXT PRIMARY KEY,
            sample_id TEXT NOT NULL,
            experiment_id TEXT NOT NULL,
            profile_id TEXT,
            profile_version TEXT,
            feature_version TEXT NOT NULL,
            label_version TEXT NOT NULL,
            dataset_hash TEXT NOT NULL,
            sample_role TEXT NOT NULL CHECK (
                sample_role IN (
                    'USER_ACTION', 'NO_ACTION', 'CANDIDATE',
                    'CONTROL', 'TRAIN', 'TEST'
                )
            ),
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_strategy_samples_experiment
            ON strategy_samples(experiment_id, sample_role);
        CREATE INDEX IF NOT EXISTS idx_strategy_samples_sample
            ON strategy_samples(sample_id);
        """
    )


def migrate_to_v5(conn) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS event_context_features (
            context_feature_id TEXT PRIMARY KEY,
            sample_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            feature_version TEXT NOT NULL,
            symbol TEXT NOT NULL,
            interval TEXT NOT NULL,
            bar_index INTEGER NOT NULL,
            lookback_bars INTEGER NOT NULL CHECK (lookback_bars IN (20, 50, 100)),
            feature_name TEXT NOT NULL CHECK (
                instr(lower(feature_name), 'fwd') = 0 AND
                instr(lower(feature_name), 'post') = 0 AND
                instr(lower(feature_name), 'future') = 0 AND
                instr(lower(feature_name), 'mfe') = 0 AND
                instr(lower(feature_name), 'mae') = 0 AND
                instr(lower(feature_name), 'hit_tp') = 0 AND
                instr(lower(feature_name), 'hit_sl') = 0 AND
                instr(lower(feature_name), 'pnl') = 0 AND
                instr(lower(feature_name), 'exit') = 0 AND
                instr(lower(feature_name), 'label') = 0
            ),
            feature_value REAL,
            created_at TEXT NOT NULL,
            UNIQUE (sample_id, feature_version, lookback_bars, feature_name)
        );
        CREATE INDEX IF NOT EXISTS idx_context_features_sample_version
            ON event_context_features(sample_id, feature_version, lookback_bars);
        CREATE INDEX IF NOT EXISTS idx_context_features_session_market
            ON event_context_features(session_id, symbol, interval, bar_index);

        CREATE TABLE IF NOT EXISTS research_outcome_labels (
            outcome_label_id TEXT PRIMARY KEY,
            sample_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            label_version TEXT NOT NULL,
            symbol TEXT NOT NULL,
            interval TEXT NOT NULL,
            bar_index INTEGER NOT NULL,
            horizon_bars INTEGER NOT NULL CHECK (horizon_bars IN (5, 10, 20, 50)),
            pricing_basis TEXT NOT NULL CHECK (
                pricing_basis IN ('next_open', 'event_close', 'legacy_mid', 'worst_case_same_bar')
            ),
            fwd_ret REAL,
            mfe REAL,
            mae REAL,
            hit_tp INTEGER,
            hit_sl INTEGER,
            r_multiple REAL,
            insufficient_future_bars INTEGER NOT NULL DEFAULT 0,
            pricing_note TEXT,
            created_at TEXT NOT NULL,
            UNIQUE (sample_id, label_version, horizon_bars, pricing_basis)
        );
        CREATE INDEX IF NOT EXISTS idx_outcome_labels_sample_version
            ON research_outcome_labels(sample_id, label_version, horizon_bars);
        CREATE INDEX IF NOT EXISTS idx_outcome_labels_session_market
            ON research_outcome_labels(session_id, symbol, interval, bar_index);
        """
    )
