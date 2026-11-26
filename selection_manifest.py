"""Patch 6 selection authority (PROV-006); no scientific selection policy.

Call append_event with an explicit decision/relation, then build_dataset_manifest
with explicit event IDs. resolve_dataset_manifest revalidates historical snapshots
and returns the existing Patch 5 input records plus the manifest's exact identity.
All artifact paths in selection records are normalized repository-relative paths.
"""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import uuid

import rf_experiment as rf


EVENT_SCHEMA = "selection-event/1.0.0"
MANIFEST_SCHEMA = "dataset-selection-manifest/1.0.0"
LEDGER_PATH = "manifests/selection_events.jsonl"
EVENT_FIELDS = frozenset("schema_version selection_event_id event_type created_at dataset_role subject round "
                         "recording_id selection_policy_version decided_by supersedes_selection_event_id "
                         "recapture decision evidence".split())
ANALYSIS_FIELDS = frozenset("analysis_run_id frames_schema_version frames_path frames_sha256 "
                            "analysis_manifest_path analysis_manifest_sha256".split())
MANIFEST_FIELDS = frozenset("schema_version dataset_manifest_id created_at created_by dataset_role "
                            "selection_policy_version selection_events_path entries".split())
ENTRY_FIELDS = ANALYSIS_FIELDS | frozenset("dataset_role subject round recording_id selection_event_id "
                                         "selection_event_sha256".split())
EVIDENCE_FIELDS = frozenset(("recording_id", "kind", "path", "sha256"))
EVIDENCE_KINDS = ("capture_provenance", "quality", "analysis_manifest", "canonical_frames", "other")
SLOT_FIELDS = ("dataset_role", "subject", "round")


def _root(repo_root):
    return Path(repo_root if repo_root is not None else Path(__file__).parent).resolve(strict=True)


def _text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _keys(value, fields, name):
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError(f"invalid exact {name} fields")


def _hash(value):
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError("SHA-256 must be lowercase 64-hex")


def _id(value, prefix):
    if not isinstance(value, str) or re.fullmatch(prefix + r"_[0-9]{8}T[0-9]{12}Z_[0-9a-f]{32}", value) is None:
        raise ValueError(f"invalid {prefix} ID")
    datetime.strptime(value.split("_")[1], "%Y%m%dT%H%M%S%fZ")
    if uuid.UUID(hex=value.split("_")[2]).version != 4:
        raise ValueError(f"{prefix} ID must contain uuid4 hex")


def _new_id(prefix):
    return f"{prefix}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}_{uuid.uuid4().hex}"


def new_event_id():
    return _new_id("se")


def new_dataset_manifest_id():
    return _new_id("dm")


def _timestamp(value):
    if not isinstance(value, str) or re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?(?:Z|\+00:00)", value) is None:
        raise ValueError("created_at must be a UTC ISO-8601 timestamp")
    if datetime.fromisoformat(value.replace("Z", "+00:00")).utcoffset() != timedelta(0):
        raise ValueError("created_at must be UTC")


def _slot(value):
    if value["dataset_role"] not in ("pilot", "formal"):
        raise ValueError("dataset_role must be pilot or formal")
    _text(value["subject"], "subject")
    rnd = value["round"]
    if not isinstance(rnd, str) or re.fullmatch(r"[1-9][0-9]*", rnd) is None:
        raise ValueError("round must be a canonical positive decimal string (no leading zero)")
    return tuple(value[k] for k in SLOT_FIELDS)


def _policy(value, required):
    if value is not None and not isinstance(value, str):
        raise ValueError("selection_policy_version must be string or null")
    if required:
        _text(value, "formal selection_policy_version")


def resolve_artifact(repo_root, value):
    """Reject non-normalized paths and escapes, including Windows paths and links."""
    _text(value, "artifact path")
    path = PurePosixPath(value)
    if (path.is_absolute() or PureWindowsPath(value).drive or "\\" in value or ":" in value or
            any(ord(c) < 32 for c in value) or path.as_posix() != value or
            any(part in ("", ".", "..") or part.endswith((".", " ")) or
                PureWindowsPath(part).is_reserved() for part in value.split("/"))):
        raise ValueError(f"artifact path must be normalized repository-relative: {value!r}")
    root = _root(repo_root)
    resolved = (root / value).resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f"artifact path resolves outside repository root: {value!r}")
    return resolved


def event_bytes(event):
    return (json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                       allow_nan=False) + "\n").encode("utf-8")


def manifest_bytes(manifest):
    return (json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True,
                       allow_nan=False) + "\n").encode("utf-8")


def _json(data):
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    def invalid_constant(value):
        raise ValueError(f"invalid JSON constant: {value}")

    return json.loads(data.decode("utf-8"), object_pairs_hook=unique_pairs,
                      parse_constant=invalid_constant)


def _pinned_json(path, sha256):
    rf.verify_file(path, sha256)
    value = _json(path.read_bytes())
    rf.verify_file(path, sha256)
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _analysis_shape(value, root):
    _keys(value, ANALYSIS_FIELDS, "analysis_selection")
    _text(value["analysis_run_id"], "analysis_run_id")
    if value["frames_schema_version"] != "frames-schema/1.0.0":
        raise ValueError("unsupported frames schema")
    for prefix in ("frames", "analysis_manifest"):
        resolve_artifact(root, value[prefix + "_path"])
        _hash(value[prefix + "_sha256"])


def _event_shape(event, root):
    _keys(event, EVENT_FIELDS, "selection event")
    if event["schema_version"] != EVENT_SCHEMA:
        raise ValueError("unsupported selection event schema")
    _id(event["selection_event_id"], "se")
    _timestamp(event["created_at"])
    _slot(event)
    _text(event["recording_id"], "recording_id")
    _text(event["decided_by"], "decided_by")
    kind = event["event_type"]
    if kind not in ("recapture_relation", "selection_decision"):
        raise ValueError("unsupported event_type")
    _policy(event["selection_policy_version"], kind == "selection_decision" and event["dataset_role"] == "formal")
    if event["supersedes_selection_event_id"] is not None:
        _id(event["supersedes_selection_event_id"], "se")
    if kind == "recapture_relation":
        _keys(event["recapture"], {"recapture_of_recording_id"}, "recapture")
        _text(event["recapture"]["recapture_of_recording_id"], "recapture parent")
        if event["decision"] is not None or event["supersedes_selection_event_id"] is not None:
            raise ValueError("recapture relation cannot carry a decision or supersession")
    else:
        if event["recapture"] is not None:
            raise ValueError("selection decision recapture must be null")
        decision = event["decision"]
        _keys(decision, {"disposition", "reason_code", "reason_text", "analysis_selection"}, "decision")
        _text(decision["reason_code"], "reason_code")
        if decision["reason_text"] is not None and not isinstance(decision["reason_text"], str):
            raise ValueError("reason_text must be string or null")
        if decision["disposition"] == "include":
            _analysis_shape(decision["analysis_selection"], root)
        elif decision["disposition"] != "exclude" or decision["analysis_selection"] is not None:
            raise ValueError("invalid disposition or exclude analysis_selection")
    if not isinstance(event["evidence"], list):
        raise ValueError("evidence must be an array")
    for item in event["evidence"]:
        _keys(item, EVIDENCE_FIELDS, "evidence")
        _text(item["recording_id"], "evidence recording_id")
        if item["kind"] not in EVIDENCE_KINDS:
            raise ValueError("unsupported evidence kind")
        resolve_artifact(root, item["path"])
        _hash(item["sha256"])
    # Evidence cardinality and bindings are schema constraints even when sources
    # of unrelated historical events are not opened during snapshot revalidation.
    _one_evidence(event, "capture_provenance", event["recording_id"])
    if kind == "recapture_relation":
        _one_evidence(event, "capture_provenance", event["recapture"]["recapture_of_recording_id"])
    elif event["decision"]["disposition"] == "include":
        selected = event["decision"]["analysis_selection"]
        for evidence_kind, prefix in (("analysis_manifest", "analysis_manifest"), ("canonical_frames", "frames")):
            items = [e for e in event["evidence"] if e["kind"] == evidence_kind and
                     e["recording_id"] == event["recording_id"]]
            if not items or (event["dataset_role"] == "formal" and len(items) != 1):
                raise ValueError(f"include requires {evidence_kind} evidence")
            if any((e["path"], e["sha256"]) != (selected[prefix + "_path"], selected[prefix + "_sha256"])
                   for e in items):
                raise ValueError(f"{evidence_kind} evidence/analysis_selection mismatch")
        if event["dataset_role"] == "formal":
            _one_evidence(event, "quality", event["recording_id"])


def _one_evidence(event, kind, recording_id):
    items = [e for e in event["evidence"] if e["kind"] == kind and e["recording_id"] == recording_id]
    if len(items) != 1:
        raise ValueError(f"requires exactly one {kind} evidence for {recording_id}")
    return items[0]


def _event_sources(event, root):
    documents = {}
    for item in event["evidence"]:
        path = resolve_artifact(root, item["path"])
        rf.verify_file(path, item["sha256"])
        if item["kind"] in ("capture_provenance", "quality", "analysis_manifest"):
            document = _pinned_json(path, item["sha256"])
            if document.get("recording_id") != item["recording_id"]:
                raise ValueError("evidence recording_id mismatch")
            documents[(item["kind"], item["recording_id"], item["path"])] = document

    def capture(rid):
        item = _one_evidence(event, "capture_provenance", rid)
        value = documents[("capture_provenance", rid, item["path"])]
        if any(value.get(k) != event[k] for k in SLOT_FIELDS):
            raise ValueError("capture provenance slot/role mismatch")
        return value

    own_capture = capture(event["recording_id"])
    if event["event_type"] == "recapture_relation":
        capture(event["recapture"]["recapture_of_recording_id"])
        return None
    if event["decision"]["disposition"] == "exclude":
        return None
    selected = event["decision"]["analysis_selection"]
    frames = resolve_artifact(root, selected["frames_path"])
    owner_path = resolve_artifact(root, selected["analysis_manifest_path"])
    owner = _pinned_json(owner_path, selected["analysis_manifest_sha256"])
    if owner.get("dataset_role") != event["dataset_role"]:
        raise ValueError("analysis dataset_role mismatch")
    if ("protocol_version" not in own_capture or "protocol_version" not in owner or
            own_capture["protocol_version"] != owner["protocol_version"]):
        raise ValueError("capture/analysis protocol_version mismatch")
    # Reuse the full Patch 5 validator, including the exact 60-field frame header,
    # owner status, archive location, row identities, and owner output path/hash.
    entry = rf.canonical_input(frames, root / "analysis")
    expected = dict(selected, recording_id=event["recording_id"], subject=event["subject"], round=event["round"],
                    frames_path=str(frames), analysis_manifest_path=str(owner_path))
    if entry != expected:
        raise ValueError("selected source/canonical input identity or hash mismatch")
    return entry


def _history_event(event, events, parents, terminals):
    event_id = event["selection_event_id"]
    if event_id in events:
        raise ValueError("duplicate selection_event_id")
    previous_id = event["supersedes_selection_event_id"]
    if previous_id is not None:
        previous = events.get(previous_id)
        if (previous is None or previous["event_type"] != "selection_decision" or
                _slot(previous) != _slot(event)):
            raise ValueError("broken supersedes reference: requires earlier decision for same slot")
    if event["event_type"] == "selection_decision":
        slot = _slot(event)
        if previous_id != terminals.get(slot):
            if previous_id is None:
                raise ValueError("unlinked selection decision: must supersede the current terminal decision for the slot")
            raise ValueError("branching supersession: must supersede the current terminal decision for the slot")
        terminals[slot] = event_id
    if event["event_type"] == "recapture_relation":
        child, parent = event["recording_id"], event["recapture"]["recapture_of_recording_id"]
        if child == parent:
            raise ValueError("recapture self-link")
        if child in parents and parents[child] != parent:
            raise ValueError("multiple direct recapture parents")
        ancestor = parent
        while ancestor in parents:
            if ancestor == child:
                raise ValueError("recapture cycle")
            ancestor = parents[ancestor]
        if ancestor == child:
            raise ValueError("recapture cycle")
        parents[child] = parent
    events[event_id] = event


def _read_ledger_bytes(data, root, validate_sources):
    events, hashes, parents, terminals = {}, {}, {}, {}
    for number, line in enumerate(data.splitlines(keepends=True), 1):
        try:
            event = _json(line)
            _event_shape(event, root)
            if line != event_bytes(event):
                raise ValueError("ledger requires canonical UTF-8 JSON + LF bytes")
            _history_event(event, events, parents, terminals)
            if validate_sources:
                _event_sources(event, root)
            hashes[event["selection_event_id"]] = hashlib.sha256(line).hexdigest()
        except (ValueError, OSError) as error:
            raise ValueError(f"selection ledger line {number}: {error}") from error
    return events, hashes, parents, terminals


def read_selection_events(repo_root=None):
    """Validate the complete ledger and all evidence, returning events in append order."""
    root = _root(repo_root)
    path = resolve_artifact(root, LEDGER_PATH)
    artifact = rf.file_identity(path)
    events, _, _, _ = _read_ledger_bytes(path.read_bytes(), root, True)
    rf.verify_file(path, artifact["sha256"])
    return list(events.values())


@contextmanager
def _locked_ledger(path, create=False):
    """Serialize append/build across processes; fail closed on a busy ledger.

    Lock byte zero on Windows (also valid for an empty file), or flock on POSIX.
    No lock-file authority and no rewrite/truncate operation are needed.
    """
    with path.open("a+b" if create else "r+b") as stream:
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise ValueError("selection ledger is busy; retry when the writer/build finishes") from error
        try:
            yield stream
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def append_event(event, repo_root=None):
    """Validate before appending, preserving every existing ledger byte. Return line SHA."""
    root = _root(repo_root)
    # Detach caller-owned mutable objects before validating/writing.
    data = event_bytes(event)
    event = _json(data)
    _event_shape(event, root)
    _event_sources(event, root)
    path = resolve_artifact(root, LEDGER_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _locked_ledger(path, create=True) as stream:
        stream.seek(0)
        events, _, parents, terminals = _read_ledger_bytes(stream.read(), root, True)
        _history_event(event, events, parents, terminals)
        _event_sources(event, root)
        stream.seek(0, os.SEEK_END)
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    return hashlib.sha256(data).hexdigest()


def _manifest_entry(event, sha256):
    if event["event_type"] != "selection_decision" or event["decision"]["disposition"] != "include":
        raise ValueError("dataset entry must reference an include selection decision")
    return dict((k, event[k]) for k in (*SLOT_FIELDS, "recording_id", "selection_event_id")) | dict(
        selection_event_sha256=sha256, **event["decision"]["analysis_selection"])


def _validate_manifest(manifest, root, events, hashes, terminals, building=False):
    _keys(manifest, MANIFEST_FIELDS, "dataset manifest")
    if manifest["schema_version"] != MANIFEST_SCHEMA:
        raise ValueError("unsupported dataset manifest schema")
    _id(manifest["dataset_manifest_id"], "dm")
    _timestamp(manifest["created_at"])
    _text(manifest["created_by"], "created_by")
    if manifest["dataset_role"] not in ("pilot", "formal"):
        raise ValueError("dataset_role must be pilot or formal")
    _policy(manifest["selection_policy_version"], manifest["dataset_role"] == "formal")
    if manifest["selection_events_path"] != LEDGER_PATH:
        raise ValueError("selection_events_path must be the canonical ledger path")
    if not isinstance(manifest["entries"], list):
        raise ValueError("entries must be an array")
    slots, ordering, inputs = set(), [], []
    for entry in manifest["entries"]:
        _keys(entry, ENTRY_FIELDS, "dataset entry")
        slot = _slot(entry)
        if slot in slots:
            raise ValueError("duplicate logical slot")
        slots.add(slot)
        ordering.append((entry["subject"], int(entry["round"])))
        _text(entry["recording_id"], "recording_id")
        _id(entry["selection_event_id"], "se")
        _hash(entry["selection_event_sha256"])
        _analysis_shape({k: entry[k] for k in ANALYSIS_FIELDS}, root)
        event_id = entry["selection_event_id"]
        if event_id not in events:
            raise ValueError("dataset selection event does not exist")
        if building and terminals.get(slot) != event_id:
            raise ValueError("new manifest requires the current terminal decision; selected decision is superseded")
        event = events[event_id]
        if (entry["dataset_role"] != manifest["dataset_role"] or
                event["selection_policy_version"] != manifest["selection_policy_version"]):
            raise ValueError("dataset role/policy mismatch")
        if entry != _manifest_entry(event, hashes[event_id]):
            raise ValueError("dataset entry/pinned event identity or SHA-256 mismatch")
        inputs.append(_event_sources(event, root))
    if ordering != sorted(ordering):
        raise ValueError("dataset entries must be ordered by subject then int(round)")
    rf.reject_input_ambiguity(inputs)
    return inputs


def build_dataset_manifest(selection_event_ids, *, dataset_role, created_by,
                           selection_policy_version=None, repo_root=None):
    """Create an immutable snapshot of explicitly supplied, currently terminal includes.

    The ledger lock spans validation and exclusive manifest creation so a concurrent
    append cannot supersede a selected event between the check and publication.
    """
    root = _root(repo_root)
    if not isinstance(selection_event_ids, (list, tuple)):
        raise ValueError("selection_event_ids must be a list/tuple of explicit IDs")
    for event_id in selection_event_ids:
        _id(event_id, "se")
    with _locked_ledger(resolve_artifact(root, LEDGER_PATH)) as stream:
        events, hashes, _, terminals = _read_ledger_bytes(stream.read(), root, True)
        if any(event_id not in events for event_id in selection_event_ids):
            raise ValueError("dataset selection event does not exist")
        entries = [_manifest_entry(events[event_id], hashes[event_id]) for event_id in selection_event_ids]
        entries.sort(key=lambda e: (e["subject"], int(e["round"])))
        manifest = dict(schema_version=MANIFEST_SCHEMA, dataset_manifest_id=new_dataset_manifest_id(),
                        created_at=datetime.now(timezone.utc).isoformat(), created_by=created_by,
                        dataset_role=dataset_role, selection_policy_version=selection_policy_version,
                        selection_events_path=LEDGER_PATH, entries=entries)
        _validate_manifest(manifest, root, events, hashes, terminals, building=True)
        relative_path = f"manifests/datasets/{manifest['dataset_manifest_id']}.json"
        resolve_artifact(root, relative_path)
        # Open the declared name exclusively, not its resolved target: even a
        # dangling final symlink already occupies this immutable manifest ID.
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive creation never overwrites an existing (even partial) snapshot.
        with path.open("xb") as output:
            output.write(manifest_bytes(manifest))
            output.flush()
            os.fsync(output.fileno())
    return path


def resolve_dataset_manifest(path, repo_root=None, expected_sha256=None):
    """Revalidate pinned snapshot sources, independent of later supersession.

    Return (Patch 5 canonical inputs, experiment dataset_manifest reference).
    Only selected events' source bytes are needed for historical revalidation;
    the entire ledger still undergoes strict schema/hash-line/graph validation.
    """
    root = _root(repo_root)
    path = Path(path)
    path = (path if path.is_absolute() else root / path).resolve(strict=True)
    artifact = rf.file_identity(path)
    if expected_sha256 is not None:
        _hash(expected_sha256)
        if expected_sha256 != artifact["sha256"]:
            raise ValueError("dataset manifest SHA-256 mismatch")
    data = path.read_bytes()
    manifest = _json(data)
    _keys(manifest, MANIFEST_FIELDS, "dataset manifest")
    _id(manifest["dataset_manifest_id"], "dm")
    canonical = resolve_artifact(root, f"manifests/datasets/{manifest['dataset_manifest_id']}.json")
    if path != canonical:
        raise ValueError("dataset manifest ID/path mismatch")
    if data != manifest_bytes(manifest):
        raise ValueError("dataset manifest requires canonical UTF-8 pretty JSON + LF bytes")
    ledger = resolve_artifact(root, LEDGER_PATH)
    ledger_identity = rf.file_identity(ledger)
    events, hashes, _, terminals = _read_ledger_bytes(ledger.read_bytes(), root, False)
    inputs = _validate_manifest(manifest, root, events, hashes, terminals)
    rf.verify_file(ledger, ledger_identity["sha256"])
    rf.verify_file(path, artifact["sha256"])
    return inputs, dict(dataset_manifest_id=manifest["dataset_manifest_id"],
                        path=str(path), sha256=artifact["sha256"])
