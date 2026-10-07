"""Patch 8 frozen protocol values (CAP-005); data only, no hardware access.

Every value here is copied from docs/foundation/PATCH_08_actual_d455_end_to_end_validation.md.
Changing any of them after observing Patch 8 results requires a new Decision Log entry
with `Supersedes: CAP-005` (Foundation §3.1); implementation must not tune them.
"""
from dataclasses import dataclass
import math


# ---------------------------------------------------------------- identities (§26, §27, §35)
LEDGER_FORMAT_VERSION = "patch8-validation-control/1.0.0"
STATIC_PROTOCOL_VERSION = "patch8-d455-static-validation-v1.0.0"
PRODUCTION_PROTOCOL_VERSION = "capture-forward-face-v2.0.0"
CAPTURE_PROVENANCE_SCHEMA = "capture-provenance/1.0.0"
DATASET_ROLE = "pilot"                       # §7.1 reserved validation subject role
STATIC_MARKER_LABEL = "upright"              # §28
VALIDATION_ROOT = "validation/patch8"        # §23 validation/patch8/<execution_id>/
LEDGER_FILENAME = "patch8_validation_ledger.jsonl"   # §35
EXECUTION_REGISTRY_PATH = "docs/research/PATCH_08_EXECUTION_REGISTRY.md"   # §15 (not created here)

# ---------------------------------------------------------------- static grid (§3, §4.2, §32, §72)
STATIC_GRID_M = (0.60, 0.70, 0.80, 0.90, 1.00)
MANDATORY_ANCHORS_M = (0.70, 0.80)
STATIC_REPETITIONS = 3
STATIC_HOLD_S = 10.0
FORMAL_INITIAL_SEATING_RANGE_M = (0.70, 0.80)   # §74; never widened from the envelope

# ---------------------------------------------------------------- timing / placement (§11, §31, §47.1)
INITIAL_WARMUP_S = 60.0
SETTLING_S = 10.0
GUIDE_RESERVATION_TIMEOUT_S = 15.0
STATIC_PLACEMENT_TOLERANCE_M = 0.02
PRODUCTION_INITIAL_PLACEMENT_M = 0.75
PRODUCTION_PLACEMENT_TOLERANCE_M = 0.02

# ---------------------------------------------------------------- windows / coverage (§55, §56, §75)
STATIC_WINDOW_START_S = 1.0     # 1.0 <= t   (inclusive)
STATIC_WINDOW_END_S = 9.5       # t < 9.5    (exclusive)
FORWARD_TRIM_START_S = 1.0      # 1.0 < t    (exclusive)
FORWARD_TRIM_END_S = 0.5        # t < phase_duration - 0.5 (exclusive)
FORWARD_PHASE_DURATION_S = 10.0  # §75.1 / §75.2 denominator applies to the 10 s phases
EXPECTED_FRAME_DENOMINATOR = 127.5
FRAME_COVERAGE_MIN = 0.85
MIN_WINDOW_ROWS = 109           # derived: ceil(0.85 * 127.5); asserted below

# ---------------------------------------------------------------- acceptance thresholds (§57–§70)
LANDMARK_RATE_MIN = 0.95
CONDITIONAL_DEPTH_RATE_MIN = 0.95
COMPLETE_RGBD_RATE_MIN = 0.90
MIN_VALID_N = 30
DEPTH_TEMPORAL_SD_MAX_MM = 10.0
WITHIN_TAKE_CV_MAX = 0.03
BETWEEN_TAKE_SPREAD_MAX = 0.03
DISTANCE_STABILITY_MAX = 0.05
FACE_DEPTH_SOURCE_REQUIRED = "bbox_roi"

# Exact quantity lists (§62, §67, §68, §70). Order is reporting order only.
DEPTH_SERIES = ("z_face_m", "z_lsh_m", "z_rsh_m", "left_hip_depth_m", "right_hip_depth_m")
WITHIN_TAKE_CV_QUANTITIES = ("shoulder_width_3d", "hip_width_3d", "trunk_length_3d")
BETWEEN_TAKE_SPREAD_QUANTITIES = ("shoulder_width_3d", "hip_width_3d", "trunk_length_3d")
DISTANCE_STABILITY_QUANTITIES = ("ipd_cm", "shoulder_width_3d", "hip_width_3d", "trunk_length_3d")

# ---------------------------------------------------------------- production gate (CAP-001 / §76)
# Read-only mirror of capture_d455 constants for evidence consistency checks; a test
# asserts equality with the production module so drift is detected, never absorbed.
FORWARD_GATE_MIN_M = 0.08
FORWARD_GATE_MAX_M = 0.12
FORWARD_GATE_ABS_TOL = 1e-12
FORWARD_VALIDATION_SOURCE = "face_only"
FORWARD_BANDS_M = {
    "below": (0.05, 0.07),
    "pass": (0.09, 0.11),
    "above": (0.13, 0.15),
}
FORWARD_GATE_REASON_BY_BAND = {"below": ["below_target"], "pass": [], "above": ["above_target"]}
BODY_ONLY_REQUIRED_REASONS = ["insufficient_current_face_samples"]   # §80

# Mirror of capture_d455.SEQ_CORE / SEQ_FULL (asserted equal by tests).
PRODUCTION_SEQUENCES = {
    "core": (("upright", 20), ("forward_head", 10), ("upright", 5), ("body_forward", 10), ("upright", 5)),
    "full": (("upright", 20), ("forward_head", 10), ("upright", 5), ("body_forward", 10), ("upright", 5),
             ("lean_back", 10), ("lean_left", 10), ("lean_right", 10), ("upright", 5)),
}

# ---------------------------------------------------------------- attempts / reasons (§44–§49, §79–§81)
MAX_ATTEMPTS = 3

GUIDE_NOT_SATISFIED = "GUIDE_NOT_SATISFIED"
MANUAL_ABORT = "MANUAL_ABORT"
CAMERA_DISCONNECT = "CAMERA_DISCONNECT"
USB_STREAM_FAILURE = "USB_STREAM_FAILURE"
POWER_FAILURE = "POWER_FAILURE"
RAW_FILE_NOT_CREATED = "RAW_FILE_NOT_CREATED"
RAW_FILE_UNREADABLE_OR_CORRUPT = "RAW_FILE_UNREADABLE_OR_CORRUPT"
UNCLASSIFIED_TERMINATION = "UNCLASSIFIED_TERMINATION"
EXTERNAL_PHYSICAL_INTERRUPTION = "EXTERNAL_PHYSICAL_INTERRUPTION"
CAMERA_MOUNT_PHYSICALLY_DISTURBED = "CAMERA_MOUNT_PHYSICALLY_DISTURBED"
TARGET_MISS = "TARGET_MISS"

MACHINE_INVALID_REASONS = (CAMERA_DISCONNECT, USB_STREAM_FAILURE, POWER_FAILURE,
                           RAW_FILE_NOT_CREATED, RAW_FILE_UNREADABLE_OR_CORRUPT)
STATIC_OPERATOR_INVALID_REASONS = (EXTERNAL_PHYSICAL_INTERRUPTION, CAMERA_MOUNT_PHYSICALLY_DISTURBED)
VALID_FAIL_REASONS = (GUIDE_NOT_SATISFIED, MANUAL_ABORT, UNCLASSIFIED_TERMINATION)
OPERATOR_OBSERVATIONS = STATIC_OPERATOR_INVALID_REASONS

# Post-lock canonical outcome labels for production attempts (§79–§81). They describe
# canonical FAIL evidence and never alter the locked acquisition validity.
CANONICAL, TARGET_MISS_OUTCOME = "CANONICAL", TARGET_MISS
POST_LOCK_FAIL_REASONS = (
    GUIDE_NOT_SATISFIED, MANUAL_ABORT, UNCLASSIFIED_TERMINATION,
    "NO_QUALITY_EVIDENCE", "NO_GATE_EVIDENCE", "CLOSER_NULL", "EVIDENCE_INCONSISTENT",
    "REFERENCE_FACE_INSUFFICIENT", "GATE_PASSED_ON_BODY_ONLY_TARGET",
)

# §7.4 camera-pose material change.
POSE_HEIGHT_TOLERANCE_MM = 5.0
POSE_ANGLE_TOLERANCE_DEG = 1.0

# Execution-level FAIL reasons (§7.3, §7.4, §9, §20).
EXECUTION_FAILURE_REASONS = (
    "CAMERA_DISTURBED_AFTER_FIRST_CANONICAL_STATIC_TAKE", "CAMERA_POSE_MATERIAL_CHANGE",
    "ENVIRONMENT_CHANGED", "CODE_CHANGED", "OPERATOR_TERMINATED_EXECUTION",
)

# ---------------------------------------------------------------- slots (§32, §33, §75, §78, §80, §81)
STATIC, FORWARD, BODY_ONLY_NEGATIVE, E2E = "static", "forward", "body_only_negative", "e2e"
SESSION_KINDS = {STATIC: "static-grid", FORWARD: "forward-gate",
                 BODY_ONLY_NEGATIVE: "body-only-negative", E2E: "E2E"}

# CAP-006 resolves the pre-execution CAP-005 sequence gap for forward slots 101–113:
# rounds 101–103 and 111–113 use SEQ_CORE. Existing mappings remain unchanged:
# round 121 uses SEQ_CORE (§80), and round 131 uses SEQ_FULL (§81).


@dataclass(frozen=True)
class Slot:
    round: str
    kind: str
    protocol_version: str
    nominal_distance_m: float = None
    repetition_index: int = None
    designated_phases: tuple = ()
    band: str = None
    sequence_mode: str = None

    @property
    def session_kind(self):
        return SESSION_KINDS[self.kind]


def _build_slots():
    slots = {}
    for repetition in range(1, STATIC_REPETITIONS + 1):
        for index, distance in enumerate(STATIC_GRID_M):
            rnd = str((repetition - 1) * len(STATIC_GRID_M) + index + 1)
            slots[rnd] = Slot(rnd, STATIC, STATIC_PROTOCOL_VERSION, distance, repetition)
    for rnd, phase, band in (("101", "forward_head", "below"), ("102", "forward_head", "pass"),
                             ("103", "forward_head", "above"), ("111", "body_forward", "below"),
                             ("112", "body_forward", "pass"), ("113", "body_forward", "above")):
        slots[rnd] = Slot(rnd, FORWARD, PRODUCTION_PROTOCOL_VERSION, designated_phases=(phase,), band=band,
                          sequence_mode="core")
    slots["121"] = Slot("121", BODY_ONLY_NEGATIVE, PRODUCTION_PROTOCOL_VERSION,
                        designated_phases=("body_forward",), sequence_mode="core")
    slots["131"] = Slot("131", E2E, PRODUCTION_PROTOCOL_VERSION,
                        designated_phases=("forward_head", "body_forward"), sequence_mode="full")
    return slots


SLOTS = _build_slots()
STATIC_ROUNDS = tuple(r for r, s in SLOTS.items() if s.kind == STATIC)
PRODUCTION_ROUNDS = tuple(r for r, s in SLOTS.items() if s.kind != STATIC)

# §75 forward availability population (exact; 121 excluded, 131 both phases separately).
FORWARD_AVAILABILITY_POPULATION = {
    "101": ("forward_head",), "102": ("forward_head",), "103": ("forward_head",),
    "111": ("body_forward",), "112": ("body_forward",), "113": ("body_forward",),
    "131": ("forward_head", "body_forward"),
}


def slot(rnd):
    if rnd not in SLOTS:
        raise ValueError(f"round {rnd!r} is not a CAP-005 Patch 8 slot")
    return SLOTS[rnd]


def static_rounds_at(distance):
    return tuple(r for r in STATIC_ROUNDS if SLOTS[r].nominal_distance_m == distance)


assert math.ceil(FRAME_COVERAGE_MIN * EXPECTED_FRAME_DENOMINATOR) == MIN_WINDOW_ROWS
assert EXPECTED_FRAME_DENOMINATOR == (STATIC_WINDOW_END_S - STATIC_WINDOW_START_S) * 15
assert len(STATIC_ROUNDS) == len(STATIC_GRID_M) * STATIC_REPETITIONS == 15
