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
            fill_mode TEXT,
            take_profit_pct REAL,
            stop_loss_pct REAL
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
            take_profit_pct REAL,
            stop_loss_pct REAL,
            take_profit_price REAL,
            stop_loss_price REAL,
            exit_reason TEXT,
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
        "take_profit_pct": "REAL",
        "stop_loss_pct": "REAL",
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
        "take_profit_pct": "REAL",
        "stop_loss_pct": "REAL",
        "take_profit_price": "REAL",
        "stop_loss_price": "REAL",
        "exit_reason": "TEXT",
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
        CREATE INDEX IF NOT EXISTS idx_trade_events_replay_time
            ON trade_events(bar_open_time_bjt, event_type, trade_id);
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


def migrate_to_v6(conn) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS entry_annotations (
            annotation_id TEXT PRIMARY KEY,
            session_id TEXT,
            symbol TEXT,
            interval TEXT,
            bar_index INTEGER,
            bar_time TEXT,
            setup_bar_index INTEGER,
            decision_bar_index INTEGER,
            setup_bar_time TEXT,
            decision_bar_time TEXT,
            human_decision TEXT CHECK (
                human_decision IN ('ENTRY', 'REJECT', 'UNCERTAIN', 'UNLABELED')
            ),
            confidence INTEGER CHECK (
                confidence IS NULL OR (confidence >= 1 AND confidence <= 5)
            ),
            reason_tags_json TEXT,
            note TEXT,
            decision_timing TEXT CHECK (
                decision_timing IN ('CURRENT_BAR_CLOSE', 'NEXT_BAR_CONFIRMATION')
            ),
            annotation_version TEXT,
            created_at TEXT,
            updated_at TEXT,
            is_active INTEGER NOT NULL DEFAULT 1,
            superseded_by TEXT,
            app_version TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_entry_annotations_session_market
            ON entry_annotations(session_id, symbol, interval, bar_index);
        CREATE INDEX IF NOT EXISTS idx_entry_annotations_decision
            ON entry_annotations(human_decision, created_at);

        CREATE TABLE IF NOT EXISTS entry_annotation_history (
            history_id INTEGER PRIMARY KEY AUTOINCREMENT,
            annotation_id TEXT NOT NULL,
            revision_no INTEGER NOT NULL,
            operation TEXT NOT NULL,
            session_id TEXT,
            symbol TEXT,
            interval TEXT,
            decision_bar_index INTEGER,
            changed_at TEXT,
            superseded_by TEXT,
            snapshot_json TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_entry_annotation_history_annotation
            ON entry_annotation_history(annotation_id, revision_no);
        CREATE INDEX IF NOT EXISTS idx_entry_annotation_history_session
            ON entry_annotation_history(session_id, symbol, interval, decision_bar_index);
        """
    )
    for column, column_type in {
        "setup_bar_index": "INTEGER",
        "decision_bar_index": "INTEGER",
        "setup_bar_time": "TEXT",
        "decision_bar_time": "TEXT",
        "annotation_version": "TEXT",
        "updated_at": "TEXT",
        "is_active": "INTEGER NOT NULL DEFAULT 1",
        "superseded_by": "TEXT",
    }.items():
        ensure_column(conn, "entry_annotations", column, column_type)
    conn.executescript(
        """
        UPDATE entry_annotations
        SET decision_bar_index=bar_index
        WHERE decision_bar_index IS NULL AND bar_index IS NOT NULL;

        UPDATE entry_annotations
        SET setup_bar_index=decision_bar_index
        WHERE setup_bar_index IS NULL
          AND decision_timing='CURRENT_BAR_CLOSE'
          AND decision_bar_index IS NOT NULL;

        UPDATE entry_annotations
        SET setup_bar_index=decision_bar_index - 1
        WHERE setup_bar_index IS NULL
          AND decision_timing='NEXT_BAR_CONFIRMATION'
          AND decision_bar_index IS NOT NULL;

        UPDATE entry_annotations
        SET decision_bar_time=bar_time
        WHERE decision_bar_time IS NULL AND bar_time IS NOT NULL;

        UPDATE entry_annotations
        SET setup_bar_time=decision_bar_time
        WHERE setup_bar_time IS NULL
          AND decision_timing='CURRENT_BAR_CLOSE'
          AND decision_bar_time IS NOT NULL;

        UPDATE entry_annotations
        SET annotation_version='entry_annotations_v1'
        WHERE annotation_version IS NULL OR annotation_version='';

        UPDATE entry_annotations
        SET updated_at=created_at
        WHERE updated_at IS NULL OR updated_at='';

        UPDATE entry_annotations
        SET is_active=1
        WHERE is_active IS NULL;

        CREATE INDEX IF NOT EXISTS idx_entry_annotations_active_decision
            ON entry_annotations(session_id, symbol, interval, decision_bar_index, is_active);
        """
    )


def migrate_to_v7(conn) -> None:
    # Some pre-versioned or partially repaired databases report a newer
    # user_version without every v2 market-data table. Reuse the idempotent
    # base migration before adding v7 columns.
    migrate_to_v2(conn)
    for column, column_type in {
        "quote_volume": "REAL",
        "trade_count": "INTEGER",
        "taker_buy_base_volume": "REAL",
        "taker_buy_quote_volume": "REAL",
    }.items():
        ensure_column(conn, "klines", column, column_type)


def migrate_to_v8(conn) -> None:
    conn.executescript(
        """
        BEGIN IMMEDIATE;

        CREATE TABLE IF NOT EXISTS setups (
            setup_id TEXT PRIMARY KEY,
            display_name TEXT NOT NULL CHECK (trim(display_name) <> ''),
            is_archived INTEGER NOT NULL DEFAULT 0 CHECK (is_archived IN (0, 1)),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            archived_at TEXT,
            creation_token TEXT NOT NULL UNIQUE
        );
        CREATE INDEX IF NOT EXISTS idx_setups_archived_name
            ON setups(is_archived, display_name, setup_id);

        CREATE TABLE IF NOT EXISTS setup_versions (
            setup_version_id TEXT PRIMARY KEY,
            setup_id TEXT NOT NULL REFERENCES setups(setup_id),
            version_number INTEGER NOT NULL CHECK (version_number > 0),
            parent_version_id TEXT REFERENCES setup_versions(setup_version_id),
            direction TEXT NOT NULL CHECK (direction IN ('LONG', 'SHORT')),
            decision_protocol TEXT NOT NULL CHECK (
                decision_protocol IN (
                    'CURRENT_BAR_CLOSE',
                    'NEXT_BAR_CONFIRMATION'
                )
            ),
            decision_rules TEXT NOT NULL CHECK (trim(decision_rules) <> ''),
            decision_timeframe TEXT NOT NULL,
            context_timeframe_one TEXT NOT NULL,
            context_timeframe_two TEXT NOT NULL,
            semantic_fingerprint TEXT NOT NULL,
            creation_key TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            UNIQUE (setup_id, version_number)
        );
        CREATE INDEX IF NOT EXISTS idx_setup_versions_setup_number
            ON setup_versions(setup_id, version_number);

        COMMIT;
        """
    )


def migrate_to_v9(conn) -> None:
    conn.executescript(
        """
        BEGIN IMMEDIATE;

        CREATE TABLE IF NOT EXISTS episode_grouping_versions (
            grouping_version_id TEXT PRIMARY KEY,
            formula_version TEXT NOT NULL,
            source TEXT NOT NULL CHECK (source IN ('AUTOMATIC', 'MANUAL_MERGE', 'MANUAL_SPLIT')),
            parent_grouping_version_id TEXT REFERENCES episode_grouping_versions(grouping_version_id),
            input_start_utc TEXT NOT NULL,
            input_end_utc TEXT NOT NULL,
            input_start_boundary TEXT NOT NULL CHECK (input_start_boundary IN ('OPEN', 'CLOSED')),
            input_end_boundary TEXT NOT NULL CHECK (input_end_boundary IN ('OPEN', 'CLOSED')),
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS market_episodes (
            grouping_version_id TEXT NOT NULL REFERENCES episode_grouping_versions(grouping_version_id),
            episode_id TEXT NOT NULL,
            start_utc TEXT NOT NULL,
            end_utc TEXT NOT NULL,
            start_boundary TEXT NOT NULL CHECK (start_boundary IN ('OPEN', 'CLOSED')),
            end_boundary TEXT NOT NULL CHECK (end_boundary IN ('OPEN', 'CLOSED')),
            source TEXT NOT NULL CHECK (source IN ('AUTOMATIC', 'MANUAL_MERGE', 'MANUAL_SPLIT')),
            PRIMARY KEY (grouping_version_id, episode_id)
        );
        CREATE INDEX IF NOT EXISTS idx_market_episodes_version_range
            ON market_episodes(grouping_version_id, start_utc, end_utc);

        CREATE TABLE IF NOT EXISTS market_episode_memberships (
            grouping_version_id TEXT NOT NULL,
            episode_id TEXT NOT NULL,
            sample_id TEXT NOT NULL,
            symbol TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            feature_start_utc TEXT NOT NULL,
            feature_end_utc TEXT NOT NULL,
            feature_start_boundary TEXT NOT NULL CHECK (feature_start_boundary IN ('OPEN', 'CLOSED')),
            feature_end_boundary TEXT NOT NULL CHECK (feature_end_boundary IN ('OPEN', 'CLOSED')),
            outcome_start_utc TEXT NOT NULL,
            outcome_end_utc TEXT NOT NULL,
            outcome_start_boundary TEXT NOT NULL CHECK (outcome_start_boundary IN ('OPEN', 'CLOSED')),
            outcome_end_boundary TEXT NOT NULL CHECK (outcome_end_boundary IN ('OPEN', 'CLOSED')),
            PRIMARY KEY (grouping_version_id, sample_id),
            FOREIGN KEY (grouping_version_id, episode_id)
                REFERENCES market_episodes(grouping_version_id, episode_id)
        );
        CREATE INDEX IF NOT EXISTS idx_episode_memberships_episode
            ON market_episode_memberships(grouping_version_id, episode_id, sample_id);

        CREATE TABLE IF NOT EXISTS market_episode_audit (
            audit_id TEXT PRIMARY KEY,
            base_grouping_version_id TEXT NOT NULL REFERENCES episode_grouping_versions(grouping_version_id),
            result_grouping_version_id TEXT NOT NULL UNIQUE REFERENCES episode_grouping_versions(grouping_version_id),
            command_type TEXT NOT NULL CHECK (command_type IN ('MANUAL_MERGE', 'MANUAL_SPLIT')),
            actor TEXT NOT NULL,
            reason TEXT NOT NULL,
            command_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_episode_audit_result
            ON market_episode_audit(result_grouping_version_id, created_at);

        COMMIT;
        """
    )


def migrate_to_v10(conn) -> None:
    conn.executescript(
        """
        BEGIN IMMEDIATE;

        CREATE TABLE IF NOT EXISTS entry_decision_events (
            decision_event_id TEXT PRIMARY KEY,
            source_sample_id TEXT NOT NULL,
            setup_version_id TEXT NOT NULL REFERENCES setup_versions(setup_version_id),
            grouping_version_id TEXT NOT NULL REFERENCES episode_grouping_versions(grouping_version_id),
            episode_id TEXT NOT NULL,
            session_id TEXT,
            symbol TEXT NOT NULL,
            direction TEXT NOT NULL CHECK (direction IN ('LONG', 'SHORT')),
            decision_timeframe TEXT NOT NULL,
            context_timeframe_one TEXT NOT NULL,
            context_timeframe_two TEXT NOT NULL,
            decision_cutoff_utc_ms INTEGER NOT NULL,
            decision_bar_open_time_utc_ms INTEGER NOT NULL,
            observed_action_time_utc_ms INTEGER,
            timing_approximate INTEGER NOT NULL CHECK (timing_approximate IN (0, 1)),
            created_at TEXT NOT NULL,
            UNIQUE (source_sample_id, setup_version_id, grouping_version_id),
            FOREIGN KEY (grouping_version_id, episode_id)
                REFERENCES market_episodes(grouping_version_id, episode_id)
        );
        CREATE INDEX IF NOT EXISTS idx_entry_decision_events_pending
            ON entry_decision_events(
                setup_version_id, grouping_version_id, created_at,
                decision_event_id
            );
        CREATE INDEX IF NOT EXISTS idx_entry_decision_events_episode_pending
            ON entry_decision_events(
                setup_version_id, grouping_version_id, episode_id,
                created_at, decision_event_id
            );

        CREATE TABLE IF NOT EXISTS entry_original_actions (
            decision_event_id TEXT PRIMARY KEY
                REFERENCES entry_decision_events(decision_event_id),
            seed_source TEXT NOT NULL CHECK (
                seed_source IN ('ACTUAL_OPEN', 'MANUAL_POSITION')
            ),
            original_action TEXT NOT NULL CHECK (
                original_action IN ('OPEN_LONG', 'OPEN_SHORT', 'NONE')
            ),
            source_event_id TEXT,
            action_time_utc_ms INTEGER,
            created_at TEXT NOT NULL,
            CHECK (
                (
                    seed_source='ACTUAL_OPEN'
                    AND original_action IN ('OPEN_LONG', 'OPEN_SHORT')
                    AND source_event_id IS NOT NULL
                    AND action_time_utc_ms IS NOT NULL
                ) OR (
                    seed_source='MANUAL_POSITION'
                    AND original_action='NONE'
                    AND source_event_id IS NULL
                )
            )
        );

        CREATE TABLE IF NOT EXISTS entry_review_batches (
            batch_id TEXT PRIMARY KEY,
            setup_version_id TEXT NOT NULL REFERENCES setup_versions(setup_version_id),
            grouping_version_id TEXT NOT NULL REFERENCES episode_grouping_versions(grouping_version_id),
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS entry_review_batch_items (
            batch_id TEXT NOT NULL REFERENCES entry_review_batches(batch_id),
            blind_item_id TEXT NOT NULL UNIQUE,
            decision_event_id TEXT NOT NULL REFERENCES entry_decision_events(decision_event_id),
            display_order INTEGER NOT NULL CHECK (display_order >= 0),
            PRIMARY KEY (batch_id, decision_event_id),
            UNIQUE (batch_id, display_order)
        );

        CREATE TABLE IF NOT EXISTS entry_judgment_versions (
            judgment_id TEXT PRIMARY KEY,
            decision_event_id TEXT NOT NULL REFERENCES entry_decision_events(decision_event_id),
            version_number INTEGER NOT NULL CHECK (version_number > 0),
            phase TEXT NOT NULL CHECK (phase IN ('BLIND', 'POST_OUTCOME')),
            label TEXT NOT NULL CHECK (label IN ('ENTRY', 'REJECT', 'UNCERTAIN')),
            reason_tags_json TEXT NOT NULL,
            confidence INTEGER NOT NULL CHECK (confidence BETWEEN 1 AND 5),
            note TEXT NOT NULL,
            previous_judgment_id TEXT REFERENCES entry_judgment_versions(judgment_id),
            eligible_for_primary_research INTEGER NOT NULL CHECK (
                eligible_for_primary_research IN (0, 1)
            ),
            created_at TEXT NOT NULL,
            UNIQUE (decision_event_id, version_number),
            CHECK (
                (
                    phase='BLIND'
                    AND version_number=1
                    AND previous_judgment_id IS NULL
                    AND eligible_for_primary_research=1
                ) OR (
                    phase='POST_OUTCOME'
                    AND version_number>1
                    AND previous_judgment_id IS NOT NULL
                    AND eligible_for_primary_research=0
                )
            )
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_entry_judgments_one_blind
            ON entry_judgment_versions(decision_event_id)
            WHERE phase='BLIND';

        CREATE TABLE IF NOT EXISTS entry_review_reveals (
            decision_event_id TEXT PRIMARY KEY
                REFERENCES entry_decision_events(decision_event_id),
            blind_judgment_id TEXT NOT NULL UNIQUE
                REFERENCES entry_judgment_versions(judgment_id),
            revealed_at TEXT NOT NULL
        );
        CREATE TRIGGER IF NOT EXISTS trg_entry_reveal_requires_blind_judgment
        BEFORE INSERT ON entry_review_reveals
        WHEN NOT EXISTS (
            SELECT 1
            FROM entry_judgment_versions AS judgment
            WHERE judgment.judgment_id=NEW.blind_judgment_id
              AND judgment.decision_event_id=NEW.decision_event_id
              AND judgment.phase='BLIND'
        )
        BEGIN
            SELECT RAISE(
                ABORT,
                'entry reveal requires the matching blind judgment'
            );
        END;

        CREATE TRIGGER IF NOT EXISTS trg_entry_relabel_requires_same_event_parent
        BEFORE INSERT ON entry_judgment_versions
        WHEN NEW.phase='POST_OUTCOME' AND NOT EXISTS (
            SELECT 1
            FROM entry_judgment_versions AS previous
            WHERE previous.judgment_id=NEW.previous_judgment_id
              AND previous.decision_event_id=NEW.decision_event_id
        )
        BEGIN
            SELECT RAISE(
                ABORT,
                'entry relabel parent must belong to the same decision event'
            );
        END;

        COMMIT;
        """
    )


def migrate_to_v11(conn) -> None:
    conn.executescript(
        """
        BEGIN IMMEDIATE;

        CREATE TABLE IF NOT EXISTS entry_similarity_audits (
            result_id TEXT PRIMARY KEY,
            left_decision_event_id TEXT NOT NULL
                REFERENCES entry_decision_events(decision_event_id),
            right_decision_event_id TEXT NOT NULL
                REFERENCES entry_decision_events(decision_event_id),
            setup_version_id TEXT NOT NULL
                REFERENCES setup_versions(setup_version_id),
            direction TEXT NOT NULL CHECK (direction IN ('LONG', 'SHORT')),
            formula_version TEXT NOT NULL,
            feature_version TEXT NOT NULL,
            left_feature_fingerprint TEXT NOT NULL,
            right_feature_fingerprint TEXT NOT NULL,
            status TEXT NOT NULL CHECK (
                status IN ('COMPUTED', 'NOT_COMPUTABLE')
            ),
            similarity REAL CHECK (
                similarity IS NULL OR similarity BETWEEN 0 AND 100
            ),
            usage TEXT NOT NULL CHECK (usage='FREE_BROWSE'),
            eligible_for_formal_evidence INTEGER NOT NULL CHECK (
                eligible_for_formal_evidence=0
            ),
            result_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            CHECK (left_decision_event_id <> right_decision_event_id),
            CHECK (
                (status='COMPUTED' AND similarity IS NOT NULL)
                OR (status='NOT_COMPUTABLE' AND similarity IS NULL)
            )
        );
        CREATE INDEX IF NOT EXISTS idx_entry_similarity_audits_pair
            ON entry_similarity_audits(
                setup_version_id, direction,
                left_decision_event_id, right_decision_event_id,
                created_at
            );
        CREATE INDEX IF NOT EXISTS idx_entry_decision_events_browsable
            ON entry_decision_events(
                setup_version_id, direction,
                decision_cutoff_utc_ms, decision_event_id
            );
        CREATE TRIGGER IF NOT EXISTS trg_entry_similarity_audits_no_update
        BEFORE UPDATE ON entry_similarity_audits
        BEGIN
            SELECT RAISE(ABORT, 'entry similarity audits are immutable');
        END;
        CREATE TRIGGER IF NOT EXISTS trg_entry_similarity_audits_valid_score
        BEFORE INSERT ON entry_similarity_audits
        WHEN NOT (
            (NEW.status='COMPUTED' AND NEW.similarity IS NOT NULL)
            OR (NEW.status='NOT_COMPUTABLE' AND NEW.similarity IS NULL)
        )
        BEGIN
            SELECT RAISE(
                ABORT,
                'entry similarity audit status and score are inconsistent'
            );
        END;
        CREATE TRIGGER IF NOT EXISTS trg_entry_similarity_audits_no_delete
        BEFORE DELETE ON entry_similarity_audits
        BEGIN
            SELECT RAISE(ABORT, 'entry similarity audits are immutable');
        END;

        COMMIT;
        """
    )


def migrate_to_v12(conn) -> None:
    conn.executescript(
        """
        BEGIN IMMEDIATE;

        CREATE TABLE IF NOT EXISTS entry_candidate_scans (
            scan_id TEXT PRIMARY KEY,
            setup_version_id TEXT NOT NULL
                REFERENCES setup_versions(setup_version_id),
            grouping_version_id TEXT NOT NULL
                REFERENCES episode_grouping_versions(grouping_version_id),
            direction TEXT NOT NULL CHECK (direction IN ('LONG', 'SHORT')),
            formula_version TEXT NOT NULL,
            feature_version TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('NOT_READY', 'COMPLETED')),
            result_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_entry_candidate_scans_context
            ON entry_candidate_scans(
                setup_version_id, grouping_version_id, direction, created_at
            );

        CREATE TABLE IF NOT EXISTS entry_candidate_scores (
            scan_id TEXT NOT NULL
                REFERENCES entry_candidate_scans(scan_id),
            source_sample_id TEXT NOT NULL,
            episode_id TEXT NOT NULL,
            similarity REAL NOT NULL CHECK (similarity BETWEEN 0 AND 100),
            completeness_ratio REAL NOT NULL CHECK (
                completeness_ratio BETWEEN 0 AND 1
            ),
            references_json TEXT NOT NULL,
            diversity_vector_json TEXT NOT NULL,
            enqueue_reason TEXT NOT NULL CHECK (
                enqueue_reason='STRUCTURAL_SIMILARITY'
            ),
            PRIMARY KEY (scan_id, source_sample_id)
        );
        CREATE INDEX IF NOT EXISTS idx_entry_candidate_scores_rank
            ON entry_candidate_scores(
                scan_id, similarity DESC, source_sample_id
            );
        CREATE INDEX IF NOT EXISTS idx_entry_candidate_scores_episode
            ON entry_candidate_scores(scan_id, episode_id, source_sample_id);

        CREATE TABLE IF NOT EXISTS entry_candidate_batches (
            batch_id TEXT PRIMARY KEY REFERENCES entry_review_batches(batch_id),
            scan_id TEXT NOT NULL REFERENCES entry_candidate_scans(scan_id),
            high_similarity_count INTEGER NOT NULL CHECK (high_similarity_count >= 0),
            diverse_count INTEGER NOT NULL CHECK (diverse_count >= 0),
            created_at TEXT NOT NULL,
            UNIQUE (batch_id, scan_id)
        );
        CREATE TABLE IF NOT EXISTS entry_candidate_batch_items (
            batch_id TEXT NOT NULL REFERENCES entry_candidate_batches(batch_id),
            scan_id TEXT NOT NULL,
            source_sample_id TEXT NOT NULL UNIQUE,
            decision_event_id TEXT NOT NULL UNIQUE
                REFERENCES entry_decision_events(decision_event_id),
            selection_reason TEXT NOT NULL CHECK (
                selection_reason IN ('HIGH_SIMILARITY', 'STRUCTURAL_DIVERSITY')
            ),
            PRIMARY KEY (batch_id, source_sample_id),
            FOREIGN KEY (batch_id, scan_id)
                REFERENCES entry_candidate_batches(batch_id, scan_id),
            FOREIGN KEY (scan_id, source_sample_id)
                REFERENCES entry_candidate_scores(scan_id, source_sample_id)
        );
        CREATE INDEX IF NOT EXISTS idx_entry_candidate_batch_scan
            ON entry_candidate_batch_items(scan_id, source_sample_id);

        CREATE TABLE IF NOT EXISTS entry_candidate_exclusions (
            setup_version_id TEXT NOT NULL
                REFERENCES setup_versions(setup_version_id),
            grouping_version_id TEXT NOT NULL
                REFERENCES episode_grouping_versions(grouping_version_id),
            source_sample_id TEXT PRIMARY KEY,
            reason TEXT NOT NULL CHECK (reason='FREE_BROWSE_REVEAL'),
            created_at TEXT NOT NULL,
            UNIQUE (setup_version_id, grouping_version_id, source_sample_id)
        );

        CREATE TRIGGER IF NOT EXISTS trg_entry_candidate_scans_no_update
        BEFORE UPDATE ON entry_candidate_scans
        BEGIN
            SELECT RAISE(ABORT, 'entry candidate scans are immutable');
        END;
        CREATE TRIGGER IF NOT EXISTS trg_entry_candidate_scans_no_delete
        BEFORE DELETE ON entry_candidate_scans
        BEGIN
            SELECT RAISE(ABORT, 'entry candidate scans are immutable');
        END;
        CREATE TRIGGER IF NOT EXISTS trg_entry_candidate_scores_no_update
        BEFORE UPDATE ON entry_candidate_scores
        BEGIN
            SELECT RAISE(ABORT, 'entry candidate scores are immutable');
        END;
        CREATE TRIGGER IF NOT EXISTS trg_entry_candidate_scores_no_delete
        BEFORE DELETE ON entry_candidate_scores
        BEGIN
            SELECT RAISE(ABORT, 'entry candidate scores are immutable');
        END;
        CREATE TRIGGER IF NOT EXISTS trg_entry_candidate_batches_no_update
        BEFORE UPDATE ON entry_candidate_batches
        BEGIN
            SELECT RAISE(ABORT, 'entry candidate batches are immutable');
        END;
        CREATE TRIGGER IF NOT EXISTS trg_entry_candidate_batches_no_delete
        BEFORE DELETE ON entry_candidate_batches
        BEGIN
            SELECT RAISE(ABORT, 'entry candidate batches are immutable');
        END;
        CREATE TRIGGER IF NOT EXISTS trg_entry_candidate_batch_items_no_update
        BEFORE UPDATE ON entry_candidate_batch_items
        BEGIN
            SELECT RAISE(ABORT, 'entry candidate batch items are immutable');
        END;
        CREATE TRIGGER IF NOT EXISTS trg_entry_candidate_batch_items_no_delete
        BEFORE DELETE ON entry_candidate_batch_items
        BEGIN
            SELECT RAISE(ABORT, 'entry candidate batch items are immutable');
        END;
        CREATE TRIGGER IF NOT EXISTS trg_entry_candidate_exclusions_no_update
        BEFORE UPDATE ON entry_candidate_exclusions
        BEGIN
            SELECT RAISE(ABORT, 'entry candidate exclusions are immutable');
        END;
        CREATE TRIGGER IF NOT EXISTS trg_entry_candidate_exclusions_no_delete
        BEFORE DELETE ON entry_candidate_exclusions
        BEGIN
            SELECT RAISE(ABORT, 'entry candidate exclusions are immutable');
        END;

        COMMIT;
        """
    )


def migrate_to_v13(conn) -> None:
    conn.executescript(
        """
        BEGIN IMMEDIATE;

        CREATE TABLE IF NOT EXISTS entry_behavior_experiments (
            experiment_id TEXT PRIMARY KEY,
            setup_version_id TEXT NOT NULL
                REFERENCES setup_versions(setup_version_id),
            grouping_version_id TEXT NOT NULL
                REFERENCES episode_grouping_versions(grouping_version_id),
            direction TEXT NOT NULL CHECK (direction IN ('LONG', 'SHORT')),
            status TEXT NOT NULL CHECK (status IN ('COMPLETED', 'FAILED')),
            failure_code TEXT,
            result_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            CHECK (
                (status='COMPLETED' AND failure_code IS NULL)
                OR (status='FAILED' AND failure_code IS NOT NULL)
            )
        );
        CREATE INDEX IF NOT EXISTS idx_entry_behavior_experiments_context
            ON entry_behavior_experiments(
                setup_version_id, grouping_version_id, direction, created_at
            );

        CREATE TABLE IF NOT EXISTS entry_behavior_model_versions (
            model_version_id TEXT PRIMARY KEY,
            experiment_id TEXT NOT NULL UNIQUE
                REFERENCES entry_behavior_experiments(experiment_id),
            setup_version_id TEXT NOT NULL
                REFERENCES setup_versions(setup_version_id),
            grouping_version_id TEXT NOT NULL
                REFERENCES episode_grouping_versions(grouping_version_id),
            direction TEXT NOT NULL CHECK (direction IN ('LONG', 'SHORT')),
            maturity TEXT NOT NULL CHECK (
                maturity IN ('EXPLORATORY', 'FORMAL')
            ),
            training_cutoff_utc_ms INTEGER NOT NULL,
            label_fingerprint TEXT NOT NULL,
            model_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_entry_behavior_models_context
            ON entry_behavior_model_versions(
                setup_version_id, grouping_version_id, direction, created_at
            );

        CREATE TRIGGER IF NOT EXISTS trg_entry_behavior_model_requires_experiment
        BEFORE INSERT ON entry_behavior_model_versions
        WHEN NOT EXISTS (
            SELECT 1
            FROM entry_behavior_experiments AS experiment
            WHERE experiment.experiment_id=NEW.experiment_id
              AND experiment.status='COMPLETED'
              AND experiment.setup_version_id=NEW.setup_version_id
              AND experiment.grouping_version_id=NEW.grouping_version_id
              AND experiment.direction=NEW.direction
        )
        BEGIN
            SELECT RAISE(
                ABORT,
                'entry behavior model requires its matching completed experiment'
            );
        END;

        CREATE TRIGGER IF NOT EXISTS trg_entry_behavior_experiments_no_update
        BEFORE UPDATE ON entry_behavior_experiments
        BEGIN
            SELECT RAISE(ABORT, 'entry behavior experiments are immutable');
        END;
        CREATE TRIGGER IF NOT EXISTS trg_entry_behavior_experiments_no_delete
        BEFORE DELETE ON entry_behavior_experiments
        BEGIN
            SELECT RAISE(ABORT, 'entry behavior experiments are immutable');
        END;
        CREATE TRIGGER IF NOT EXISTS trg_entry_behavior_models_no_update
        BEFORE UPDATE ON entry_behavior_model_versions
        BEGIN
            SELECT RAISE(ABORT, 'entry behavior model versions are immutable');
        END;
        CREATE TRIGGER IF NOT EXISTS trg_entry_behavior_models_no_delete
        BEFORE DELETE ON entry_behavior_model_versions
        BEGIN
            SELECT RAISE(ABORT, 'entry behavior model versions are immutable');
        END;

        COMMIT;
        """
    )


def migrate_to_v14(conn) -> None:
    conn.executescript(
        """
        BEGIN IMMEDIATE;

        CREATE TABLE IF NOT EXISTS entry_outcome_comparisons (
            comparison_id TEXT PRIMARY KEY,
            setup_version_id TEXT NOT NULL
                REFERENCES setup_versions(setup_version_id),
            grouping_version_id TEXT NOT NULL
                REFERENCES episode_grouping_versions(grouping_version_id),
            direction TEXT NOT NULL CHECK (direction IN ('LONG', 'SHORT')),
            formula_version TEXT NOT NULL,
            feature_version TEXT NOT NULL,
            input_feature_fingerprint TEXT NOT NULL CHECK (
                length(input_feature_fingerprint) = 64
            ),
            random_seed INTEGER NOT NULL,
            result_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_entry_outcome_comparisons_context
            ON entry_outcome_comparisons(
                setup_version_id, grouping_version_id, direction, created_at
            );

        CREATE TABLE IF NOT EXISTS entry_outcome_matches (
            comparison_id TEXT NOT NULL
                REFERENCES entry_outcome_comparisons(comparison_id),
            similarity_threshold REAL NOT NULL CHECK (
                similarity_threshold IN (70.0, 75.0, 80.0)
            ),
            entry_decision_event_id TEXT NOT NULL
                REFERENCES entry_decision_events(decision_event_id),
            reject_decision_event_id TEXT NOT NULL
                REFERENCES entry_decision_events(decision_event_id),
            entry_episode_id TEXT NOT NULL,
            reject_episode_id TEXT NOT NULL,
            symbol TEXT NOT NULL,
            decision_timeframe TEXT NOT NULL,
            similarity REAL NOT NULL CHECK (similarity BETWEEN 0 AND 100),
            context_distance REAL NOT NULL CHECK (
                context_distance BETWEEN 0 AND 1
            ),
            PRIMARY KEY (
                comparison_id, similarity_threshold,
                entry_decision_event_id, reject_decision_event_id
            ),
            UNIQUE (
                comparison_id, similarity_threshold,
                entry_decision_event_id
            ),
            UNIQUE (
                comparison_id, similarity_threshold,
                reject_decision_event_id
            )
        );
        CREATE INDEX IF NOT EXISTS idx_entry_outcome_matches_threshold
            ON entry_outcome_matches(
                comparison_id, similarity_threshold, similarity DESC
            );

        CREATE TRIGGER IF NOT EXISTS trg_entry_outcome_comparisons_no_update
        BEFORE UPDATE ON entry_outcome_comparisons
        BEGIN
            SELECT RAISE(ABORT, 'entry outcome comparisons are immutable');
        END;
        CREATE TRIGGER IF NOT EXISTS trg_entry_outcome_comparisons_no_delete
        BEFORE DELETE ON entry_outcome_comparisons
        BEGIN
            SELECT RAISE(ABORT, 'entry outcome comparisons are immutable');
        END;
        CREATE TRIGGER IF NOT EXISTS trg_entry_outcome_matches_no_update
        BEFORE UPDATE ON entry_outcome_matches
        BEGIN
            SELECT RAISE(ABORT, 'entry outcome matches are immutable');
        END;
        CREATE TRIGGER IF NOT EXISTS trg_entry_outcome_matches_no_delete
        BEFORE DELETE ON entry_outcome_matches
        BEGIN
            SELECT RAISE(ABORT, 'entry outcome matches are immutable');
        END;

        COMMIT;
        """
    )


def migrate_to_v15(conn) -> None:
    """Add immutable exit blind-review records without rewriting entry history."""

    conn.executescript(
        """
        BEGIN IMMEDIATE;

        CREATE TABLE IF NOT EXISTS exit_decision_events (
            decision_event_id TEXT PRIMARY KEY,
            source_sample_id TEXT NOT NULL,
            setup_version_id TEXT REFERENCES setup_versions(setup_version_id),
            review_setup_version_id TEXT NOT NULL
                REFERENCES setup_versions(setup_version_id),
            grouping_version_id TEXT NOT NULL
                REFERENCES episode_grouping_versions(grouping_version_id),
            episode_id TEXT NOT NULL,
            trade_id TEXT NOT NULL,
            entry_event_id TEXT,
            session_id TEXT,
            symbol TEXT NOT NULL,
            direction TEXT NOT NULL CHECK (direction IN ('LONG', 'SHORT')),
            decision_timeframe TEXT NOT NULL,
            context_timeframe_one TEXT NOT NULL,
            context_timeframe_two TEXT NOT NULL,
            decision_cutoff_utc_ms INTEGER NOT NULL,
            decision_bar_open_time_utc_ms INTEGER NOT NULL,
            observed_action_time_utc_ms INTEGER,
            timing_approximate INTEGER NOT NULL CHECK (
                timing_approximate IN (0, 1)
            ),
            setup_link_status TEXT NOT NULL CHECK (
                setup_link_status IN ('LINKED', 'LEGACY_UNLINKED')
            ),
            eligible_for_formal_research INTEGER NOT NULL CHECK (
                eligible_for_formal_research IN (0, 1)
            ),
            created_at TEXT NOT NULL,
            UNIQUE (
                source_sample_id, review_setup_version_id,
                grouping_version_id
            ),
            FOREIGN KEY (grouping_version_id, episode_id)
                REFERENCES market_episodes(grouping_version_id, episode_id),
            CHECK (
                (setup_link_status='LINKED'
                    AND setup_version_id=review_setup_version_id
                    AND entry_event_id IS NOT NULL)
                OR
                (setup_link_status='LEGACY_UNLINKED'
                    AND setup_version_id IS NULL
                    AND eligible_for_formal_research=0)
            )
        );
        CREATE INDEX IF NOT EXISTS idx_exit_decision_events_pending
            ON exit_decision_events(
                review_setup_version_id, grouping_version_id,
                created_at, decision_event_id
            );
        CREATE INDEX IF NOT EXISTS idx_exit_decision_events_trade
            ON exit_decision_events(trade_id, decision_cutoff_utc_ms);

        CREATE TABLE IF NOT EXISTS exit_position_snapshots (
            decision_event_id TEXT PRIMARY KEY
                REFERENCES exit_decision_events(decision_event_id),
            actual_entry_price REAL,
            entry_price_source TEXT NOT NULL CHECK (
                entry_price_source IN ('FILL', 'PROXY', 'MISSING')
            ),
            entry_atr20 REAL,
            entry_atr_status TEXT NOT NULL CHECK (
                entry_atr_status IN ('AVAILABLE', 'MISSING')
            ),
            entry_bar_index INTEGER,
            decision_bar_index INTEGER,
            take_profit_status TEXT NOT NULL CHECK (
                take_profit_status IN ('SET', 'NOT_SET', 'MISSING')
            ),
            take_profit_price REAL,
            stop_loss_status TEXT NOT NULL CHECK (
                stop_loss_status IN ('SET', 'NOT_SET', 'MISSING')
            ),
            stop_loss_price REAL,
            created_at TEXT NOT NULL,
            CHECK (
                (entry_atr_status='AVAILABLE' AND entry_atr20 > 0)
                OR (entry_atr_status='MISSING' AND entry_atr20 IS NULL)
            ),
            CHECK (
                (take_profit_status='SET' AND take_profit_price IS NOT NULL)
                OR (take_profit_status IN ('NOT_SET', 'MISSING')
                    AND take_profit_price IS NULL)
            ),
            CHECK (
                (stop_loss_status='SET' AND stop_loss_price IS NOT NULL)
                OR (stop_loss_status IN ('NOT_SET', 'MISSING')
                    AND stop_loss_price IS NULL)
            )
        );

        CREATE TABLE IF NOT EXISTS exit_account_pressure_snapshots (
            decision_event_id TEXT PRIMARY KEY
                REFERENCES exit_decision_events(decision_event_id),
            equity_before_decision REAL,
            position_notional_quote REAL,
            position_equity_ratio REAL,
            total_open_notional_quote REAL,
            total_exposure_ratio REAL,
            open_position_count INTEGER NOT NULL CHECK (
                open_position_count >= 0
            ),
            account_drawdown_pct REAL,
            leverage REAL,
            margin_quote REAL,
            liquidation_price REAL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS exit_original_actions (
            decision_event_id TEXT PRIMARY KEY
                REFERENCES exit_decision_events(decision_event_id),
            seed_source TEXT NOT NULL CHECK (
                seed_source IN ('ACTUAL_CLOSE', 'MANUAL_POSITION')
            ),
            original_action TEXT NOT NULL CHECK (
                original_action IN ('FULL_CLOSE', 'NONE')
            ),
            source_event_id TEXT,
            action_time_utc_ms INTEGER,
            realized_pnl_quote REAL,
            created_at TEXT NOT NULL,
            CHECK (
                (seed_source='ACTUAL_CLOSE'
                    AND original_action='FULL_CLOSE'
                    AND source_event_id IS NOT NULL
                    AND action_time_utc_ms IS NOT NULL)
                OR
                (seed_source='MANUAL_POSITION'
                    AND original_action='NONE'
                    AND source_event_id IS NULL)
            )
        );

        CREATE TABLE IF NOT EXISTS exit_review_batches (
            batch_id TEXT PRIMARY KEY,
            setup_version_id TEXT NOT NULL
                REFERENCES setup_versions(setup_version_id),
            grouping_version_id TEXT NOT NULL
                REFERENCES episode_grouping_versions(grouping_version_id),
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS exit_review_batch_items (
            batch_id TEXT NOT NULL REFERENCES exit_review_batches(batch_id),
            blind_item_id TEXT NOT NULL UNIQUE,
            decision_event_id TEXT NOT NULL
                REFERENCES exit_decision_events(decision_event_id),
            display_order INTEGER NOT NULL CHECK (display_order >= 0),
            PRIMARY KEY (batch_id, decision_event_id),
            UNIQUE (batch_id, display_order)
        );

        CREATE TABLE IF NOT EXISTS exit_judgment_versions (
            judgment_id TEXT PRIMARY KEY,
            decision_event_id TEXT NOT NULL
                REFERENCES exit_decision_events(decision_event_id),
            version_number INTEGER NOT NULL CHECK (version_number > 0),
            phase TEXT NOT NULL CHECK (phase IN ('BLIND', 'POST_OUTCOME')),
            label TEXT NOT NULL CHECK (
                label IN ('EXIT_NOW', 'HOLD', 'UNCERTAIN')
            ),
            reason_tags_json TEXT NOT NULL,
            confidence INTEGER NOT NULL CHECK (confidence BETWEEN 1 AND 5),
            note TEXT NOT NULL,
            previous_judgment_id TEXT
                REFERENCES exit_judgment_versions(judgment_id),
            eligible_for_primary_research INTEGER NOT NULL CHECK (
                eligible_for_primary_research IN (0, 1)
            ),
            created_at TEXT NOT NULL,
            UNIQUE (decision_event_id, version_number),
            CHECK (
                (phase='BLIND' AND version_number=1
                    AND previous_judgment_id IS NULL)
                OR
                (phase='POST_OUTCOME' AND version_number>1
                    AND previous_judgment_id IS NOT NULL
                    AND eligible_for_primary_research=0)
            )
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_exit_judgments_one_blind
            ON exit_judgment_versions(decision_event_id)
            WHERE phase='BLIND';

        CREATE TABLE IF NOT EXISTS exit_review_reveals (
            decision_event_id TEXT PRIMARY KEY
                REFERENCES exit_decision_events(decision_event_id),
            blind_judgment_id TEXT NOT NULL UNIQUE
                REFERENCES exit_judgment_versions(judgment_id),
            revealed_at TEXT NOT NULL
        );
        CREATE TRIGGER IF NOT EXISTS trg_exit_reveal_requires_blind_judgment
        BEFORE INSERT ON exit_review_reveals
        WHEN NOT EXISTS (
            SELECT 1 FROM exit_judgment_versions AS judgment
            WHERE judgment.judgment_id=NEW.blind_judgment_id
              AND judgment.decision_event_id=NEW.decision_event_id
              AND judgment.phase='BLIND'
        )
        BEGIN
            SELECT RAISE(
                ABORT,
                'exit reveal requires the matching blind judgment'
            );
        END;
        CREATE TRIGGER IF NOT EXISTS trg_exit_relabel_requires_same_event_parent
        BEFORE INSERT ON exit_judgment_versions
        WHEN NEW.phase='POST_OUTCOME' AND NOT EXISTS (
            SELECT 1 FROM exit_judgment_versions AS previous
            WHERE previous.judgment_id=NEW.previous_judgment_id
              AND previous.decision_event_id=NEW.decision_event_id
        )
        BEGIN
            SELECT RAISE(
                ABORT,
                'exit relabel parent must belong to the same decision event'
            );
        END;

        CREATE TRIGGER IF NOT EXISTS trg_exit_decision_events_no_update
        BEFORE UPDATE ON exit_decision_events
        BEGIN
            SELECT RAISE(ABORT, 'exit decision events are immutable');
        END;
        CREATE TRIGGER IF NOT EXISTS trg_exit_decision_events_no_delete
        BEFORE DELETE ON exit_decision_events
        BEGIN
            SELECT RAISE(ABORT, 'exit decision events are immutable');
        END;
        CREATE TRIGGER IF NOT EXISTS trg_exit_position_snapshots_no_update
        BEFORE UPDATE ON exit_position_snapshots
        BEGIN
            SELECT RAISE(ABORT, 'exit position snapshots are immutable');
        END;
        CREATE TRIGGER IF NOT EXISTS trg_exit_position_snapshots_no_delete
        BEFORE DELETE ON exit_position_snapshots
        BEGIN
            SELECT RAISE(ABORT, 'exit position snapshots are immutable');
        END;
        CREATE TRIGGER IF NOT EXISTS trg_exit_account_pressure_no_update
        BEFORE UPDATE ON exit_account_pressure_snapshots
        BEGIN
            SELECT RAISE(ABORT, 'exit account pressure snapshots are immutable');
        END;
        CREATE TRIGGER IF NOT EXISTS trg_exit_account_pressure_no_delete
        BEFORE DELETE ON exit_account_pressure_snapshots
        BEGIN
            SELECT RAISE(ABORT, 'exit account pressure snapshots are immutable');
        END;
        CREATE TRIGGER IF NOT EXISTS trg_exit_original_actions_no_update
        BEFORE UPDATE ON exit_original_actions
        BEGIN
            SELECT RAISE(ABORT, 'exit original actions are immutable');
        END;
        CREATE TRIGGER IF NOT EXISTS trg_exit_original_actions_no_delete
        BEFORE DELETE ON exit_original_actions
        BEGIN
            SELECT RAISE(ABORT, 'exit original actions are immutable');
        END;
        CREATE TRIGGER IF NOT EXISTS trg_exit_judgment_versions_no_update
        BEFORE UPDATE ON exit_judgment_versions
        BEGIN
            SELECT RAISE(ABORT, 'exit judgment versions are immutable');
        END;
        CREATE TRIGGER IF NOT EXISTS trg_exit_judgment_versions_no_delete
        BEFORE DELETE ON exit_judgment_versions
        BEGIN
            SELECT RAISE(ABORT, 'exit judgment versions are immutable');
        END;
        CREATE TRIGGER IF NOT EXISTS trg_exit_review_reveals_no_update
        BEFORE UPDATE ON exit_review_reveals
        BEGIN
            SELECT RAISE(ABORT, 'exit review reveals are immutable');
        END;
        CREATE TRIGGER IF NOT EXISTS trg_exit_review_reveals_no_delete
        BEFORE DELETE ON exit_review_reveals
        BEGIN
            SELECT RAISE(ABORT, 'exit review reveals are immutable');
        END;

        COMMIT;
        """
    )


def migrate_to_v16(conn) -> None:
    conn.executescript(
        """
        BEGIN IMMEDIATE;

        CREATE TABLE IF NOT EXISTS exit_behavior_experiments (
            experiment_id TEXT PRIMARY KEY,
            setup_version_id TEXT NOT NULL
                REFERENCES setup_versions(setup_version_id),
            grouping_version_id TEXT NOT NULL
                REFERENCES episode_grouping_versions(grouping_version_id),
            direction TEXT NOT NULL CHECK (direction IN ('LONG', 'SHORT')),
            status TEXT NOT NULL CHECK (status IN ('COMPLETED', 'FAILED')),
            failure_code TEXT,
            result_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            CHECK (
                (status='COMPLETED' AND failure_code IS NULL)
                OR (status='FAILED' AND failure_code IS NOT NULL)
            )
        );
        CREATE INDEX IF NOT EXISTS idx_exit_behavior_experiments_context
            ON exit_behavior_experiments(
                setup_version_id, grouping_version_id, direction, created_at
            );

        CREATE TABLE IF NOT EXISTS exit_behavior_model_versions (
            model_version_id TEXT PRIMARY KEY,
            experiment_id TEXT NOT NULL UNIQUE
                REFERENCES exit_behavior_experiments(experiment_id),
            setup_version_id TEXT NOT NULL
                REFERENCES setup_versions(setup_version_id),
            grouping_version_id TEXT NOT NULL
                REFERENCES episode_grouping_versions(grouping_version_id),
            direction TEXT NOT NULL CHECK (direction IN ('LONG', 'SHORT')),
            maturity TEXT NOT NULL CHECK (
                maturity IN ('EXPLORATORY', 'FORMAL')
            ),
            training_cutoff_utc_ms INTEGER NOT NULL,
            label_fingerprint TEXT NOT NULL,
            model_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_exit_behavior_models_context
            ON exit_behavior_model_versions(
                setup_version_id, grouping_version_id, direction, created_at
            );

        CREATE TRIGGER IF NOT EXISTS trg_exit_behavior_model_requires_experiment
        BEFORE INSERT ON exit_behavior_model_versions
        WHEN NOT EXISTS (
            SELECT 1
            FROM exit_behavior_experiments AS experiment
            WHERE experiment.experiment_id=NEW.experiment_id
              AND experiment.status='COMPLETED'
              AND experiment.setup_version_id=NEW.setup_version_id
              AND experiment.grouping_version_id=NEW.grouping_version_id
              AND experiment.direction=NEW.direction
        )
        BEGIN
            SELECT RAISE(
                ABORT,
                'exit behavior model requires its matching completed experiment'
            );
        END;

        CREATE TRIGGER IF NOT EXISTS trg_exit_behavior_experiments_no_update
        BEFORE UPDATE ON exit_behavior_experiments
        BEGIN
            SELECT RAISE(ABORT, 'exit behavior experiments are immutable');
        END;
        CREATE TRIGGER IF NOT EXISTS trg_exit_behavior_experiments_no_delete
        BEFORE DELETE ON exit_behavior_experiments
        BEGIN
            SELECT RAISE(ABORT, 'exit behavior experiments are immutable');
        END;
        CREATE TRIGGER IF NOT EXISTS trg_exit_behavior_models_no_update
        BEFORE UPDATE ON exit_behavior_model_versions
        BEGIN
            SELECT RAISE(ABORT, 'exit behavior model versions are immutable');
        END;
        CREATE TRIGGER IF NOT EXISTS trg_exit_behavior_models_no_delete
        BEFORE DELETE ON exit_behavior_model_versions
        BEGIN
            SELECT RAISE(ABORT, 'exit behavior model versions are immutable');
        END;

        COMMIT;
        """
    )


def migrate_to_v17(conn) -> None:
    """Add immutable exit-candidate scans and their formal-batch audit links."""

    conn.executescript(
        """
        BEGIN IMMEDIATE;

        CREATE TABLE IF NOT EXISTS exit_candidate_scans (
            scan_id TEXT PRIMARY KEY,
            setup_version_id TEXT NOT NULL
                REFERENCES setup_versions(setup_version_id),
            grouping_version_id TEXT NOT NULL
                REFERENCES episode_grouping_versions(grouping_version_id),
            direction TEXT NOT NULL CHECK (direction IN ('LONG', 'SHORT')),
            formula_version TEXT NOT NULL,
            feature_version TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('NOT_READY', 'COMPLETED')),
            result_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_exit_candidate_scans_context
            ON exit_candidate_scans(
                setup_version_id, grouping_version_id, direction, created_at
            );
        CREATE INDEX IF NOT EXISTS idx_exit_decision_events_candidate_context
            ON exit_decision_events(
                setup_version_id, grouping_version_id, direction,
                decision_cutoff_utc_ms, decision_event_id
            );

        CREATE TABLE IF NOT EXISTS exit_candidate_scores (
            scan_id TEXT NOT NULL REFERENCES exit_candidate_scans(scan_id),
            decision_event_id TEXT NOT NULL
                REFERENCES exit_decision_events(decision_event_id),
            holding_episode_id TEXT NOT NULL,
            similarity REAL NOT NULL CHECK (similarity BETWEEN 0 AND 100),
            completeness_ratio REAL NOT NULL CHECK (
                completeness_ratio BETWEEN 0 AND 1
            ),
            references_json TEXT NOT NULL,
            diversity_vector_json TEXT NOT NULL,
            enqueue_reason TEXT NOT NULL CHECK (
                enqueue_reason='STRUCTURAL_SIMILARITY'
            ),
            PRIMARY KEY (scan_id, decision_event_id)
        );
        CREATE INDEX IF NOT EXISTS idx_exit_candidate_scores_rank
            ON exit_candidate_scores(
                scan_id, similarity DESC, decision_event_id
            );
        CREATE INDEX IF NOT EXISTS idx_exit_candidate_scores_holding_episode
            ON exit_candidate_scores(
                scan_id, holding_episode_id, decision_event_id
            );

        CREATE TABLE IF NOT EXISTS exit_candidate_batches (
            batch_id TEXT PRIMARY KEY REFERENCES exit_review_batches(batch_id),
            scan_id TEXT NOT NULL REFERENCES exit_candidate_scans(scan_id),
            high_similarity_count INTEGER NOT NULL CHECK (
                high_similarity_count >= 0
            ),
            diverse_count INTEGER NOT NULL CHECK (diverse_count >= 0),
            created_at TEXT NOT NULL,
            UNIQUE (batch_id, scan_id)
        );
        CREATE TABLE IF NOT EXISTS exit_candidate_batch_items (
            batch_id TEXT NOT NULL REFERENCES exit_candidate_batches(batch_id),
            scan_id TEXT NOT NULL,
            decision_event_id TEXT NOT NULL UNIQUE
                REFERENCES exit_decision_events(decision_event_id),
            selection_reason TEXT NOT NULL CHECK (
                selection_reason IN ('HIGH_SIMILARITY', 'STRUCTURAL_DIVERSITY')
            ),
            PRIMARY KEY (batch_id, decision_event_id),
            FOREIGN KEY (batch_id, scan_id)
                REFERENCES exit_candidate_batches(batch_id, scan_id),
            FOREIGN KEY (scan_id, decision_event_id)
                REFERENCES exit_candidate_scores(scan_id, decision_event_id)
        );
        CREATE INDEX IF NOT EXISTS idx_exit_candidate_batch_scan
            ON exit_candidate_batch_items(scan_id, decision_event_id);

        CREATE TABLE IF NOT EXISTS exit_candidate_exclusions (
            setup_version_id TEXT NOT NULL
                REFERENCES setup_versions(setup_version_id),
            grouping_version_id TEXT NOT NULL
                REFERENCES episode_grouping_versions(grouping_version_id),
            decision_event_id TEXT PRIMARY KEY
                REFERENCES exit_decision_events(decision_event_id),
            reason TEXT NOT NULL CHECK (reason='FREE_BROWSE_REVEAL'),
            created_at TEXT NOT NULL,
            UNIQUE (setup_version_id, grouping_version_id, decision_event_id)
        );

        CREATE TRIGGER IF NOT EXISTS trg_exit_candidate_batch_not_excluded
        BEFORE INSERT ON exit_candidate_batch_items
        WHEN EXISTS (
            SELECT 1 FROM exit_candidate_exclusions AS exclusion
            WHERE exclusion.decision_event_id=NEW.decision_event_id
        )
        BEGIN
            SELECT RAISE(
                ABORT,
                'free-browse exit candidate cannot enter a formal batch'
            );
        END;
        CREATE TRIGGER IF NOT EXISTS trg_exit_candidate_exclusion_not_batched
        BEFORE INSERT ON exit_candidate_exclusions
        WHEN EXISTS (
            SELECT 1 FROM exit_candidate_batch_items AS item
            WHERE item.decision_event_id=NEW.decision_event_id
        )
        BEGIN
            SELECT RAISE(
                ABORT,
                'formal exit candidate cannot enter free browse'
            );
        END;

        CREATE TRIGGER IF NOT EXISTS trg_exit_candidate_scans_no_update
        BEFORE UPDATE ON exit_candidate_scans
        BEGIN
            SELECT RAISE(ABORT, 'exit candidate scans are immutable');
        END;
        CREATE TRIGGER IF NOT EXISTS trg_exit_candidate_scans_no_delete
        BEFORE DELETE ON exit_candidate_scans
        BEGIN
            SELECT RAISE(ABORT, 'exit candidate scans are immutable');
        END;
        CREATE TRIGGER IF NOT EXISTS trg_exit_candidate_scores_no_update
        BEFORE UPDATE ON exit_candidate_scores
        BEGIN
            SELECT RAISE(ABORT, 'exit candidate scores are immutable');
        END;
        CREATE TRIGGER IF NOT EXISTS trg_exit_candidate_scores_no_delete
        BEFORE DELETE ON exit_candidate_scores
        BEGIN
            SELECT RAISE(ABORT, 'exit candidate scores are immutable');
        END;
        CREATE TRIGGER IF NOT EXISTS trg_exit_candidate_batches_no_update
        BEFORE UPDATE ON exit_candidate_batches
        BEGIN
            SELECT RAISE(ABORT, 'exit candidate batches are immutable');
        END;
        CREATE TRIGGER IF NOT EXISTS trg_exit_candidate_batches_no_delete
        BEFORE DELETE ON exit_candidate_batches
        BEGIN
            SELECT RAISE(ABORT, 'exit candidate batches are immutable');
        END;
        CREATE TRIGGER IF NOT EXISTS trg_exit_candidate_batch_items_no_update
        BEFORE UPDATE ON exit_candidate_batch_items
        BEGIN
            SELECT RAISE(ABORT, 'exit candidate batch items are immutable');
        END;
        CREATE TRIGGER IF NOT EXISTS trg_exit_candidate_batch_items_no_delete
        BEFORE DELETE ON exit_candidate_batch_items
        BEGIN
            SELECT RAISE(ABORT, 'exit candidate batch items are immutable');
        END;
        CREATE TRIGGER IF NOT EXISTS trg_exit_candidate_exclusions_no_update
        BEFORE UPDATE ON exit_candidate_exclusions
        BEGIN
            SELECT RAISE(ABORT, 'exit candidate exclusions are immutable');
        END;
        CREATE TRIGGER IF NOT EXISTS trg_exit_candidate_exclusions_no_delete
        BEFORE DELETE ON exit_candidate_exclusions
        BEGIN
            SELECT RAISE(ABORT, 'exit candidate exclusions are immutable');
        END;

        COMMIT;
        """
    )


def migrate_to_v18(conn) -> None:
    """Add immutable, content-addressed decision-research snapshots."""

    conn.executescript(
        """
        BEGIN IMMEDIATE;

        CREATE TABLE IF NOT EXISTS research_snapshots (
            snapshot_id TEXT PRIMARY KEY,
            content_hash TEXT NOT NULL UNIQUE CHECK (length(content_hash)=64),
            setup_version_id TEXT NOT NULL
                REFERENCES setup_versions(setup_version_id),
            episode_version TEXT NOT NULL
                REFERENCES episode_grouping_versions(grouping_version_id),
            direction TEXT NOT NULL CHECK (direction IN ('LONG', 'SHORT')),
            decision_timeframe TEXT NOT NULL,
            context_timeframe_one TEXT NOT NULL,
            context_timeframe_two TEXT NOT NULL,
            data_version TEXT NOT NULL,
            label_version TEXT NOT NULL,
            formula_version TEXT NOT NULL,
            feature_version TEXT NOT NULL,
            model_version_ids_json TEXT NOT NULL,
            matched_research_ids_json TEXT NOT NULL,
            application_version TEXT NOT NULL,
            random_seed INTEGER NOT NULL,
            data_start_utc_ms INTEGER NOT NULL,
            data_end_utc_ms INTEGER NOT NULL,
            manifest_json TEXT NOT NULL,
            published_relative_path TEXT NOT NULL,
            created_at TEXT NOT NULL,
            CHECK (data_start_utc_ms <= data_end_utc_ms)
        );
        CREATE INDEX IF NOT EXISTS idx_research_snapshots_context
            ON research_snapshots(
                setup_version_id, direction, created_at, snapshot_id
            );

        CREATE TRIGGER IF NOT EXISTS trg_research_snapshots_no_update
        BEFORE UPDATE ON research_snapshots
        BEGIN
            SELECT RAISE(ABORT, 'research snapshots are immutable');
        END;
        CREATE TRIGGER IF NOT EXISTS trg_research_snapshots_no_delete
        BEFORE DELETE ON research_snapshots
        BEGIN
            SELECT RAISE(ABORT, 'research snapshots are immutable');
        END;

        COMMIT;
        """
    )


def migrate_to_v19(conn) -> None:
    """Add immutable matched EXIT_NOW/HOLD outcome comparisons."""

    conn.executescript(
        """
        BEGIN IMMEDIATE;

        CREATE TABLE IF NOT EXISTS exit_outcome_comparisons (
            comparison_id TEXT PRIMARY KEY,
            setup_version_id TEXT NOT NULL
                REFERENCES setup_versions(setup_version_id),
            grouping_version_id TEXT NOT NULL
                REFERENCES episode_grouping_versions(grouping_version_id),
            direction TEXT NOT NULL CHECK (direction IN ('LONG', 'SHORT')),
            formula_version TEXT NOT NULL,
            feature_version TEXT NOT NULL,
            input_feature_fingerprint TEXT NOT NULL CHECK (
                length(input_feature_fingerprint)=64
            ),
            random_seed INTEGER NOT NULL,
            result_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_exit_outcomes_context
            ON exit_outcome_comparisons(
                setup_version_id, grouping_version_id, direction, created_at
            );

        CREATE TABLE IF NOT EXISTS exit_outcome_matches (
            comparison_id TEXT NOT NULL
                REFERENCES exit_outcome_comparisons(comparison_id),
            similarity_threshold REAL NOT NULL CHECK (
                similarity_threshold BETWEEN 0 AND 100
            ),
            exit_now_decision_event_id TEXT NOT NULL
                REFERENCES exit_decision_events(decision_event_id),
            hold_decision_event_id TEXT NOT NULL
                REFERENCES exit_decision_events(decision_event_id),
            exit_now_episode_id TEXT NOT NULL,
            hold_episode_id TEXT NOT NULL,
            symbol TEXT NOT NULL,
            decision_timeframe TEXT NOT NULL,
            similarity REAL NOT NULL CHECK (similarity BETWEEN 0 AND 100),
            context_distance REAL NOT NULL CHECK (
                context_distance BETWEEN 0 AND 1
            ),
            PRIMARY KEY (
                comparison_id, similarity_threshold,
                exit_now_decision_event_id
            ),
            UNIQUE (
                comparison_id, similarity_threshold,
                hold_decision_event_id
            )
        );
        CREATE INDEX IF NOT EXISTS idx_exit_outcome_matches_threshold
            ON exit_outcome_matches(
                comparison_id, similarity_threshold, similarity DESC
            );

        CREATE TRIGGER IF NOT EXISTS trg_exit_outcome_comparisons_no_update
        BEFORE UPDATE ON exit_outcome_comparisons
        BEGIN
            SELECT RAISE(ABORT, 'exit outcome comparisons are immutable');
        END;
        CREATE TRIGGER IF NOT EXISTS trg_exit_outcome_comparisons_no_delete
        BEFORE DELETE ON exit_outcome_comparisons
        BEGIN
            SELECT RAISE(ABORT, 'exit outcome comparisons are immutable');
        END;
        CREATE TRIGGER IF NOT EXISTS trg_exit_outcome_matches_no_update
        BEFORE UPDATE ON exit_outcome_matches
        BEGIN
            SELECT RAISE(ABORT, 'exit outcome matches are immutable');
        END;
        CREATE TRIGGER IF NOT EXISTS trg_exit_outcome_matches_no_delete
        BEFORE DELETE ON exit_outcome_matches
        BEGIN
            SELECT RAISE(ABORT, 'exit outcome matches are immutable');
        END;

        COMMIT;
        """
    )
