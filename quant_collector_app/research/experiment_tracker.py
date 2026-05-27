from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from .feature_registry import FEATURE_VERSION
from .label_registry import LABEL_VERSION


def dataset_hash(samples: pd.DataFrame) -> str:
    if samples is None or samples.empty:
        return hashlib.sha256(b"empty").hexdigest()
    stable = samples.copy()
    stable = stable.reindex(sorted(stable.columns), axis=1)
    if "event_id" in stable.columns:
        stable = stable.sort_values("event_id", kind="stable")
    payload = stable.to_csv(index=False, na_rep="NaN").encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def create_manifest(
    samples: pd.DataFrame,
    selected_label: str,
    generated_files: list[str],
    *,
    profile_id: str | None = None,
    profile_version: str | None = None,
    baseline_spec: dict | str | None = None,
    split_spec: dict | str | None = None,
) -> dict:
    time_values = pd.to_datetime(samples.get("event_time_bjt"), errors="coerce") if "event_time_bjt" in samples.columns else pd.Series(dtype="datetime64[ns]")
    baseline_spec_json = (
        json.dumps(baseline_spec, ensure_ascii=False, sort_keys=True)
        if isinstance(baseline_spec, dict)
        else baseline_spec
    )
    split_spec_json = (
        json.dumps(split_spec, ensure_ascii=False, sort_keys=True)
        if isinstance(split_spec, dict)
        else split_spec
    )
    return {
        "experiment_id": f"exp_{uuid.uuid4().hex}",
        "dataset_hash": dataset_hash(samples),
        "feature_version": FEATURE_VERSION,
        "label_version": LABEL_VERSION,
        "profile_id": profile_id,
        "profile_version": profile_version,
        "baseline_spec_json": baseline_spec_json,
        "split_spec_json": split_spec_json,
        "symbols": sorted(samples.get("symbol", pd.Series(dtype=str)).dropna().astype(str).unique().tolist()),
        "intervals": sorted(samples.get("interval", pd.Series(dtype=str)).dropna().astype(str).unique().tolist()),
        "time_range": {
            "start": str(time_values.min()) if time_values.notna().any() else None,
            "end": str(time_values.max()) if time_values.notna().any() else None,
        },
        "sample_count": int(len(samples)),
        "selected_label": selected_label,
        "generated_files": sorted(generated_files),
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }


def write_manifest(
    output_dir: Path,
    samples: pd.DataFrame,
    selected_label: str,
    generated_files: list[str],
    *,
    profile_id: str | None = None,
    profile_version: str | None = None,
    baseline_spec: dict | str | None = None,
    split_spec: dict | str | None = None,
) -> dict:
    manifest = create_manifest(
        samples,
        selected_label,
        generated_files,
        profile_id=profile_id,
        profile_version=profile_version,
        baseline_spec=baseline_spec,
        split_spec=split_spec,
    )
    (Path(output_dir) / "research_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return manifest
