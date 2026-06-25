from __future__ import annotations

import csv
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse
from typing import Any

REQUIRED_MANIFEST_FIELDS = (
    "experiment_id",
    "created_at",
    "app_version",
    "symbol",
    "interval",
    "data_start",
    "data_end",
    "data_hash",
    "annotation_version",
    "feature_version",
    "label_version",
    "feature_cols",
    "feature_timing_policy",
    "allow_confirmation_bar",
    "split_method",
    "split_summary",
    "train_count",
    "validation_count",
    "test_count",
    "unlabeled_scored_count",
    "purged_count",
    "embargoed_count",
    "episode_leakage_count",
    "embargo_bars",
    "model_type",
    "model_params",
    "threshold_tuning_metric",
    "selected_threshold",
    "validation_metrics",
    "frozen_test_metrics",
    "review_queue_config",
    "metrics",
    "artifact_paths",
    "warnings",
)
SENSITIVE_KEY_TOKENS = ("api_key", "apikey", "secret", "token", "password", "private_key")


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def create_experiment_id(config: dict[str, Any]) -> str:
    if not isinstance(config, dict):
        raise ValueError("config must be a mapping")
    _reject_sensitive_fields(config)
    digest = hashlib.sha256(_canonical_json(config).encode("utf-8")).hexdigest()[:16]
    return f"entry_exp_{digest}"


def _reject_sensitive_fields(value: Any, path: str = "manifest") -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            key_text = str(key).lower()
            if any(token in key_text for token in SENSITIVE_KEY_TOKENS):
                raise ValueError(f"Sensitive field is not allowed in experiment manifest: {path}.{key}")
            _reject_sensitive_fields(nested, f"{path}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _reject_sensitive_fields(nested, f"{path}[{index}]")


def _validate_artifact_paths(artifacts: dict[str, str]) -> dict[str, str]:
    if not isinstance(artifacts, dict):
        raise ValueError("artifacts must be a mapping")
    safe: dict[str, str] = {}
    for name, raw_path in artifacts.items():
        value = str(raw_path)
        parsed = urlparse(value)
        if parsed.scheme or Path(value).is_absolute():
            raise ValueError(f"artifact_paths must be relative: {name}")
        safe[str(name)] = value.replace("\\", "/")
    return safe


def _normalized_split_summary(config: dict[str, Any], metrics: dict[str, Any]) -> dict[str, Any]:
    raw = config.get("split_summary") or metrics.get("split_summary") or {}
    if not isinstance(raw, dict):
        raw = {}
    return {
        "split_method": raw.get("split_method") or raw.get("method") or _nested(config, "split_config", "method"),
        "train_count": int(raw.get("train_count", raw.get("train", 0)) or 0),
        "validation_count": int(raw.get("validation_count", raw.get("val_count", raw.get("val", 0))) or 0),
        "test_count": int(raw.get("test_count", raw.get("test", 0)) or 0),
        "unlabeled_scored_count": int(raw.get("unlabeled_scored_count", metrics.get("unlabeled_scored_count", 0)) or 0),
        "purged_count": int(raw.get("purged_count", 0) or 0),
        "embargoed_count": int(raw.get("embargoed_count", 0) or 0),
        "episode_leakage_count": int(raw.get("episode_leakage_count", 0) or 0),
        "horizon_bars": raw.get("horizon_bars") or _nested(config, "split_config", "horizon_bars"),
        "embargo_bars": raw.get("embargo_bars", config.get("embargo_bars", _nested(config, "split_config", "embargo_bars"))),
    }


def _nested(mapping: dict[str, Any], key: str, nested_key: str) -> Any:
    value = mapping.get(key)
    return value.get(nested_key) if isinstance(value, dict) else None


def _threshold_selection(metrics: dict[str, Any]) -> dict[str, Any]:
    value = metrics.get("threshold_selection") or {}
    return value if isinstance(value, dict) else {}


def _validation_metrics(metrics: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    explicit = config.get("validation_metrics") or metrics.get("validation_metrics")
    if isinstance(explicit, dict):
        return dict(explicit)
    selection = _threshold_selection(metrics)
    return {str(key): value for key, value in selection.items() if str(key).startswith("validation_")}


def _frozen_test_metrics(metrics: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    explicit = config.get("frozen_test_metrics") or metrics.get("frozen_test_metrics") or metrics.get("test_metrics")
    if isinstance(explicit, dict):
        return dict(explicit)
    return {str(key): value for key, value in metrics.items() if str(key).startswith("test_") or str(key).startswith("score_distribution")}


def _selected_threshold(config: dict[str, Any], metrics: dict[str, Any]) -> Any:
    if "selected_threshold" in config:
        return config.get("selected_threshold")
    if "threshold" in config:
        return config.get("threshold")
    return _threshold_selection(metrics).get("selected_threshold")


def _threshold_tuning_metric(config: dict[str, Any]) -> str | None:
    return (
        config.get("threshold_tuning_metric")
        or _nested(config, "model_config", "threshold_metric")
        or _nested(config, "model_params", "threshold_metric")
        or _nested(config, "model_config", "metric")
    )

def save_experiment_manifest(
    path: str | Path,
    config: dict[str, Any],
    metrics: dict[str, Any],
    artifacts: dict[str, str],
) -> dict[str, Any]:
    if not isinstance(config, dict):
        raise ValueError("config must be a mapping")
    _reject_sensitive_fields(config, "config")
    _reject_sensitive_fields(metrics, "metrics")
    metrics_payload = dict(metrics or {})
    safe_artifacts = _validate_artifact_paths(artifacts or {})
    split_summary = _normalized_split_summary(config, metrics_payload)
    validation_metrics = _validation_metrics(metrics_payload, config)
    frozen_test_metrics = _frozen_test_metrics(metrics_payload, config)
    selected_threshold = _selected_threshold(config, metrics_payload)
    threshold_tuning_metric = _threshold_tuning_metric(config)
    model_params = dict(config.get("model_params") or {})
    if not model_params and isinstance(config.get("model_config"), dict):
        model_params = dict(config.get("model_config") or {})
    manifest = {
        "experiment_id": config.get("experiment_id") or create_experiment_id(config),
        "created_at": config.get("created_at") or datetime.now(UTC).isoformat(timespec="seconds"),
        "app_version": config.get("app_version"),
        "symbol": config.get("symbol"),
        "interval": config.get("interval"),
        "data_start": config.get("data_start"),
        "data_end": config.get("data_end"),
        "data_hash": config.get("data_hash"),
        "annotation_version": config.get("annotation_version"),
        "feature_version": config.get("feature_version"),
        "label_version": config.get("label_version"),
        "feature_cols": list(config.get("feature_cols") or []),
        "feature_timing_policy": config.get("feature_timing_policy") or _nested(config, "feature_spec", "feature_timing_policy"),
        "allow_confirmation_bar": config.get("allow_confirmation_bar", _nested(config, "feature_spec", "allow_confirmation_bar")),
        "split_method": config.get("split_method") or split_summary.get("split_method") or _nested(config, "split_config", "method"),
        "split_summary": split_summary,
        "train_count": split_summary.get("train_count", 0),
        "validation_count": split_summary.get("validation_count", 0),
        "test_count": split_summary.get("test_count", 0),
        "unlabeled_scored_count": split_summary.get("unlabeled_scored_count", metrics_payload.get("unlabeled_scored_count", 0)),
        "purged_count": split_summary.get("purged_count", 0),
        "embargoed_count": split_summary.get("embargoed_count", 0),
        "episode_leakage_count": split_summary.get("episode_leakage_count", 0),
        "embargo_bars": split_summary.get("embargo_bars", config.get("embargo_bars")),
        "model_type": config.get("model_type") or _nested(config, "model_config", "model_type"),
        "model_params": model_params,
        "threshold_tuning_metric": threshold_tuning_metric,
        "selected_threshold": selected_threshold,
        "validation_metrics": validation_metrics,
        "frozen_test_metrics": frozen_test_metrics,
        "review_queue_config": dict(config.get("review_queue_config") or {}),
        "metrics": metrics_payload,
        "artifact_paths": safe_artifacts,
        "warnings": list(config.get("warnings") or []),
    }
    for optional_field in (
        "data_version",
        "data_hash",
        "data_hash_algorithm",
        "quality_status",
        "quality_warnings",
        "label_version",
        "split_config",
        "model_config",
        "threshold",
        "git_commit",
        "annotation_counts",
        "experiment_note",
    ):
        if optional_field in config:
            manifest[optional_field] = config.get(optional_field)
    validate_experiment_manifest(manifest)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return manifest


def load_experiment_manifest(path: str | Path, *, check_artifacts: bool = False) -> dict[str, Any]:
    target = _manifest_path(path)
    manifest = json.loads(target.read_text(encoding="utf-8"))
    validate_experiment_manifest(manifest)
    if check_artifacts:
        manifest = _with_artifact_warnings(manifest, target.parent)
    return manifest


def save_experiment_bundle(
    root_dir: str | Path,
    config: dict[str, Any],
    metrics: dict[str, Any] | None = None,
    *,
    report_markdown: str = "",
    review_queue: list[dict[str, Any]] | None = None,
    feature_quality: dict[str, Any] | None = None,
    split_summary: dict[str, Any] | None = None,
    warnings: list[str] | None = None,
    note: str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    """Save a complete, reproducible entry logic experiment directory."""
    if not isinstance(config, dict):
        raise ValueError("config must be a mapping")
    metrics_payload = dict(metrics or {})
    warning_payload = list(warnings or config.get("warnings") or [])
    bundle_config = dict(config)
    experiment_id = str(bundle_config.get("experiment_id") or create_experiment_id(config))
    created = str(created_at or bundle_config.get("created_at") or datetime.now(UTC).isoformat(timespec="seconds"))
    bundle_config["experiment_id"] = experiment_id
    bundle_config["created_at"] = created
    bundle_config["warnings"] = warning_payload
    if note is not None:
        bundle_config["experiment_note"] = str(note)

    experiment_dir = _experiment_directory(root_dir, created, experiment_id)
    experiment_dir.mkdir(parents=True, exist_ok=True)

    feature_quality_payload = dict(feature_quality or {})
    split_summary_payload = dict(split_summary or metrics_payload.get("split_summary") or {})
    review_queue_payload = list(review_queue or [])
    bundle_config.setdefault("split_summary", split_summary_payload)
    if "feature_timing_policy" in feature_quality_payload:
        bundle_config.setdefault("feature_timing_policy", feature_quality_payload.get("feature_timing_policy"))
    if "allow_confirmation_bar" in feature_quality_payload:
        bundle_config.setdefault("allow_confirmation_bar", feature_quality_payload.get("allow_confirmation_bar"))

    _write_json(experiment_dir / "metrics.json", metrics_payload)
    (experiment_dir / "report.md").write_text(str(report_markdown or "# Entry Logic Experiment\n"), encoding="utf-8")
    _write_review_queue_csv(experiment_dir / "review_queue.csv", review_queue_payload)
    _write_json(experiment_dir / "feature_quality.json", feature_quality_payload)
    _write_json(experiment_dir / "split_summary.json", split_summary_payload)
    _write_json(experiment_dir / "warnings.json", {"warnings": warning_payload})

    artifacts = {
        "metrics": "metrics.json",
        "report": "report.md",
        "review_queue": "review_queue.csv",
        "feature_quality": "feature_quality.json",
        "split_summary": "split_summary.json",
        "warnings": "warnings.json",
    }
    manifest = save_experiment_manifest(experiment_dir / "manifest.json", bundle_config, metrics_payload, artifacts)
    return {
        "experiment_dir": experiment_dir,
        "manifest_path": experiment_dir / "manifest.json",
        "manifest": manifest,
    }


def load_latest_experiment(root_dir: str | Path, *, check_artifacts: bool = False) -> dict[str, Any]:
    root = Path(root_dir)
    experiments_root = root if root.name == "experiments" else root / "experiments"
    manifests = sorted(experiments_root.glob("*/manifest.json"))
    if not manifests:
        raise FileNotFoundError(f"No entry logic experiments found under {experiments_root}")
    loaded = [load_experiment_manifest(path, check_artifacts=check_artifacts) for path in manifests]
    loaded.sort(key=lambda item: (str(item.get("created_at") or ""), str(item.get("experiment_id") or "")))
    return loaded[-1]


def compare_experiments(a: str | Path | dict[str, Any], b: str | Path | dict[str, Any]) -> dict[str, Any]:
    first = a if isinstance(a, dict) else load_experiment_manifest(a, check_artifacts=True)
    second = b if isinstance(b, dict) else load_experiment_manifest(b, check_artifacts=True)
    first_counts = _annotation_counts(first)
    second_counts = _annotation_counts(second)
    first_metrics = _numeric_metrics(first.get("metrics") or {})
    second_metrics = _numeric_metrics(second.get("metrics") or {})
    metric_keys = sorted(set(first_metrics) | set(second_metrics))
    return {
        "experiment_id_a": first.get("experiment_id"),
        "experiment_id_b": second.get("experiment_id"),
        "same_data": bool(first.get("data_hash") and first.get("data_hash") == second.get("data_hash")),
        "data_hash_a": first.get("data_hash"),
        "data_hash_b": second.get("data_hash"),
        "annotation_count_delta": {
            key: int(second_counts.get(key, 0) - first_counts.get(key, 0))
            for key in sorted(set(first_counts) | set(second_counts))
        },
        "feature_version_changed": first.get("feature_version") != second.get("feature_version"),
        "feature_version_a": first.get("feature_version"),
        "feature_version_b": second.get("feature_version"),
        "split_changed": _split_signature(first) != _split_signature(second),
        "metrics_delta": {
            key: float(second_metrics.get(key, 0.0) - first_metrics.get(key, 0.0))
            for key in metric_keys
        },
        "warnings": [
            *[f"a:{warning}" for warning in first.get("warnings", [])],
            *[f"b:{warning}" for warning in second.get("warnings", [])],
        ],
    }


def _experiment_directory(root_dir: str | Path, created_at: str, experiment_id: str) -> Path:
    root = Path(root_dir)
    experiments_root = root if root.name == "experiments" else root / "experiments"
    date = _created_date(created_at)
    return experiments_root / f"{date}_{experiment_id}"


def _created_date(created_at: str) -> str:
    text = str(created_at or "")
    if len(text) >= 10:
        return text[:10]
    return datetime.now(UTC).date().isoformat()


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str), encoding="utf-8")


def _write_review_queue_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            name = str(key)
            if name not in fieldnames:
                fieldnames.append(name)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames or ["observation_id"])
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in fieldnames})


def _manifest_path(path: str | Path) -> Path:
    target = Path(path)
    return target / "manifest.json" if target.is_dir() else target


def _with_artifact_warnings(manifest: dict[str, Any], directory: Path) -> dict[str, Any]:
    checked = dict(manifest)
    warnings = list(checked.get("warnings") or [])
    for name, raw_path in (checked.get("artifact_paths") or {}).items():
        artifact_path = directory / str(raw_path)
        if not artifact_path.exists():
            warning = f"missing_artifact:{name}:{raw_path}"
            if warning not in warnings:
                warnings.append(warning)
    checked["warnings"] = warnings
    return checked


def _annotation_counts(manifest: dict[str, Any]) -> dict[str, int]:
    raw = manifest.get("annotation_counts") or manifest.get("metrics", {}).get("annotation_counts") or {}
    if not isinstance(raw, dict):
        return {}
    return {str(key): int(value or 0) for key, value in raw.items()}


def _numeric_metrics(metrics: dict[str, Any]) -> dict[str, float]:
    result: dict[str, float] = {}
    for key, value in metrics.items():
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)) and value is not None:
            result[str(key)] = float(value)
    return result


def _split_signature(manifest: dict[str, Any]) -> Any:
    return manifest.get("split_config") or {
        "split_method": manifest.get("split_method"),
        "embargo_bars": manifest.get("embargo_bars"),
    }
def validate_experiment_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(manifest, dict):
        raise ValueError("manifest must be a mapping")
    missing = [field for field in REQUIRED_MANIFEST_FIELDS if field not in manifest]
    if missing:
        raise ValueError(f"Missing experiment manifest fields: {', '.join(missing)}")
    _reject_sensitive_fields(manifest)
    _validate_artifact_paths(manifest["artifact_paths"])
    return manifest


__all__ = [
    "compare_experiments",
    "create_experiment_id",
    "load_experiment_manifest",
    "load_latest_experiment",
    "save_experiment_bundle",
    "save_experiment_manifest",
    "validate_experiment_manifest",
]

