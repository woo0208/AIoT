"""Patch 8 pre-lock structural evidence and CLOSED classifier (CAP-005 §39, §41, §44–§48).

Only CAP-005-permitted pre-lock evidence is read here:
  - recording identity inventory under data/ (file names only),
  - `_camera.json` keys `recording_id` and `record_file` only,
  - structured child exit status and orchestrator-observed actions,
  - post-exit D455/USB enumeration,
  - a whitelisted exception-class identifier from sealed stderr,
  - a raw readability probe limited to exists/openable/>=1 color/>=1 depth.
Quality, samples, markers, sealed log bodies, frame counts, ratios, gaps, landmarks,
gate evidence, file size and mtime are never read or used here.

Hardware probes run as `python patch8_prelock.py <probe>` child processes so an SDK
fault cannot take down the orchestrator; each prints one JSON object.
"""
from dataclasses import dataclass
from datetime import datetime
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import re
import signal
import sys

import patch8_ledger as ledger
import patch8_protocol as p8


CAPTURE_SUFFIXES = (".db3", ".bag", "_camera.json", "_markers.csv", "_samples.csv", "_quality.json")
RAW_SUFFIXES = (".db3", ".bag")
RESERVATION_KEYS = ("recording_id", "record_file")
RAW_PROBE_FIELDS = ("exists", "openable", "color_frame", "depth_frame")
WHITELISTED_EXCEPTION_CLASSES = ("RuntimeError", "KeyboardInterrupt")
UNLISTED_EXCEPTION = "UNLISTED"
POWER_EVIDENCE_KINDS = ("host_power_event", "ups_power_event", "device_power_event")

# Structured exit status of the dedicated static child (patch8_static_capture.py).
STATIC_EXIT_STATUS = {0: "completed", 10: "operator_abort", 11: "record_start_failed", 12: "stream_failure"}
STATIC_EXIT_CODES = {name: code for code, name in STATIC_EXIT_STATUS.items()}
STATIC_SDK_FAILURE_STATUSES = ("record_start_failed", "stream_failure")


# ---------------------------------------------------------------- recording identity binding (§39)
def recording_inventory(data_dir):
    """Sorted recording identity stems from capture file names (no content is opened)."""
    directory = Path(data_dir)
    if not directory.is_dir():
        return []
    identities = set()
    for path in directory.iterdir():
        for suffix in CAPTURE_SUFFIXES:
            if path.name.endswith(suffix) and len(path.name) > len(suffix):
                identities.add(path.name[:-len(suffix)])
                break
    return sorted(identities)


def new_recordings(before, after):
    return sorted(set(after) - set(before))


def read_reservation_keys(camera_path):
    """§39: before lock only `recording_id` and `record_file` may be used from _camera.json."""
    try:
        value = json.loads(Path(camera_path).read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    if not isinstance(value, dict) or not all(k in value for k in RESERVATION_KEYS):
        return None
    return {k: value[k] for k in RESERVATION_KEYS}


def valid_reservation(data_dir, identity, subject, rnd):
    """A recording reservation is valid once its camera sidecar names the same identity."""
    keys = read_reservation_keys(Path(data_dir) / (identity + "_camera.json"))
    return (keys is not None and keys["recording_id"] == identity and
            isinstance(identity, str) and identity.startswith(f"{subject}_r{rnd}_") and
            (keys["record_file"] is None or keys["record_file"] in (identity + ".db3", identity + ".bag")))


def raw_path(data_dir, identity):
    """Structural raw existence only: reservation `record_file` or the same-stem SDK formats."""
    keys = read_reservation_keys(Path(data_dir) / (identity + "_camera.json")) or {}
    names = [keys.get("record_file")] if keys.get("record_file") in (identity + ".db3", identity + ".bag") else []
    names += [identity + suffix for suffix in RAW_SUFFIXES]
    for name in names:
        if (Path(data_dir) / name).is_file():
            return Path(data_dir) / name
    return None


# ---------------------------------------------------------------- sealed-log extraction (§47.5)
def extract_exception_class(stderr_path, max_bytes=65536):
    """Return only a whitelisted exception class identifier; never any message text."""
    try:
        with open(stderr_path, "rb") as stream:
            stream.seek(0, 2)
            size = stream.tell()
            stream.seek(max(0, size - max_bytes))
            text = stream.read().decode("utf-8", errors="replace")
    except OSError:
        return None
    index = text.rfind("Traceback (most recent call last):")
    if index < 0:
        return None
    for line in text[index:].splitlines()[1:]:
        if not line or line[0].isspace():
            continue
        match = re.match(r"([A-Za-z_][A-Za-z0-9_.]*)(?::|$)", line)
        name = match.group(1).rsplit(".", 1)[-1] if match else None
        return name if name in WHITELISTED_EXCEPTION_CLASSES else UNLISTED_EXCEPTION
    return UNLISTED_EXCEPTION


# ---------------------------------------------------------------- hardware probes (child processes)
def probe_raw_readability(path, rs=None, timeout_ms=5000):
    """§47.6: exists / openable / >=1 color / >=1 depth. Stops at the first of each; no counts."""
    result = dict.fromkeys(RAW_PROBE_FIELDS, False)
    path = Path(path)
    result["exists"] = path.is_file()
    if not result["exists"]:
        return result
    if rs is None:
        import pyrealsense2 as rs
    pipe, config = rs.pipeline(), rs.config()
    try:
        config.enable_device_from_file(str(path), repeat_playback=False)
        profile = pipe.start(config)
    except Exception:
        return result
    result["openable"] = True
    try:
        profile.get_device().as_playback().set_real_time(False)
        while not (result["color_frame"] and result["depth_frame"]):
            ok, frames = pipe.try_wait_for_frames(timeout_ms)
            if not ok:
                break
            result["color_frame"] = result["color_frame"] or bool(frames.get_color_frame())
            result["depth_frame"] = result["depth_frame"] or bool(frames.get_depth_frame())
    except Exception:
        pass
    finally:
        try:
            pipe.stop()
        except Exception:
            pass
    return result


def enumerate_devices(rs=None):
    """§47.5 post-exit D455/USB enumeration (device identity only)."""
    if rs is None:
        import pyrealsense2 as rs
    devices = []
    for device in rs.context().query_devices():
        def info(key):
            try:
                return device.get_info(key) if device.supports(key) else None
            except Exception:
                return None
        devices.append(dict(name=info(rs.camera_info.name), serial=info(rs.camera_info.serial_number),
                            firmware=info(rs.camera_info.firmware_version),
                            usb_type=info(rs.camera_info.usb_type_descriptor)))
    return {"probe_ok": True, "devices": sorted(devices, key=lambda d: str(d["serial"]))}


def package_versions():
    versions = {}
    for package in ("pyrealsense2", "opencv-python", "numpy", "mediapipe", "pillow"):
        try:
            versions[package] = importlib.metadata.version(package)
        except Exception:
            versions[package] = None
    return versions


def realsense_sdk_version(rs, package_version):
    """Best available explicit librealsense identity exposed by the Python binding."""
    value = getattr(rs, "__version__", None)
    if value is None:
        getter = getattr(rs, "get_api_version", None)
        try:
            value = getter() if callable(getter) else None
        except Exception:
            value = None
    return str(value) if value is not None else package_version


def collect_environment(rs=None):
    """§9 environment snapshot recorded at each physical session start."""
    if rs is None:
        import pyrealsense2 as rs
    enumeration = enumerate_devices(rs)
    d455 = [d for d in enumeration["devices"] if d["name"] and "D455" in d["name"]]
    packages = package_versions()
    host = platform.node()
    environment = dict(capture_host=host, analysis_host=host, os=platform.platform(),
                       python=platform.python_version(), packages=packages,
                       realsense_sdk_version=realsense_sdk_version(rs, packages.get("pyrealsense2")),
                       realsense_devices=enumeration["devices"],
                       d455_serial=None, d455_firmware=None, usb_type=None, depth_scale_m=None,
                       device_options={}, stream_profiles={
                           "color": {"width": 1280, "height": 720, "format": "bgr8", "fps": 15},
                           "depth": {"width": 848, "height": 480, "format": "z16", "fps": 15},
                           "align_to": "color"})
    if len(d455) != 1:
        return environment
    environment.update(d455_serial=d455[0]["serial"], d455_firmware=d455[0]["firmware"],
                       usb_type=d455[0]["usb_type"])
    try:
        device = next(d for d in rs.context().query_devices()
                      if d.get_info(rs.camera_info.serial_number) == d455[0]["serial"])
        sensor = device.first_depth_sensor()
        environment["depth_scale_m"] = sensor.get_depth_scale()
        for name in ("visual_preset", "emitter_enabled", "laser_power", "enable_auto_exposure"):
            option = getattr(rs.option, name, None)
            if option is not None and sensor.supports(option):
                environment["device_options"]["depth." + name] = sensor.get_option(option)
    except Exception as error:
        environment["device_options"]["error"] = type(error).__name__
    return environment


def run_probe(command, *, runner, timeout):
    """Run a probe child; any failure is recorded as probe_ok = false (never machine evidence)."""
    try:
        completed = runner([sys.executable, str(Path(__file__).resolve()), *command],
                           capture_output=True, timeout=timeout)
        if completed.returncode != 0:
            return None
        value = json.loads(completed.stdout.decode("utf-8"))
        return value if isinstance(value, dict) else None
    except Exception:
        return None


# ---------------------------------------------------------------- power evidence (§47.4)
def validate_power_evidence(record, execution_dir, window_start_utc, window_end_utc):
    """Independent power-loss evidence: an evidence file under the execution directory whose
    SHA-256 matches and whose reported power event lies inside the attempt window."""
    if not isinstance(record, dict) or set(record) != {"kind", "path", "sha256", "event_time_utc"}:
        return None
    if record["kind"] not in POWER_EVIDENCE_KINDS or not isinstance(record["path"], str):
        return None
    root = Path(execution_dir).resolve()
    path = (root / record["path"]).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        return None
    if hashlib.sha256(path.read_bytes()).hexdigest() != record["sha256"]:
        return None
    try:
        when = datetime.fromisoformat(str(record["event_time_utc"]).replace("Z", "+00:00"))
        start = datetime.fromisoformat(window_start_utc.replace("Z", "+00:00"))
        end = datetime.fromisoformat(window_end_utc.replace("Z", "+00:00"))
    except ValueError:
        return None
    if when.utcoffset() is None or not start <= when <= end:
        return None
    return dict(record)


# ---------------------------------------------------------------- closed classifier (§47)
@dataclass(frozen=True)
class PrelockEvidence:
    slot_kind: str
    stage: str
    bound_recording_ids: tuple = ()
    exit_code: int = None
    signal: int = None
    orchestrator_timeout_kill: bool = False
    operator_signal_observed: str = None
    operator_declaration: str = "unknown"
    exception_class: str = None
    static_exit_status: str = None
    raw_exists: bool = None
    raw_probe: dict = None
    enumeration: dict = None
    power_evidence: dict = None
    observations: tuple = ()
    attempt_index: int = 1
    canonical_static_take_exists: bool = False
    execution_failed: bool = False

    @property
    def static(self):
        return self.slot_kind == p8.STATIC

    @property
    def normal_exit(self):
        return (self.exit_code == 0 and self.signal is None and not self.orchestrator_timeout_kill and
                self.operator_signal_observed is None)

    @property
    def not_operator(self):
        return (self.operator_declaration == "not_operator_initiated" and self.operator_signal_observed is None and
                not self.orchestrator_timeout_kill)

    @property
    def post_reservation(self):
        return self.stage == "post_reservation"

    @property
    def raw_absent(self):
        return self.post_reservation and self.raw_exists is False

    @property
    def raw_probe_failed(self):
        probe = self.raw_probe
        return (self.post_reservation and self.raw_exists is True and isinstance(probe, dict) and
                set(probe) == set(RAW_PROBE_FIELDS) and probe["exists"] and
                not (probe["openable"] and probe["color_frame"] and probe["depth_frame"]))

    @property
    def sdk_failure_signal(self):
        return self.exception_class == "RuntimeError" or self.static_exit_status in STATIC_SDK_FAILURE_STATUSES

    def pinned_serial(self, present):
        enumeration = self.enumeration
        return (isinstance(enumeration, dict) and enumeration.get("probe_ok") is True and
                enumeration.get("pinned_serial_present") is present)


@dataclass(frozen=True)
class Classification:
    stage: str
    reason_code: str
    acquisition_valid: bool
    retry_allowed: bool
    rule_id: str
    evidence_used: tuple


def _sigint(e):
    return e.exception_class == "KeyboardInterrupt" or e.signal == int(signal.SIGINT)


# Ordered, first match wins. Every row names the only evidence it may use. Anything not
# matched by a specific row ends in a fail-closed acquisition-valid row (no retry).
CLASSIFIER_RULES = (
    ("R01_AMBIGUOUS_BINDING", p8.UNCLASSIFIED_TERMINATION, ("bound_recording_ids",),
     lambda e: len(e.bound_recording_ids) > 1),
    ("R02_GUIDE_TIMEOUT", p8.GUIDE_NOT_SATISFIED, ("orchestrator_timeout_kill", "stage"),
     lambda e: not e.static and e.orchestrator_timeout_kill),
    ("R03_OPERATOR_SIGNAL_OBSERVED", p8.MANUAL_ABORT, ("operator_signal_observed",),
     lambda e: e.operator_signal_observed is not None),
    ("R04_CHILD_SIGINT", p8.MANUAL_ABORT, ("exception_class", "signal"), _sigint),
    ("R05_STATIC_Q_ABORT", p8.MANUAL_ABORT, ("static_exit_status",),
     lambda e: e.static and e.static_exit_status == "operator_abort"),
    ("R06_GUIDE_Q_PRE_RESERVATION", p8.GUIDE_NOT_SATISFIED, ("stage", "exit_code"),
     lambda e: not e.static and not e.post_reservation and e.normal_exit),
    ("R07_OPERATOR_DECLARED", p8.MANUAL_ABORT, ("operator_declaration",),
     lambda e: e.operator_declaration == "operator_initiated"),
    ("R08_STATIC_CAMERA_MOUNT_DISTURBED", p8.CAMERA_MOUNT_PHYSICALLY_DISTURBED, ("observations",),
     lambda e: e.static and p8.CAMERA_MOUNT_PHYSICALLY_DISTURBED in e.observations),
    ("R09_POWER_FAILURE", p8.POWER_FAILURE, ("operator_declaration", "power_evidence"),
     lambda e: e.not_operator and e.power_evidence is not None),
    ("R10_RAW_FILE_NOT_CREATED", p8.RAW_FILE_NOT_CREATED,
     ("operator_declaration", "stage", "raw_exists", "exit_code", "exception_class", "static_exit_status",
      "enumeration"),
     lambda e: e.not_operator and e.raw_absent and not e.normal_exit and
     (e.sdk_failure_signal or e.pinned_serial(False))),
    ("R11_RAW_FILE_UNREADABLE_OR_CORRUPT", p8.RAW_FILE_UNREADABLE_OR_CORRUPT,
     ("operator_declaration", "stage", "raw_exists", "raw_probe"),
     lambda e: e.not_operator and e.raw_probe_failed),
    ("R12_CAMERA_DISCONNECT", p8.CAMERA_DISCONNECT, ("operator_declaration", "exit_code", "enumeration"),
     lambda e: e.not_operator and not e.normal_exit and e.pinned_serial(False)),
    ("R13_USB_STREAM_FAILURE", p8.USB_STREAM_FAILURE,
     ("operator_declaration", "exit_code", "enumeration", "exception_class", "static_exit_status"),
     lambda e: e.not_operator and not e.normal_exit and e.pinned_serial(True) and e.sdk_failure_signal),
    ("R14_STATIC_EXTERNAL_INTERRUPTION", p8.EXTERNAL_PHYSICAL_INTERRUPTION, ("observations", "exit_code"),
     lambda e: e.static and e.normal_exit and p8.EXTERNAL_PHYSICAL_INTERRUPTION in e.observations),
    ("R15_UNCLASSIFIED_ABNORMAL_TERMINATION", p8.UNCLASSIFIED_TERMINATION, ("exit_code", "signal"),
     lambda e: not e.normal_exit),
    ("R16_NO_RAW_AFTER_NORMAL_EXIT", p8.UNCLASSIFIED_TERMINATION, ("stage", "raw_exists"),
     lambda e: not e.post_reservation or e.raw_exists is not True),
    ("R17_ACQUISITION_COMPLETED", None, ("exit_code", "stage", "raw_exists"), lambda e: True),
)


def classify(evidence):
    if evidence.stage not in ledger.STAGES or evidence.slot_kind not in p8.SESSION_KINDS or \
            evidence.operator_declaration not in ledger.DECLARATIONS:
        raise ValueError("invalid pre-lock evidence")
    slot_kind = evidence.slot_kind
    for rule_id, reason, used, predicate in CLASSIFIER_RULES:
        if predicate(evidence):
            break
    if reason not in ledger.allowed_lock_reasons(slot_kind):
        raise ValueError(f"classifier produced {reason!r}, not permitted for {slot_kind}")
    retry = ledger.lock_retry_allowed(slot_kind, reason, evidence.attempt_index,
                                      evidence.canonical_static_take_exists, evidence.execution_failed)
    return Classification(evidence.stage, reason, ledger.acquisition_valid_for(reason), retry, rule_id, tuple(used))


def evidence_record(evidence, classification):
    """JSON-safe pre-lock evidence summary (wrapper state; contains no result-bearing data)."""
    value = {name: getattr(evidence, name) for name in evidence.__dataclass_fields__}
    value["bound_recording_ids"] = list(evidence.bound_recording_ids)
    value["observations"] = list(evidence.observations)
    value["classification"] = dict(stage=classification.stage, reason_code=classification.reason_code,
                                   acquisition_valid=classification.acquisition_valid,
                                   retry_allowed=classification.retry_allowed, rule_id=classification.rule_id,
                                   evidence_used=list(classification.evidence_used))
    return value


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["raw-probe"] and len(argv) == 2:
        value = probe_raw_readability(argv[1])
    elif argv == ["enumerate"]:
        value = enumerate_devices()
    elif argv == ["environment"]:
        value = collect_environment()
    else:
        print("usage: patch8_prelock.py raw-probe <path> | enumerate | environment", file=sys.stderr)
        return 2
    print(json.dumps(ledger.json_safe(value), sort_keys=True, ensure_ascii=False, allow_nan=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
