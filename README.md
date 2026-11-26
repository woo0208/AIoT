# AIoT RGB-D research code snapshot

This snapshot contains D455 capture, native RGB/Depth timestamp pairing and recovery,
offline replay, and the Research A and B analysis code. It uses independent Git history
and contains public source, configuration examples, and synthetic regression fixtures.

## Environment

The verification environment was 64-bit Windows with CPython 3.12.10. Use a fresh
virtual environment and install the matching Python dependencies.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -X utf8 -B -m pytest -q -p no:cacheprovider
```

The requirements use the OpenCV distribution declared by MediaPipe. Keep a
single OpenCV provider in the environment for the camera and model version checks.
Tkinter comes with the standard Windows Python installer. PyVista is used by the
optional 3D viewer. The D455 and the RealSense runtime are required for live capture;
the regression tests generate temporary synthetic frames, inputs and model fixtures.
For MediaPipe Tasks inference, obtain the public artifacts listed in
[mediapipe_model_lock.json](mediapipe_model_lock.json), verify their SHA-256 hashes
and place them in the ignored models/ directory. Use only trusted model artifacts.

On Windows, the full regression suite also reproduces existing failures in Patch 7 sidecar path validation and a legacy exploratory probe test fixture. The targeted capture, replay, and Research A/B evaluation tests run on synthetic inputs.

## Research B capture and offline replay

Check the launcher and preview options without opening a camera or GUI:

```powershell
python -X utf8 -B run_research_b.py --check-only --exchange-capture --capture-only --rgb-preview --participant-unregistered
```

For an independently authorized D455 engineering run, use the same flags with
--live in place of --check-only. The capture-only mode records native RGB-D and
operator events without live inference. RGB Preview is optional and displays the
latest RGB frame. The output defaults to a new directory below
analysis/RESEARCH_B/local_private/. An optional capture setup can be supplied
with --capture-environment using the example in config/.

For offline inference, supply an authorized local clip, session, BAG or DB3
recording and a trusted FS3 SVM binding with --binding. The binding example lists
the required keys. Replace its placeholders with values for the approved local
artifact, including the archive and separately computed model/scaler SHA-256
hashes. Keep the real binding and artifacts in ignored directories. The artifact
path in the binding is relative to the checkout.

```powershell
python -X utf8 -B run_research_b.py --replay ./private/example-session --binding ./private/fs3-binding.json --replay-method Fixed --fixed-n 2
python -X utf8 -B research_b_final_validation.py --help
python -X utf8 -B research_b_final_validation.py inspect --help
python -X utf8 -B research_b_final_validation.py run --help
```

The simple replay command above uses the Fixed interval policy. The four-policy
validation runner implements E0, Fixed_2_matched, Uniform_85 and V2_85, using
research_b_fair_replay.py and research_b_robustness_replay.py. Its run mode
requires an approved local protocol bound to the exact implementation,
the authorized intake and source, a trusted model, a hardware description and,
where required, an authorized roster. A session verified as RECOVERED_WITH_GAPS
requires the explicit --allow-incomplete option for diagnostic replay. The
standalone external NPZ adapter additionally requires the research authority's
local authorization module, catalog and registered grant for the protected
another_team input directory. Keep those files and all generated logs local.

## Research A analysis

Use these entry points with authorized local inputs. The evaluation code keeps
the existing feature computation, model definitions and selection rules.

```powershell
python -X utf8 -B analyze_d455.py f1 --help
python -X utf8 -B h6_offline.py --help
python -X utf8 -B rf_experiment.py --help
```

analyze_d455.py supports analysis of native recordings or canonical frame CSVs.
h6_offline.py accepts canonical frames, guided probe metadata or labeled probe
CSVs and writes its report to stdout. Redirect that report into an ignored
directory as it may include participant-level evidence. rf_experiment.py accepts
an authorized dataset spreadsheet, canonical frame files or a selection
manifest. The six-class evaluation code also includes its model factory and metric functions.
Use newly approved bindings for this snapshot because its implementation hashes
are independent of historical approvals. The standard exploratory six-posture
capture controller and H9 M0
inference code are included. The historical targeted pilot supplement,
participant-to-input binding for the original H9 training run, and exploratory
runners tied to restricted study bundles remain in the original workspace.

## Local input layout

Keep recordings, datasets, model artifacts, grants, participant mappings, and
experiment results outside Git. Review the ignore rules before creating additional
local folders. CLEAN_OWN_TEAM_EXPERIMENT/src contains independently usable helper
modules only. Study-specific configs, fitted models and generated results for
that package must be supplied separately by the research team. The capture and
test commands here do not authorize formal participant collection or Patch 8
execution.
