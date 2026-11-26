"""Patch 7 read-only audit of the existing Patch 1–6 authority graph.

No repair, selection, inference, hardware access, or model provisioning occurs here.
See docs/foundation/PATCH_07_integrity_checker_hardening.md (PROV-008).
"""
import argparse
from contextlib import redirect_stdout
import csv
from dataclasses import dataclass
import io
import json
import os
from pathlib import Path, PureWindowsPath
import re
import sys

try:
    import analyze_d455 as analysis
    import rf_experiment as rf
    import selection_manifest as selection
except Exception as error:
    if __name__ != "__main__":
        raise
    print(f"CHECKER_FAILURE: {type(error).__name__}: {error}", file=sys.stderr)
    sys.exit(2)


SEVERITIES = ("ERROR", "WARNING", "INFO")
CAPTURE_SUFFIXES = (".db3", ".bag", "_camera.json", "_markers.csv", "_samples.csv", "_quality.json")


@dataclass(frozen=True)
class Finding:
    severity: str
    code: str
    artifact: str
    reason: str


@dataclass(frozen=True)
class AuditResult:
    findings: tuple

    @property
    def counts(self):
        return {s: sum(f.severity == s for f in self.findings) for s in SEVERITIES}

    @property
    def exit_code(self):
        return int(self.counts["ERROR"] > 0)


class Contradiction(ValueError):
    def __init__(self, code, reason):
        super().__init__(reason)
        self.code = code


def require(condition, code, reason):
    if not condition:
        raise Contradiction(code, reason)


def text_value(value):
    return isinstance(value, str) and bool(value.strip())


def digest_value(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-fA-F]{64}", value) is not None


def foreign_absolute(value):
    # Historical Windows absolute inputs are external and unopenable on POSIX;
    # do not reinterpret them as paths relative to this checkout.
    return isinstance(value, str) and PureWindowsPath(value).is_absolute() and not Path(value).is_absolute()


def temporary(path):
    return (path.match(".manifest-*.tmp") or path.name == ".experiment_manifest.tmp" or
            path.match(".model-*.tmp"))


def managed_inventory(root):
    """Include directories and dangling names as well as files; never follow dir links."""
    paths = set()
    for name in ("data", "analysis", "results"):
        base = root / name
        if os.path.lexists(base):
            paths.add(base.relative_to(root).as_posix())
        else:
            continue
        def walk_error(error):
            raise error
        for directory, dirs, files in os.walk(base, onerror=walk_error, followlinks=False):
            for name in dirs + files:
                paths.add((Path(directory) / name).relative_to(root).as_posix())
    for path in [root / selection.LEDGER_PATH, root / "mediapipe_model_lock.json",
                 *(root / "manifests/datasets").glob("*.json"),
                 *(root / "manifests/datasets").glob(".manifest-*.tmp"),
                 *(root / "models").glob(".model-*.tmp"),
                 *(root / "models" / name for name in analysis.MODEL_FILENAMES.values())]:
        if os.path.lexists(path):
            paths.add(path.relative_to(root).as_posix())
    return frozenset(paths)


def validation_code(error, default):
    """Map existing validators' diagnostics without reimplementing their semantics."""
    if isinstance(error, FileNotFoundError):
        return "MISSING_ARTIFACT"
    if isinstance(error.__cause__, FileNotFoundError):
        return "MISSING_ARTIFACT"
    message = str(error).lower()
    if "changed while hashing" in message:
        return "REPOSITORY_CHANGED_DURING_CHECK"
    if "sha" in message and ("mismatch" in message or "hash" in message):
        return "HASH_MISMATCH"
    if isinstance(error, json.JSONDecodeError) or "expecting " in message or "unterminated string" in message:
        return "TORN_AUTHORITY"
    if "canonical utf-8" in message or "duplicate json" in message:
        return "SERIALIZATION_INVALID"
    if "identity" in message or "recording_id mismatch" in message or "id/path" in message:
        return "IDENTITY_MISMATCH"
    if "owner" in message or "reference" in message and "cross-" in message:
        return "OWNER_MISMATCH"
    return default


class Auditor:
    def __init__(self, root):
        self.root = Path(root).resolve(strict=True)
        if not self.root.is_dir():
            raise ValueError("repo-root must be a directory")
        self.findings = set()
        self.runs = {}
        self.batches = {}

    def display(self, path):
        path = Path(path)
        return path.relative_to(self.root).as_posix() if path.is_relative_to(self.root) else str(path)

    def add(self, severity, code, path, reason):
        self.findings.add(Finding(severity, code, self.display(path), str(reason)))

    def check(self, path, action):
        # Only explicit repository contradictions are findings. Unexpected checker
        # exceptions propagate to main(), which exits 2 and never prints PASS.
        try:
            return action()
        except Contradiction as error:
            self.add("ERROR", error.code, path, error)
            return None

    def reuse(self, function, *args, code="SCHEMA_INVALID", **kwargs):
        try:
            return function(*args, **kwargs)
        except Contradiction:
            raise  # Preserve an explicit checker category across helper layers.
        except (ValueError, FileNotFoundError) as error:
            # Existing validators deliberately reject content with ValueError.
            # Programming errors (TypeError/KeyError/AttributeError) must escape
            # to main's exit 2, not masquerade as repository contradictions.
            raise Contradiction(validation_code(error, code), str(error)) from error

    def path(self, value, base=None):
        require(text_value(value), "SCHEMA_INVALID", "artifact path must be a non-empty string")
        path = Path(value)
        if path.is_absolute():
            return path.resolve()
        return self.reuse(selection.resolve_artifact, base or self.root, value)

    def exists(self, path):
        require(path.is_file(), "MISSING_ARTIFACT", f"authority requires file: {self.display(path)}")

    def bytes(self, path):
        self.exists(path)
        identity = self.reuse(rf.file_identity, path)
        data = path.read_bytes()
        self.reuse(rf.verify_file, path, identity["sha256"])
        return data

    def document(self, path):
        value = self.reuse(selection._json, self.bytes(path), code="TORN_AUTHORITY")
        require(isinstance(value, dict), "SCHEMA_INVALID", "authority must be a JSON object")
        return value

    def record(self, item, *, base=None, required=True, hash_required=False, historical_compatibility=False):
        require(isinstance(item, dict), "SCHEMA_INVALID", "artifact record must be an object")
        sha = item.get("sha256")
        complete = item.get("hash_status") == "complete"
        require("hash_status" not in item or item["hash_status"] in ("complete", "unavailable"),
                "SCHEMA_INVALID", "invalid artifact hash_status")
        require(not (complete or hash_required) or digest_value(sha), "SCHEMA_INVALID",
                "complete artifact record requires full SHA-256")
        require(sha is None or digest_value(sha), "SCHEMA_INVALID", "invalid artifact SHA-256")
        if foreign_absolute(item.get("path")):
            self.add("WARNING", "EXTERNAL_UNVERIFIABLE", item["path"], "historical absolute path is inaccessible on this platform")
            return None
        path = self.path(item.get("path"), base)
        require(not path.is_dir(), "SCHEMA_INVALID", "artifact record points to a directory")
        if historical_compatibility:
            # PROV-009: this records bytes consumed then, not a permanent pin on
            # today's publication. Immutable source/parent checks occur below;
            # current explicit compatibility claims are audited independently.
            require(item.get("size_bytes") is None or type(item["size_bytes"]) is int,
                    "SCHEMA_INVALID", "invalid historical input size_bytes")
            return path
        external = not path.is_relative_to(self.root)
        try:
            actual = self.reuse(rf.file_identity, path)
        except (Contradiction, PermissionError) as error:
            missing = isinstance(error, PermissionError) or error.code == "MISSING_ARTIFACT"
            if missing and external:
                self.add("WARNING", "EXTERNAL_UNVERIFIABLE", path, "recorded external artifact is inaccessible")
                return None
            if missing and not required and sha is None and not complete:
                self.add("WARNING", "INCOMPLETE_NONTERMINAL", path, "historical input hash explicitly unavailable")
                return None
            raise
        if sha is not None:
            require(actual["sha256"] == sha.lower(), "HASH_MISMATCH", f"stored SHA-256 differs: {path}")
        if item.get("size_bytes") is not None:
            require(type(item["size_bytes"]) is int and item["size_bytes"] == actual["size_bytes"],
                    "SCHEMA_INVALID", f"stored size_bytes differs: {path}")
        return path

    def canonical(self, path, *, historical_output=False):
        # The reused Patch 5 validator assumes an object with object outputs.
        # Diagnose malformed repository shapes explicitly before calling it.
        self.lifecycle(self.document(path.parent / "analysis_manifest.json"), "analysis-provenance/1.0.0")
        if historical_output:
            entry = self.reuse(rf.validate_frames_output, path, self.root / "analysis", require_completed=False)
        else:
            entry = self.reuse(rf.canonical_input, path, self.root / "analysis")
        # Patch 4 reader owns field-value serialization; Patch 5 owns identity,
        # exact header, immutable path and completed-owner/hash binding.
        with redirect_stdout(io.StringIO()):
            self.reuse(analysis.load_frames_csv, [], paths=[path])
        return entry

    def analysis_input(self, value, kind, item, parent_output):
        historical = False
        if (value["analysis_mode"] == "summarize_existing_frames" and parent_output is not None and
                kind in ("frames", "frames_provenance") and parent_output.get("compatibility_path") is not None and
                not foreign_absolute(parent_output["compatibility_path"]) and not foreign_absolute(item.get("path"))):
            # PROV-010: only the explicitly validated parent frames output can
            # identify this mutable publication, including legacy raw-stem names.
            flat = self.path(parent_output["compatibility_path"])
            publication = flat if kind == "frames" else Path(str(flat) + ".provenance.json")
            historical = (flat.parent == self.root / "analysis" and
                          self.path(value["inputs"]["frames"].get("path")) == flat and
                          self.path(item.get("path")) == publication)
        return self.record(item, required=item.get("hash_status") != "unavailable",
                           hash_required=historical, historical_compatibility=historical)

    def capture(self, path, expected=None, event=None):
        value = self.document(path)
        raw_name = path.with_name(path.name.removesuffix("_camera.json") + ".bag")
        modern = (expected is not None or "recording_id" in value or
                  str(value.get("schema_version", "")).startswith("capture-provenance/") or
                  value.get("protocol_version") not in (None, "", "unknown_legacy") or
                  value.get("dataset_role") in ("formal", "external") or analysis.new_recording_name(raw_name))
        if not modern:
            self.add("WARNING", "INCOMPLETE_NONTERMINAL", path, "legacy capture authority; no modern identity inferred")
            return value
        require(value.get("schema_version") == "capture-provenance/1.0.0", "SCHEMA_INVALID",
                "unsupported capture provenance schema")
        rid = self.reuse(analysis.safe_recording_id, value.get("recording_id"))
        require(path.name == rid + "_camera.json" and (expected is None or rid == expected),
                "IDENTITY_MISMATCH", "capture path/evidence recording_id mismatch")
        require(isinstance(value.get("subject"), str) and
                re.fullmatch(r"[A-Za-z0-9-]+", value["subject"]) is not None,
                "SCHEMA_INVALID", "invalid modern capture subject")
        require(isinstance(value.get("round"), str) and
                re.fullmatch(r"[1-9][0-9]*", value["round"]) is not None,
                "SCHEMA_INVALID", "capture round must be canonical positive decimal string")
        require(value.get("dataset_role") in ("pilot", "formal", "external") and
                text_value(value.get("protocol_version")), "SCHEMA_INVALID", "invalid capture role/protocol")
        require("record_file" in value, "SCHEMA_INVALID", "capture record_file field missing")
        raw = value["record_file"]
        require(raw is None or raw in (rid + ".bag", rid + ".db3"), "IDENTITY_MISMATCH",
                "capture record_file must name the same recording stem")
        if raw is not None:
            self.exists(path.parent / raw)
        else:
            self.add("WARNING", "INCOMPLETE_NONTERMINAL", path, "preserved capture attempt has record_file=null")
        mapping = {kind: f"{rid}_{kind}.{ext}" for kind, ext in
                   (("camera", "json"), ("markers", "csv"), ("samples", "csv"), ("quality", "json"))}
        require(value.get("sidecar_files") == mapping, "IDENTITY_MISMATCH", "capture sidecar naming map mismatch")
        if event is not None:
            require(all(value.get(k) == event[k] for k in selection.SLOT_FIELDS),
                    "IDENTITY_MISMATCH", "capture evidence/event slot mismatch")
        for kind in ("markers", "samples", "quality"):
            companion = path.parent / mapping[kind]
            if not companion.exists():
                continue  # naming map does not assert successful creation
            if kind == "quality":
                self.check(companion, lambda p=companion: self.quality(p, rid))
            else:
                def csv_ids(p=companion):
                    rows = csv.DictReader(io.StringIO(self.reuse(bytes.decode, self.bytes(p), "utf-8-sig",
                                                                code="SERIALIZATION_INVALID")))
                    for row in rows:
                        if "recording_id" in row:
                            require(row["recording_id"] == rid, "IDENTITY_MISMATCH",
                                    "capture companion row recording_id mismatch")
                self.check(companion, csv_ids)
        return value

    def quality(self, path, rid):
        value = self.document(path)
        require(text_value(value.get("recording_id")) and value["recording_id"] == rid,
                "IDENTITY_MISMATCH", "quality recording_id missing or mismatched")

    def captures(self, inventory):
        groups = set()
        for name in sorted(inventory):
            path = self.root / name
            if name.startswith("data/"):
                for suffix in CAPTURE_SUFFIXES:
                    if path.name.endswith(suffix):
                        groups.add(path.parent / path.name[:-len(suffix)])
                        break
        for base in sorted(groups):
            camera = base.with_name(base.name + "_camera.json")
            if camera.exists():
                self.check(camera, lambda p=camera: self.capture(p))
            else:
                self.add("WARNING", "INCOMPLETE_NONTERMINAL", base, "capture companions without modern camera authority")

    def lifecycle(self, value, schema):
        require(value.get("schema_version") == schema, "SCHEMA_INVALID", "unsupported manifest schema")
        require(value.get("status") in ("running", "failed", "completed"), "SCHEMA_INVALID", "invalid run status")
        require(isinstance(value.get("inputs"), dict) and isinstance(value.get("outputs"), list),
                "SCHEMA_INVALID", "inputs/outputs must be object/array")
        require(all(isinstance(o, dict) for o in value["outputs"]), "SCHEMA_INVALID", "output records must be objects")

    def analysis_run(self, path):
        value = self.document(path)
        self.lifecycle(value, "analysis-provenance/1.0.0")
        require(path.name == "analysis_manifest.json" and path.parent.name.startswith("ar_") and
                path.parent.parent.parent == self.root / "analysis", "OWNER_MISMATCH",
                "analysis authority is outside its canonical run namespace")
        rid, run = path.parent.parent.name, path.parent.name
        require((value.get("recording_id"), value.get("analysis_run_id")) == (rid, run),
                "IDENTITY_MISMATCH", "analysis directory/manifest identity mismatch")
        require(text_value(value.get("analysis_batch_id")), "SCHEMA_INVALID", "missing analysis_batch_id")
        require(value.get("analysis_mode") in ("extract_raw", "summarize_existing_frames") and
                "parent_analysis_run_id" in value and
                (value["parent_analysis_run_id"] is None or text_value(value["parent_analysis_run_id"])),
                "SCHEMA_INVALID", "invalid analysis mode/parent identity")
        require(value.get("dataset_role") in ("pilot", "formal", "external") and
                text_value(value.get("protocol_version")), "SCHEMA_INVALID", "invalid analysis role/protocol")
        self.runs[path.resolve()] = value
        if value["status"] != "completed":
            self.add("WARNING", "INCOMPLETE_NONTERMINAL", path, f"preserved {value['status']} analysis run")
        inputs = value["inputs"]
        require(all(isinstance(i, dict) for i in inputs.values()), "SCHEMA_INVALID", "analysis input records must be objects")
        parent_output = self.check(path, lambda: self.analysis_parent(value))
        for kind, item in sorted(inputs.items()):
            self.check(path, lambda k=kind, i=item: self.analysis_input(value, k, i, parent_output))
            if isinstance(item, dict) and item.get("recording_id") is not None:
                require(item["recording_id"] == rid, "IDENTITY_MISMATCH", f"analysis {kind} recording identity mismatch")
        if value["analysis_mode"] == "extract_raw":
            require(isinstance(inputs.get("recording"), dict) and digest_value(inputs["recording"].get("sha256")),
                    "SCHEMA_INVALID", "raw analysis requires authoritative recording SHA-256")
            if value["dataset_role"] == "formal":
                require(isinstance(inputs.get("markers"), dict) and digest_value(inputs["markers"].get("sha256")),
                        "SCHEMA_INVALID", "formal raw analysis requires markers SHA-256")
            capture = inputs.get("capture_metadata")
            if capture and capture.get("sha256") and not foreign_absolute(capture.get("path")):
                camera_path = self.path(capture.get("path"))
                if camera_path.is_file():
                    camera = self.check(camera_path, lambda: self.capture(camera_path))
                    if camera and camera.get("recording_id"):
                        require(camera["recording_id"] == rid and all(camera.get(k) == value.get(k)
                                for k in ("dataset_role", "protocol_version")), "IDENTITY_MISMATCH",
                                "analysis/capture provenance mismatch")
                        raw = self.path(inputs["recording"]["path"])
                        require(raw.parent == camera_path.parent and raw.name == camera.get("record_file"),
                                "OWNER_MISMATCH", "analysis raw input differs from capture record_file")
        else:
            require(isinstance(inputs.get("frames"), dict), "SCHEMA_INVALID", "CSV analysis requires frames input")
        for item in value["outputs"]:
            self.check(path, lambda i=item: self.analysis_output(path, value, i))

    def analysis_parent(self, value):
        """Validate immutable parent authority before using its publication relation."""
        inputs, rid = value["inputs"], value["recording_id"]
        parent = value["parent_analysis_run_id"]
        if parent is not None:
            parent_record = inputs.get("parent_manifest")
            require(isinstance(parent_record, dict), "OWNER_MISMATCH", "linked analysis parent record missing")
            parent_path = self.record(parent_record, hash_required=True)
            require(parent_path is not None, "OWNER_MISMATCH", "analysis parent authority is unverifiable")
            previous = self.document(parent_path)
            self.lifecycle(previous, "analysis-provenance/1.0.0")
            require((previous.get("recording_id"), previous.get("analysis_run_id"), previous.get("status")) ==
                    (rid, parent, "completed"), "OWNER_MISMATCH", "analysis parent identity/status mismatch")
            source = inputs.get("frames", {})
            outputs = [o for o in previous["outputs"] if o.get("kind") == "frames" and
                       o.get("sha256") == source.get("sha256") and
                       o.get("filename") == self.path(source.get("path")).name]
            require(source.get("analysis_run_id") == parent and len(outputs) == 1,
                    "OWNER_MISMATCH", "CSV analysis input is not a declared parent frames output")
            entry = self.canonical(self.path(outputs[0].get("path")))
            require(entry["analysis_manifest_path"] == str(parent_path) and
                    (entry["recording_id"], entry["analysis_run_id"]) == (rid, parent),
                    "OWNER_MISMATCH", "CSV parent canonical output ownership mismatch")
            archives = [o for o in value["outputs"] if o.get("kind") == "source_frames"]
            require(len(archives) <= 1, "OWNER_MISMATCH", "CSV analysis has multiple archived sources")
            require(value["status"] != "completed" or len(archives) == 1,
                    "MISSING_ARTIFACT", "completed linked CSV analysis requires archived source_frames")
            require(all(previous.get(k) == value.get(k) for k in ("dataset_role", "protocol_version")),
                    "IDENTITY_MISMATCH", "CSV analysis parent role/protocol mismatch")
            return outputs[0]

    def analysis_output(self, owner, value, item):
        target = self.path(item.get("path"))
        if item.get("kind") == "batch_output":
            expected = self.root / "analysis/batches" / value["analysis_batch_id"]
            require(target.parent == expected, "OWNER_MISMATCH", "shared output points outside owning batch")
        else:
            require(target.parent == owner.parent, "OWNER_MISMATCH", "analysis output points outside owning run")
        self.record(item)
        if item.get("kind") == "frames":
            self.canonical(target, historical_output=True)
        elif item.get("kind") == "source_frames":
            # Exact-byte equality with the historical input and the validated
            # parent frames also binds the archive's schema and row identities.
            require(item.get("sha256") == value["inputs"].get("frames", {}).get("sha256"),
                    "HASH_MISMATCH", "archived source frames differ from recorded input")

    def batch(self, path):
        value = self.document(path)
        require(value.get("analysis_batch_id") == path.parent.name, "IDENTITY_MISMATCH", "batch directory/ID mismatch")
        ids, refs, outputs = (value.get(k) for k in ("analysis_run_ids", "run_manifests", "outputs"))
        require(isinstance(ids, list) and all(text_value(i) and i.startswith("ar_") for i in ids) and
                len(set(ids)) == len(ids) and isinstance(refs, list) and isinstance(outputs, list),
                "SCHEMA_INVALID", "invalid batch contributors/references/outputs")
        require(all(isinstance(o, dict) for o in outputs), "SCHEMA_INVALID", "batch output records must be objects")
        actual_ids = []
        for ref in refs:
            target = self.path(ref)
            self.exists(target)
            run = self.runs.get(target)
            require(run is not None and run["analysis_batch_id"] == path.parent.name,
                    "OWNER_MISMATCH", "batch/run manifest ownership mismatch")
            actual_ids.append(run["analysis_run_id"])
            require(all(item in run["outputs"] for item in outputs), "OWNER_MISMATCH",
                    "batch output missing from contributor manifest")
        require(sorted(actual_ids) == sorted(ids), "OWNER_MISMATCH", "batch contributors/run references differ")
        for item in outputs:
            target = self.record(item)
            require(target is None or target.parent == path.parent, "OWNER_MISMATCH", "batch output path mismatch")
            require(item.get("analysis_run_ids") == ids, "OWNER_MISMATCH", "shared output contributors differ")
        self.batches[path.parent.name] = value

    def compatibility(self, path):
        link = self.document(path)
        flat = Path(str(path)[:-len(".provenance.json")])
        self.record(dict(path=str(flat), sha256=link.get("frames_sha256")), hash_required=True)
        owner_path = self.path(link.get("analysis_manifest"), path.parent)
        self.record(dict(path=str(owner_path), sha256=link.get("analysis_manifest_sha256")), hash_required=True)
        owner = self.document(owner_path)
        self.lifecycle(owner, "analysis-provenance/1.0.0")
        outputs = [o for o in owner.get("outputs", []) if o.get("kind") == "frames" and
                   o.get("sha256") == link["frames_sha256"]]
        require(len(outputs) == 1, "OWNER_MISMATCH", "compatibility claim has no unique owner output")
        entry = self.canonical(self.path(outputs[0].get("path")))
        require(entry["analysis_manifest_path"] == str(owner_path) and
                all(entry[k] == link.get(k) for k in ("recording_id", "analysis_run_id")),
                "OWNER_MISMATCH", "compatibility provenance owner mismatch")

    def unowned_directory(self, directory, owner_name):
        artifacts = [p for p in directory.iterdir() if p.is_file() and not temporary(p)]
        self.add("ERROR" if artifacts else "WARNING",
                 "STRUCTURAL_ORPHAN" if artifacts else "INCOMPLETE_NONTERMINAL", directory,
                 f"{'derivative artifacts' if artifacts else 'empty/temporary-only directory'} without {owner_name}")

    def analyses(self):
        root = self.root / "analysis"
        for directory in sorted(root.glob("*/ar_*")):
            if not directory.is_dir() or directory.parent.name == "batches":
                continue
            path = directory / "analysis_manifest.json"
            if path.exists():
                self.check(path, lambda p=path: self.analysis_run(p))
                value = self.runs.get(path.resolve())
                if value:
                    owned = {self.check(path, lambda o=o: self.path(o.get("path"))) for o in value["outputs"]}
                    for frames in sorted(directory.glob("*_frames.csv")):
                        if frames.resolve() not in owned:
                            self.add("ERROR", "STRUCTURAL_ORPHAN", frames, "frames absent from owner outputs")
            else:
                self.unowned_directory(directory, path.name)
        for directory in sorted((root / "batches").glob("*")):
            if directory.is_dir():
                path = directory / "analysis_batch.json"
                if path.exists():
                    self.check(path, lambda p=path: self.batch(p))
                else:
                    self.unowned_directory(directory, path.name)
        for path, value in sorted(self.runs.items()):
            batch = self.batches.get(value["analysis_batch_id"])
            if batch is not None:
                self.check(path, lambda p=path, v=value, b=batch: require(
                    str(p) in [str(self.path(r)) for r in b["run_manifests"]] and
                    v["analysis_run_id"] in b["analysis_run_ids"], "OWNER_MISMATCH", "run omitted from declared batch"))
            elif value["status"] == "completed" or any(o.get("kind") == "batch_output" for o in value["outputs"]):
                self.add("ERROR", "MISSING_ARTIFACT", path, "completed/shared-output run requires its batch authority")
        # The same Patch 5 guard indexes failed and running raw authorities too.
        candidates = [(v["inputs"]["recording"]["sha256"], v["recording_id"]) for v in self.runs.values()
                      if v.get("analysis_mode") == "extract_raw" and isinstance(v["inputs"].get("recording"), dict)
                      and digest_value(v["inputs"]["recording"].get("sha256"))]
        if candidates:
            sha, rid = candidates[0]
            self.check(root, lambda: self.reuse(analysis.validate_raw_identity, sha, rid,
                                               analysis_dir=root, code="IDENTITY_MISMATCH"))
            by_id = {}
            for sha, rid in candidates:
                by_id.setdefault(rid, set()).add(sha.lower())
            for rid, hashes in sorted(by_id.items()):
                if len(hashes) > 1:
                    self.add("ERROR", "IDENTITY_MISMATCH", root / rid, "same recording_id has different raw content")
        for path in sorted(root.glob("*_frames.csv.provenance.json")):
            self.check(path, lambda p=path: self.compatibility(p))

    def evidence(self, item, event):
        path = self.reuse(selection.resolve_artifact, self.root, item["path"])
        self.record(dict(path=str(path), sha256=item["sha256"]), hash_required=True)
        # PROV-011: each evidence[] edge has historical-evidence semantics,
        # independent of event action. Patch 6 separately validates selected
        # sources with completion required, even when they also occur here.
        if item["kind"] == "capture_provenance":
            self.capture(path, item["recording_id"], event)
        elif item["kind"] == "quality":
            self.quality(path, item["recording_id"])
        elif item["kind"] == "canonical_frames":
            entry = self.canonical(path, historical_output=True)
            require(entry["recording_id"] == item["recording_id"], "IDENTITY_MISMATCH", "frames evidence identity mismatch")
        elif item["kind"] == "analysis_manifest":
            self.analysis_run(path)
            value = self.document(path)
            require(value["recording_id"] == item["recording_id"], "IDENTITY_MISMATCH", "analysis evidence identity mismatch")
            for output in value["outputs"]:
                if output.get("kind") == "frames":
                    self.canonical(self.path(output["path"]), historical_output=True)

    def selections(self):
        ledger = self.root / selection.LEDGER_PATH
        if ledger.exists():
            events = self.check(ledger, lambda: self.reuse(selection.read_selection_events, self.root, code="GRAPH_INVALID"))
            if events is not None:
                for event in events:
                    for item in event["evidence"]:
                        self.check(self.root / item["path"], lambda i=item, e=event: self.evidence(i, e))
        for path in sorted((self.root / "manifests/datasets").glob("*.json")):
            self.check(path, lambda p=path: self.reuse(selection.resolve_dataset_manifest, p, self.root, code="GRAPH_INVALID"))

    def lineage(self, directory, manifest, path):
        reference = manifest["sample_lineage"]
        require(reference.get("schema_version") == rf.LINEAGE_SCHEMA, "SCHEMA_INVALID", "invalid sample-lineage schema")
        data = self.bytes(path)
        rows = []
        for line in data.splitlines(keepends=True):
            row = self.reuse(selection._json, line, code="TORN_AUTHORITY")
            require(isinstance(row, dict), "SCHEMA_INVALID", "sample lineage row must be an object")
            expected = (json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
            require(line == expected, "SERIALIZATION_INVALID", "lineage requires canonical UTF-8 JSONL + LF")
            rows.append(row)
        require(type(reference.get("row_count")) is int and reference["row_count"] == len(rows),
                "SCHEMA_INVALID", "sample lineage row_count mismatch")
        keys, source_keys, indices = set(), set(), {}
        for row in rows:
            self.reuse(rf.validate_sample_lineage_row, row, keys)
            require(row["experiment_run_id"] == directory.name, "IDENTITY_MISMATCH", "lineage experiment identity mismatch")
            group = row["dataset_track"], row["feature_mode"]
            index = row["sample_index"]
            require(type(index) is int and index == indices.get(group, 0), "IDENTITY_MISMATCH",
                    "sample_index must identify source order within track/mode")
            indices[group] = index + 1
            if row["source_kind"] == "canonical_frames":
                require(row["dataset_track"] == "ours_external", "IDENTITY_MISMATCH", "canonical lineage track mismatch")
                matches = [e for e in manifest["inputs"]["ours"] if all(row[k] == e.get(k) for k in
                           ("recording_id", "analysis_run_id", "subject", "round", "frames_path", "frames_sha256"))]
                require(len(matches) == 1, "OWNER_MISMATCH", "lineage source differs from experiment canonical input")
                entry = self.canonical(self.path(row["frames_path"]))
                require(all(entry[k] == matches[0][k] for k in entry), "OWNER_MISMATCH", "lineage canonical source mismatch")
                with self.path(row["frames_path"]).open(encoding="utf-8-sig", newline="") as stream:
                    labels = {int(r["step"]): r["label"] for r in csv.DictReader(stream)}
                require(type(row["step"]) is int and labels.get(row["step"]) == row["label"],
                        "IDENTITY_MISMATCH", "lineage step/label differs from source")
                for field in ("calibration_reference_step", "relative_reference_step"):
                    if row[field] is not None:
                        require(type(row[field]) is int and labels.get(row[field]) == "upright" and
                                row["reference_recording_id"] == row["recording_id"] and
                                row["reference_analysis_run_id"] == row["analysis_run_id"],
                                "OWNER_MISMATCH", "lineage reference identity/step mismatch")
                source = (row["recording_id"], row["analysis_run_id"], row["step"])
            else:
                kind, track = {"paper_dataset": ("paper", "paper_loso"),
                               "multiposture_dataset": ("multiposture", "multiposture_loso")}[row["source_dataset_id"]]
                item = manifest["inputs"].get(kind)
                require(isinstance(item, dict) and row["dataset_track"] == track and
                        row["source_dataset_id"] == item.get("source_dataset_id") and
                        row["source_file_path"] == item.get("path") and row["source_file_sha256"] == item.get("sha256"),
                        "OWNER_MISMATCH", "external lineage source differs from experiment input")
                require(all(row[k] is None for k in ("round", "step", "calibration_reference_step", "relative_reference_step")),
                        "SCHEMA_INVALID", "external lineage has canonical-only fields")
                source = (row["source_dataset_id"], row["source_file_path"], row["source_row_number"])
            key = group + source
            require(key not in source_keys, "GRAPH_INVALID", "duplicate lineage source key")
            source_keys.add(key)

    def experiment(self, path):
        value = self.document(path)
        self.lifecycle(value, "rf-experiment-provenance/1.0.0")
        directory = path.parent
        require(value.get("experiment_run_id") == directory.name, "IDENTITY_MISMATCH", "RF directory/manifest identity mismatch")
        if value["status"] != "completed":
            self.add("WARNING", "INCOMPLETE_NONTERMINAL", path, f"preserved {value['status']} RF run")
        inputs = value["inputs"]
        require(all(k in inputs for k in ("paper", "multiposture", "ours")) and isinstance(inputs["ours"], list),
                "SCHEMA_INVALID", "invalid RF inputs")
        for kind in ("paper", "multiposture"):
            if inputs[kind] is not None:
                self.check(path, lambda i=inputs[kind]: self.record(i, hash_required=True))
        for entry in inputs["ours"]:
            def canonical_entry(e=entry):
                require(isinstance(e, dict), "SCHEMA_INVALID", "invalid canonical RF input")
                for prefix in ("frames", "analysis_manifest"):
                    self.record(dict(path=e.get(prefix + "_path"), sha256=e.get(prefix + "_sha256")), hash_required=True)
                actual = self.canonical(self.path(e.get("frames_path")))
                require(actual == e, "OWNER_MISMATCH", "RF canonical input differs from recorded source")
            self.check(path, canonical_entry)
        self.reuse(rf.reject_input_ambiguity, inputs["ours"], code="GRAPH_INVALID")
        dataset = value.get("dataset_manifest")
        require(isinstance(dataset, dict) and all(k in dataset for k in ("dataset_manifest_id", "path", "sha256")),
                "SCHEMA_INVALID", "invalid RF dataset manifest reference")
        if dataset["path"] is not None:
            def binding():
                sources, reference = self.reuse(selection.resolve_dataset_manifest, dataset["path"], self.root, dataset["sha256"])
                require(reference == dataset and sources == inputs["ours"], "OWNER_MISMATCH", "RF/dataset resolved source binding mismatch")
            self.check(path, binding)
        else:
            require(dataset["sha256"] is None and dataset["dataset_manifest_id"] is None,
                    "SCHEMA_INVALID", "partial RF dataset manifest reference")
        lineage = value.get("sample_lineage")
        require(isinstance(lineage, dict) and lineage.get("path") == "sample_lineage.jsonl" and
                lineage.get("schema_version") == rf.LINEAGE_SCHEMA, "SCHEMA_INVALID", "invalid lineage reference")
        lineage_path = directory / "sample_lineage.jsonl"
        if lineage.get("sha256") is not None or value["status"] == "completed":
            self.check(lineage_path, lambda: self.record(lineage, base=directory, hash_required=True))
            self.check(lineage_path, lambda: self.lineage(directory, value, lineage_path))
        elif lineage_path.exists():
            self.add("WARNING", "INCOMPLETE_NONTERMINAL", lineage_path, "lineage publication has no committed hash yet")
        output_paths = set()
        for item in value["outputs"]:
            def output(i=item):
                target = self.path(i.get("path"))
                require(target.parent == directory and i.get("kind") == target.name,
                        "OWNER_MISMATCH", "RF output path/kind differs from owner directory")
                require(target not in output_paths, "OWNER_MISMATCH", "duplicate RF output binding")
                output_paths.add(target)
                self.record(i, hash_required=True)
            self.check(path, output)
        if value["status"] == "completed":
            for name in ("rf_results.csv", "rf_results.txt"):
                target = directory / name
                self.check(target, lambda p=target: self.exists(p))
                if target not in output_paths:
                    self.add("ERROR", "OWNER_MISMATCH", target, "completed RF output absent from authority")
        result = directory / "rf_results.csv"
        if result in output_paths and result.is_file():
            def result_fields():
                reader = csv.DictReader(io.StringIO(self.reuse(bytes.decode, self.bytes(result), "utf-8-sig",
                                                              code="SERIALIZATION_INVALID")))
                require(all(k in (reader.fieldnames or []) for k in rf.RESULT_LINEAGE_FIELDS),
                        "SCHEMA_INVALID", "RF result missing lineage fields")
                expected = (directory.name, dataset["sha256"] or "", lineage["path"], lineage["sha256"])
                for row in reader:
                    require(tuple(row.get(k) for k in rf.RESULT_LINEAGE_FIELDS) == expected,
                            "IDENTITY_MISMATCH", "RF result lineage fields contradict experiment authority")
            self.check(result, result_fields)

    def models(self):
        path = self.root / "mediapipe_model_lock.json"
        self.exists(path)  # Tracked authority, unlike the optional runtime cache.
        self.bytes(path)
        lock = self.reuse(analysis.load_model_lock, path)
        for entry in lock.values():
            model = self.root / "models" / entry["filename"]
            if os.path.lexists(model):
                self.check(model, lambda p=model, e=entry: self.record(dict(path=str(p), sha256=e["sha256"]), hash_required=True))
            else:
                self.add("INFO", "INCOMPLETE_NONTERMINAL.MODEL_CACHE_ABSENT", model, "optional local model cache absent")

    def run(self):
        before = managed_inventory(self.root)
        for name in sorted(before):
            path = self.root / name
            if temporary(path):
                self.add("WARNING", "TEMP_RESIDUE", path, "recognized producer publication residue")
        self.captures(before)
        self.analyses()
        self.selections()
        for directory in sorted((self.root / "results").glob("er_*")):
            if directory.is_dir():
                path = directory / "experiment_manifest.json"
                if path.exists():
                    self.check(path, lambda p=path: self.experiment(p))
                else:
                    self.unowned_directory(directory, path.name)
        self.check(self.root / "mediapipe_model_lock.json", self.models)
        if before != managed_inventory(self.root):
            self.add("ERROR", "REPOSITORY_CHANGED_DURING_CHECK", self.root, "managed path inventory changed during audit")
        return AuditResult(tuple(sorted(self.findings, key=lambda f:
                           (SEVERITIES.index(f.severity), f.code, f.artifact, f.reason))))


def audit_repository(repo_root=None):
    return Auditor(Path(__file__).resolve().parent if repo_root is None else repo_root).run()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args(argv)
    try:
        result = audit_repository(args.repo_root)
    except Exception as error:
        print(f"CHECKER_FAILURE: {type(error).__name__}: {error}", file=sys.stderr)
        return 2
    for finding in result.findings:
        print(f"{finding.severity} {finding.code} {finding.artifact}: {finding.reason}")
    print(" ".join(f"{s}={result.counts[s]}" for s in SEVERITIES) +
          (" FAIL" if result.exit_code else " PASS"))
    return result.exit_code


if __name__ == "__main__":
    sys.exit(main())
