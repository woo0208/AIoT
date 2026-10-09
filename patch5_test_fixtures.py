"""Synthetic artifacts for lineage tests and existing controlled numeric tests."""
from contextlib import contextmanager, ExitStack
import csv
import json
from pathlib import Path
import shutil
import sys
from unittest.mock import patch

import rf_experiment as rf
from test_analysis_provenance import analysis


def make_frames(root, rid="P01_r1_take", run="ar_source", rows=None, flat=True):
    root = Path(root).resolve()
    directory = root / rid / run
    directory.mkdir(parents=True)
    path = directory / (rid + "_frames.csv")
    rows = rows if rows is not None else [dict(subject="P01", round="1", step=i + 1, label=lab)
                                         for i, lab in enumerate(rf.LAB5)]
    canonical = []
    for index, row in enumerate(rows, 1):
        value = dict(subject="P01", round="1", step=1, label="upright", face_x=640, face_y=300,
                     rsh_x=500, rsh_y=450, lsh_x=780, lsh_y=450, oval_area_px=100,
                     face_area_px=200, face_w_px=100, z_face_m=.75, z_sh_m=.8,
                     frame_schema_version=analysis.FRAME_SCHEMA_VERSION, recording_id=rid,
                     analysis_run_id=run, frame_index=index, face_depth_source="bbox_roi",
                     shoulder_depth_source="both")
        value.update(row)
        canonical.append(value)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=analysis.FRAME_FIELDS)
        writer.writeheader()
        writer.writerows(canonical)
    owner = directory / "analysis_manifest.json"
    manifest = dict(recording_id=rid, analysis_run_id=run, status="completed", analysis_mode="extract_raw",
                    dataset_role="pilot", protocol_version="synthetic-protocol", models=[],
                    outputs=[dict(kind="frames", filename=path.name, **rf.file_identity(path))])
    owner.write_text(json.dumps(manifest), encoding="utf-8")
    if flat:
        compatibility = root / path.name
        shutil.copyfile(path, compatibility)
        link = dict(recording_id=rid, analysis_run_id=run,
                    frames_sha256=rf.file_identity(path)["sha256"],
                    analysis_manifest=owner.relative_to(root).as_posix(),
                    analysis_manifest_sha256=rf.file_identity(owner)["sha256"])
        Path(str(compatibility) + ".provenance.json").write_text(json.dumps(link), encoding="utf-8")
    return path


@contextmanager
def mocked_model_inputs(module, directory, paper, ours, multi=None):
    """Keep controlled numeric arrays; supply explicit synthetic provenance fixtures."""
    with ExitStack() as stack:
        root = Path(directory)
        stack.enter_context(patch.object(module, "RESULTS_DIR", str(root / "results")))
        paper_path = root / "synthetic.xlsx"
        paper_path.write_bytes(b"synthetic mocked paper table")
        argv = [*sys.argv, "--paper", str(paper_path)]
        if multi is not None:
            multi_path = root / "synthetic.csv"
            multi_path.write_bytes(b"synthetic mocked MultiPosture table")
            argv += ["--multiposture", str(multi_path)]
        stack.enter_context(patch.object(sys, "argv", argv))
        groups = {}
        for sub, rnd, step, label in ours[2]:
            groups.setdefault((sub, rnd), []).append(dict(subject=sub, round=rnd, step=step, label=label))
        for (sub, rnd), rows in groups.items():
            make_frames(root, f"{sub}_r{rnd}_synthetic", rows=rows)

        def external_loader(values):
            def load(*args, lineage, artifact, **kwargs):
                lineage.extend(module.external_source(artifact, i + 2, str(sub), int(label))
                               for i, (sub, label) in enumerate(zip(values[2], values[1])))
                return values
            return load

        def ours_loader(*args, inputs, lineage, **kwargs):
            for sub, rnd, step, label in ours[2]:
                entry = next(e for e in inputs if (e["subject"], e["round"]) == (sub, rnd))
                upright = [m[2] for m in ours[2] if m[:2] == (sub, rnd) and m[3] == "upright"]
                lineage.append(dict(source_kind="canonical_frames", subject=sub, round=rnd, step=step,
                                    label=label, calibration_reference_step=min(upright) if upright else None,
                                    **{k: entry[k] for k in ("recording_id", "analysis_run_id",
                                                             "frames_path", "frames_sha256")}))
            return ours

        stack.enter_context(patch.object(module, "load_paper", side_effect=external_loader(paper)))
        stack.enter_context(patch.object(module, "load_ours", side_effect=ours_loader))
        if multi is not None:
            stack.enter_context(patch.object(module, "load_multiposture", side_effect=external_loader(multi)))
        yield
