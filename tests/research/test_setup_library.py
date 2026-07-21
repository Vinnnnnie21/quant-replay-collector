from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import sqlite3

import pytest

from database_backup import run_database_integrity_check
from research.setups import (
    CreateSetup,
    CreateSetupVersion,
    DecisionProtocol,
    SetupDirection,
    SetupErrorCode,
    SetupLibrary,
    SetupPersistenceError,
    SetupValidationError,
    SetupVersionSpec,
    TimeframeProfile,
    recommend_timeframe_profile,
)
from storage import StorageManager


def test_create_setup_and_first_version_round_trip_with_stable_identity(tmp_path):
    path = tmp_path / "setup_library.db"
    library = SetupLibrary(StorageManager(path))
    request = CreateSetup(
        display_name="深 V 反转",
        version=SetupVersionSpec(
            direction=SetupDirection.LONG,
            decision_protocol=DecisionProtocol.CURRENT_BAR_CLOSE,
            decision_rules="区间低位出现长下影并收回前低。",
            timeframes=TimeframeProfile("5m", "15m", "1h"),
        ),
    )

    created = library.create_setup(request)
    reloaded = SetupLibrary(StorageManager(path)).get_version(
        created.version.setup_version_id
    )

    assert created.setup.display_name == "深 V 反转"
    assert created.version.version_number == 1
    assert reloaded == created.version
    assert reloaded.setup_id == created.setup.setup_id
    assert reloaded.direction is SetupDirection.LONG
    assert reloaded.decision_protocol is DecisionProtocol.CURRENT_BAR_CLOSE
    assert reloaded.decision_rules == "区间低位出现长下影并收回前低。"
    assert reloaded.timeframes == TimeframeProfile("5m", "15m", "1h")


def test_timeframe_recommendation_is_supported_and_invalid_order_is_explicit():
    assert recommend_timeframe_profile("5m") == TimeframeProfile(
        "5m",
        "15m",
        "1h",
    )

    with pytest.raises(SetupValidationError) as captured:
        TimeframeProfile("15m", "5m", "1h")

    assert captured.value.code is SetupErrorCode.TIMEFRAME_ORDER
    assert captured.value.field == "timeframes"


def test_semantic_change_creates_new_version_without_mutating_old_version(
    tmp_path,
):
    library = SetupLibrary(StorageManager(tmp_path / "immutable_setup.db"))
    created = library.create_setup(
        CreateSetup(
            display_name="突破回踩",
            version=SetupVersionSpec(
                direction=SetupDirection.LONG,
                decision_protocol=DecisionProtocol.CURRENT_BAR_CLOSE,
                decision_rules="收盘重新站上突破位。",
                timeframes=TimeframeProfile("5m", "15m", "1h"),
            ),
        )
    )

    changed = library.create_version(
        CreateSetupVersion(
            setup_id=created.setup.setup_id,
            based_on_version_id=created.version.setup_version_id,
            version=SetupVersionSpec(
                direction=SetupDirection.SHORT,
                decision_protocol=DecisionProtocol.NEXT_BAR_CONFIRMATION,
                decision_rules="跌破后等待下一根完整 K 线确认。",
                timeframes=TimeframeProfile("15m", "1h", "4h"),
            ),
        )
    )

    assert changed.version_number == 2
    assert changed.parent_version_id == created.version.setup_version_id
    assert changed.setup_version_id != created.version.setup_version_id
    assert library.get_version(created.version.setup_version_id) == (
        created.version
    )
    assert library.list_versions(created.setup.setup_id) == (
        created.version,
        changed,
    )


def test_identical_semantics_do_not_create_a_meaningless_version(tmp_path):
    library = SetupLibrary(StorageManager(tmp_path / "setup_noop_version.db"))
    created = library.create_setup(
        CreateSetup(
            display_name="不生成空版本",
            version=SetupVersionSpec(
                direction=SetupDirection.LONG,
                decision_protocol=DecisionProtocol.CURRENT_BAR_CLOSE,
                decision_rules="保持不变",
                timeframes=TimeframeProfile("5m", "15m", "1h"),
            ),
        )
    )

    with pytest.raises(SetupValidationError) as captured:
        library.create_version(
            CreateSetupVersion(
                setup_id=created.setup.setup_id,
                based_on_version_id=created.version.setup_version_id,
                version=created.version.spec,
            )
        )

    assert captured.value.code is SetupErrorCode.NO_SEMANTIC_CHANGE
    assert library.list_versions(created.setup.setup_id) == (created.version,)


def test_rename_and_archive_change_catalog_state_without_changing_history(
    tmp_path,
):
    library = SetupLibrary(StorageManager(tmp_path / "setup_catalog.db"))
    created = library.create_setup(
        CreateSetup(
            display_name="假突破",
            version=SetupVersionSpec(
                direction=SetupDirection.SHORT,
                decision_protocol=DecisionProtocol.CURRENT_BAR_CLOSE,
                decision_rules="区间上沿假突破后收回。",
                timeframes=TimeframeProfile("5m", "15m", "1h"),
            ),
        )
    )

    renamed = library.rename_setup(
        created.setup.setup_id,
        "区间上沿假突破",
    )
    archived = library.archive_setup(created.setup.setup_id)

    assert renamed.display_name == "区间上沿假突破"
    assert archived.is_archived is True
    assert library.get_setup(created.setup.setup_id) == archived
    assert library.get_version(created.version.setup_version_id) == (
        created.version
    )
    assert library.list_setups() == ()
    assert library.list_setups(include_archived=True) == (archived,)

    with pytest.raises(SetupValidationError) as captured:
        library.create_version(
            CreateSetupVersion(
                setup_id=created.setup.setup_id,
                based_on_version_id=created.version.setup_version_id,
                version=created.version.spec,
            )
        )

    assert captured.value.code is SetupErrorCode.SETUP_ARCHIVED


def test_renaming_to_same_display_name_is_a_noop(tmp_path):
    library = SetupLibrary(StorageManager(tmp_path / "setup_rename_noop.db"))
    created = library.create_setup(
        CreateSetup(
            display_name="名称不变",
            version=SetupVersionSpec(
                direction=SetupDirection.LONG,
                decision_protocol=DecisionProtocol.CURRENT_BAR_CLOSE,
                decision_rules="有效规则",
                timeframes=TimeframeProfile("5m", "15m", "1h"),
            ),
        )
    )

    unchanged = library.rename_setup(
        created.setup.setup_id,
        created.setup.display_name,
    )

    assert unchanged == created.setup


@pytest.mark.parametrize(
    ("factory", "code", "field"),
    (
        (
            lambda: CreateSetup(
                display_name=" ",
                version=SetupVersionSpec(
                    direction=SetupDirection.LONG,
                    decision_protocol=DecisionProtocol.CURRENT_BAR_CLOSE,
                    decision_rules="有效规则",
                    timeframes=TimeframeProfile("5m", "15m", "1h"),
                ),
            ),
            SetupErrorCode.INVALID_NAME,
            "display_name",
        ),
        (
            lambda: SetupVersionSpec(
                direction="BOTH",
                decision_protocol=DecisionProtocol.CURRENT_BAR_CLOSE,
                decision_rules="有效规则",
                timeframes=TimeframeProfile("5m", "15m", "1h"),
            ),
            SetupErrorCode.INVALID_DIRECTION,
            "direction",
        ),
        (
            lambda: SetupVersionSpec(
                direction=SetupDirection.LONG,
                decision_protocol="INTRABAR",
                decision_rules="有效规则",
                timeframes=TimeframeProfile("5m", "15m", "1h"),
            ),
            SetupErrorCode.INVALID_PROTOCOL,
            "decision_protocol",
        ),
        (
            lambda: SetupVersionSpec(
                direction=SetupDirection.LONG,
                decision_protocol=DecisionProtocol.CURRENT_BAR_CLOSE,
                decision_rules=" ",
                timeframes=TimeframeProfile("5m", "15m", "1h"),
            ),
            SetupErrorCode.INVALID_RULES,
            "decision_rules",
        ),
    ),
)
def test_invalid_setup_inputs_return_stable_domain_error_codes(
    factory,
    code,
    field,
):
    with pytest.raises(SetupValidationError) as captured:
        factory()

    assert captured.value.code is code
    assert captured.value.field == field


def test_first_version_failure_rolls_back_setup_and_returns_domain_error(
    tmp_path,
):
    storage = StorageManager(tmp_path / "setup_transaction.db")
    with storage.connect() as conn:
        conn.execute(
            """
            CREATE TRIGGER fail_setup_version_insert
            BEFORE INSERT ON setup_versions
            BEGIN
                SELECT RAISE(ABORT, 'forced setup version failure');
            END
            """
        )
    library = SetupLibrary(storage)

    with pytest.raises(SetupPersistenceError) as captured:
        library.create_setup(
            CreateSetup(
                display_name="事务失败样本",
                version=SetupVersionSpec(
                    direction=SetupDirection.LONG,
                    decision_protocol=DecisionProtocol.CURRENT_BAR_CLOSE,
                    decision_rules="有效规则",
                    timeframes=TimeframeProfile("5m", "15m", "1h"),
                ),
            )
        )

    assert captured.value.code is SetupErrorCode.PERSISTENCE
    assert storage.fetch_table("setups") == []
    assert storage.fetch_table("setup_versions") == []


def test_stale_concurrent_change_cannot_fork_setup_version_history(tmp_path):
    library = SetupLibrary(StorageManager(tmp_path / "setup_stale.db"))
    created = library.create_setup(
        CreateSetup(
            display_name="并发版本",
            version=SetupVersionSpec(
                direction=SetupDirection.LONG,
                decision_protocol=DecisionProtocol.CURRENT_BAR_CLOSE,
                decision_rules="初始规则",
                timeframes=TimeframeProfile("5m", "15m", "1h"),
            ),
        )
    )
    first_change = library.create_version(
        CreateSetupVersion(
            setup_id=created.setup.setup_id,
            based_on_version_id=created.version.setup_version_id,
            version=SetupVersionSpec(
                direction=SetupDirection.LONG,
                decision_protocol=DecisionProtocol.CURRENT_BAR_CLOSE,
                decision_rules="第一个并发修改",
                timeframes=TimeframeProfile("5m", "15m", "1h"),
            ),
        )
    )

    with pytest.raises(SetupValidationError) as captured:
        library.create_version(
            CreateSetupVersion(
                setup_id=created.setup.setup_id,
                based_on_version_id=created.version.setup_version_id,
                version=SetupVersionSpec(
                    direction=SetupDirection.SHORT,
                    decision_protocol=DecisionProtocol.CURRENT_BAR_CLOSE,
                    decision_rules="过期页面中的另一项修改",
                    timeframes=TimeframeProfile("5m", "15m", "1h"),
                ),
            )
        )

    assert captured.value.code is SetupErrorCode.STALE_VERSION
    assert library.list_versions(created.setup.setup_id) == (
        created.version,
        first_change,
    )


def test_concurrent_duplicate_create_is_idempotent(tmp_path):
    storage = StorageManager(tmp_path / "setup_duplicate.db")
    library = SetupLibrary(storage)
    request = CreateSetup(
        display_name="重复点击",
        version=SetupVersionSpec(
            direction=SetupDirection.LONG,
            decision_protocol=DecisionProtocol.CURRENT_BAR_CLOSE,
            decision_rules="同一提交只创建一次。",
            timeframes=TimeframeProfile("5m", "15m", "1h"),
        ),
    )

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = tuple(pool.map(lambda _index: library.create_setup(request), range(8)))

    assert len({item.setup.setup_id for item in results}) == 1
    assert len({item.version.setup_version_id for item in results}) == 1
    assert len(storage.fetch_table("setups")) == 1
    assert len(storage.fetch_table("setup_versions")) == 1


def test_creation_token_reuse_with_different_semantics_is_rejected(tmp_path):
    library = SetupLibrary(StorageManager(tmp_path / "setup_token_conflict.db"))
    original = CreateSetup(
        display_name="同一提交",
        version=SetupVersionSpec(
            direction=SetupDirection.LONG,
            decision_protocol=DecisionProtocol.CURRENT_BAR_CLOSE,
            decision_rules="原始规则",
            timeframes=TimeframeProfile("5m", "15m", "1h"),
        ),
        creation_token="setup_create_stable_request",
    )
    library.create_setup(original)

    with pytest.raises(SetupValidationError) as captured:
        library.create_setup(
            CreateSetup(
                display_name="被篡改的提交",
                version=SetupVersionSpec(
                    direction=SetupDirection.SHORT,
                    decision_protocol=DecisionProtocol.CURRENT_BAR_CLOSE,
                    decision_rules="不同规则",
                    timeframes=TimeframeProfile("15m", "1h", "4h"),
                ),
                creation_token=original.creation_token,
            )
        )

    assert captured.value.code is SetupErrorCode.IDEMPOTENCY_CONFLICT


def test_schema_v7_upgrade_adds_setup_tables_and_preserves_existing_rows(
    tmp_path,
):
    path = tmp_path / "schema_v7.db"
    backup_dir = tmp_path / "backups"
    legacy = StorageManager(path)
    legacy.upsert_session(
        {
            "session_id": "legacy_session",
            "symbol": "BTCUSDT",
            "interval": "5m",
        }
    )
    with sqlite3.connect(path) as conn:
        conn.execute("DROP TABLE setup_versions")
        conn.execute("DROP TABLE setups")
        conn.execute("PRAGMA user_version=7")

    upgraded = StorageManager(path, backup_dir=backup_dir)

    assert upgraded.schema_version() == StorageManager.SCHEMA_VERSION
    assert upgraded.get_session("legacy_session")["symbol"] == "BTCUSDT"
    assert upgraded.fetch_table("setups") == []
    assert upgraded.fetch_table("setup_versions") == []
    backups = tuple(
        backup_dir.glob(
            "quant_replay_pre_upgrade_v7_to_"
            f"v{StorageManager.SCHEMA_VERSION}_*.db"
        )
    )
    assert len(backups) == 1


def test_version_machine_export_uses_stable_english_ids_and_keys(tmp_path):
    library = SetupLibrary(StorageManager(tmp_path / "setup_export.db"))
    created = library.create_setup(
        CreateSetup(
            display_name="导出 Setup",
            version=SetupVersionSpec(
                direction=SetupDirection.SHORT,
                decision_protocol=DecisionProtocol.NEXT_BAR_CONFIRMATION,
                decision_rules="等待确认。",
                timeframes=TimeframeProfile("15m", "1h", "4h"),
            ),
        )
    )
    library.rename_setup(created.setup.setup_id, "修正后的显示名称")

    payload = library.export_version(
        created.version.setup_version_id
    ).to_dict()

    assert payload == {
        "setup_id": created.setup.setup_id,
        "setup_version_id": created.version.setup_version_id,
        "version_number": 1,
        "direction": "SHORT",
        "decision_protocol": "NEXT_BAR_CONFIRMATION",
        "decision_rules": "等待确认。",
        "decision_timeframe": "15m",
        "context_timeframe_one": "1h",
        "context_timeframe_two": "4h",
        "created_at": created.version.created_at,
    }


def test_database_integrity_audit_protects_setup_catalog_and_versions(
    tmp_path,
):
    path = tmp_path / "setup_integrity.db"
    library = SetupLibrary(StorageManager(path))
    library.create_setup(
        CreateSetup(
            display_name="备份审计",
            version=SetupVersionSpec(
                direction=SetupDirection.LONG,
                decision_protocol=DecisionProtocol.CURRENT_BAR_CLOSE,
                decision_rules="审计规则",
                timeframes=TimeframeProfile("5m", "15m", "1h"),
            ),
        )
    )

    report = run_database_integrity_check(
        path,
        expected_schema_version=StorageManager.SCHEMA_VERSION,
    )

    assert report["status"] == "ok"
    assert report["protected_table_counts"]["setups"] == 1
    assert report["protected_table_counts"]["setup_versions"] == 1
