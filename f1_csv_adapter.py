"""Canonical frames CSV -> F1FrameRecord adapter (Gate 1.9 engineering prototype, NOT APPROVED).

Connects one canonical ``frames-schema/1.0.0`` CSV to the existing, unchanged
F1 code:

    canonical CSV --analyze_d455.load_frames_csv--> typed rows
                  --f1_features.compute_f1_5_frame--> F1FrameResult (FEAT-009)
                  --> f1_sample_aggregator.F1FrameRecord

Value semantics (exact 60-field header, schema version, single
``(recording_id, analysis_run_id)``, lowercase ``true`` / ``false`` / empty
booleans, enums, ``frame_index``, empty cell -> ``None``, NaN/Infinity
rejected) are those of the existing canonical reader ``load_frames_csv``; this
module only adds the structural checks that reader does not perform (ragged
rows, header-only input, duplicate frame keys, empty identity text, one
subject/round per recording) and fails closed on them.

Nothing here computes geometry, applies a visibility / presence / ``D_sh`` /
``N_min`` / ``R_min`` threshold, fills a missing landmark or decides sample
eligibility.  A missing or invalid hip is a legitimate F1 diagnostic case, not
a malformed CSV.  The source file is only read.
"""

import contextlib
import csv
import io

import analyze_d455
from f1_features import compute_f1_5_frame
from f1_sample_aggregator import F1FrameRecord


# Non-frozen prototype label; not a schema or contract version.
F1_CSV_ADAPTER_ID = "f1-csv-adapter-prototype-gate1.9-unapproved"
SUPPORTED_FRAME_SCHEMA = analyze_d455.FRAME_SCHEMA_VERSION
CANONICAL_FRAME_FIELDS = analyze_d455.FRAME_FIELDS

# Proposed F1 sample key (f1_sample_aggregator; summary-schema/1.0.0 precedent).
SAMPLE_KEY_FIELDS = ("analysis_run_id", "recording_id", "step")


def _check_structure(path: str) -> int:
    """Exact canonical header and a full 60-cell record for every row; returns the row count."""

    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        if header is None:
            raise ValueError(f"empty CSV (no header): {path}")
        if tuple(header) != CANONICAL_FRAME_FIELDS:
            missing = [h for h in CANONICAL_FRAME_FIELDS if h not in header]
            extra = [h for h in header if h not in CANONICAL_FRAME_FIELDS]
            detail = f"missing={missing} extra={extra}" if missing or extra else "field order differs"
            raise ValueError(f"not a {SUPPORTED_FRAME_SCHEMA} header ({detail}): {path}")
        n_rows = 0
        for cells in reader:
            n_rows += 1
            if len(cells) != len(CANONICAL_FRAME_FIELDS):
                raise ValueError(f"malformed CSV record {reader.line_num}: "
                                 f"{len(cells)} cells, expected {len(CANONICAL_FRAME_FIELDS)}")
    if n_rows == 0:
        raise ValueError(f"header-only canonical CSV (zero frame rows): {path}")
    return n_rows


def read_canonical_frame_rows(path: str) -> tuple[dict, ...]:
    """Read one canonical frames CSV into typed rows via the existing canonical reader."""

    n_rows = _check_structure(path)
    with contextlib.redirect_stdout(io.StringIO()):   # load_frames_csv prints a progress line
        rows = analyze_d455.load_frames_csv([], paths=[path])
    if len(rows) != n_rows:
        raise ValueError(f"row count mismatch: {len(rows)} parsed, {n_rows} records")
    return tuple(rows)


def _text(row: dict, field: str, *, optional: bool = False) -> str | None:
    value = row.get(field)
    if value in ("", None):
        if optional:
            return None   # canonical empty cell = unknown; never filled in or guessed
        raise ValueError(f"frame_index {row.get('frame_index')!r}: missing canonical {field}")
    if not isinstance(value, str):
        raise ValueError(f"frame_index {row.get('frame_index')!r}: invalid canonical {field}: {value!r}")
    return value


def row_to_f1_record(row: dict) -> F1FrameRecord:
    """One typed canonical row -> ``F1FrameRecord`` with the unchanged FEAT-009 frame result."""

    if row.get("frame_schema_version") != SUPPORTED_FRAME_SCHEMA:
        raise ValueError(f"unsupported frame_schema_version: {row.get('frame_schema_version')!r}")
    frame_index = row.get("frame_index")
    if type(frame_index) is not int or frame_index < 1:
        raise ValueError(f"invalid canonical frame_index: {frame_index!r}")
    return F1FrameRecord(
        analysis_run_id=_text(row, "analysis_run_id"),
        recording_id=_text(row, "recording_id"),
        frame_index=frame_index,
        subject=_text(row, "subject"),
        round=_text(row, "round", optional=True),
        step=_text(row, "step"),
        label=_text(row, "label"),
        result=compute_f1_5_frame(row),
    )


def records_from_rows(rows) -> tuple[F1FrameRecord, ...]:
    """Convert all rows of ONE recording/run; fail closed on duplicate keys or conflicting identity."""

    rows = tuple(rows)
    if not rows:
        raise ValueError("zero frame rows")
    records = tuple(row_to_f1_record(row) for row in rows)
    for field in ("analysis_run_id", "recording_id", "subject", "round"):
        values = {getattr(r, field) for r in records}
        if len(values) > 1:
            raise ValueError(f"conflicting {field} within one canonical CSV: {sorted(map(repr, values))}")
    seen = set()
    for r in records:
        if r.frame_key in seen:
            raise ValueError(f"duplicate canonical frame key: {r.frame_key}")
        seen.add(r.frame_key)
    labels: dict[str, str] = {}
    for r in records:
        if labels.setdefault(r.step, r.label) != r.label:
            raise ValueError(f"conflicting label within step {r.step!r}: "
                             f"{labels[r.step]!r} vs {r.label!r} (frame_index {r.frame_index})")
    return records


def load_f1_frame_records(path: str) -> tuple[tuple[dict, ...], tuple[F1FrameRecord, ...]]:
    """Read one canonical CSV; return ``(typed rows, records)`` in the same file order."""

    rows = read_canonical_frame_rows(path)
    return rows, records_from_rows(rows)


def group_by_sample(records) -> dict[tuple[str, str, str], tuple[F1FrameRecord, ...]]:
    """Partition records by the sample key, in first-appearance order; every record exactly once."""

    groups: dict[tuple[str, str, str], list[F1FrameRecord]] = {}
    for r in records:
        groups.setdefault((r.analysis_run_id, r.recording_id, r.step), []).append(r)
    return {key: tuple(members) for key, members in groups.items()}
