"""Single-person non-formal E0 connection check. Default: no camera or GUI.

Explicit --live uses the existing verified fold0 artifact for a short check,
not deployment selection, formal collection, training or accuracy evaluation.
"""
import argparse
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import shutil
import uuid

from e0_model import load_fs3,environment_record
from e0_panel import run_bound_probe
from posture_geometry_probe import run_probe, e0_ui_backend


ROOT=Path(__file__).resolve().parent
BINDING=ROOT/'analysis/E0_P3_INTEGRATION_20261109_CHECKED/local_private/model_fold0.json'


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    action=parser.add_mutually_exclusive_group()
    action.add_argument('--live',action='store_true',help='explicitly start the engineering camera/UI check')
    action.add_argument('--check-only',action='store_true',help='verify only; no camera/GUI (default)')
    parser.add_argument('--binding',type=Path,default=BINDING)
    parser.add_argument('--duration-seconds',type=float)
    parser.add_argument('--guided-six',action='store_true',help='six posture blocks, five manual 10s holds each')
    parser.add_argument('--subject',choices=('P01','P02'),help='guided window label only; never exported')
    parser.add_argument('--mode',choices=('summary','detailed'),default='summary')
    parser.add_argument('--pc-id',default='PC01')
    parser.add_argument('--variant',choices=('E0','E1'),default='E0')
    parser.add_argument('--output-dir',type=Path)
    args=parser.parse_args(argv)
    if args.guided_six != (args.subject is not None):
        parser.error('--guided-six and --subject must be used together')
    if args.duration_seconds is None:
        args.duration_seconds=1800. if args.guided_six else 90.
    if not math.isfinite(args.duration_seconds) or args.duration_seconds<=0:
        parser.error('duration must be finite and positive')
    if args.guided_six and args.duration_seconds<=300:
        parser.error('guided run needs more than 300s to allow preparation/transitions')
    binding=json.loads(args.binding.read_text(encoding='utf-8'))
    path=(ROOT/binding['path']).resolve()
    if not path.is_relative_to(ROOT):raise ValueError('Artifact must be inside the workspace')
    _,_,verified=load_fs3(path,binding['artifact_sha256'],binding['feature_ids'],
        expected_model_sha256=binding['model_sha256'],expected_scaler_sha256=binding['scaler_sha256'])
    environment_record(args.pc_id)  # validate anonymous PC id before opening any UI.
    if args.variant == 'E1':
        import cv2
        e0_ui_backend(cv2, 'E1')  # support check only, no camera/window
    base=ROOT/('analysis/E1_GUIDED/local_private' if args.guided_six and args.variant=='E1' else
               'analysis/E0_GUIDED/local_private' if args.guided_six else
               'analysis/E1_PREFLIGHT/local_private' if args.variant=='E1' else 'analysis/E0_PREFLIGHT/local_private')
    target=args.output_dir or (base/
        ('check_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'_'+uuid.uuid4().hex[:8]))
    target=target.resolve()
    if not target.is_relative_to(ROOT):raise ValueError('Output must be inside the workspace')
    if target.exists():raise FileExistsError(target)
    if shutil.disk_usage(ROOT).free<2**30:raise RuntimeError('At least 1 GiB free disk required')
    print(f"MODEL_READY: SVM-FS3-V0-T0; training_samples={verified['training_samples']}; preflight artifact only")
    print(f"artifact_sha256={verified['artifact_sha256']}")
    print(f"output={target.relative_to(ROOT)}")
    print(f"execution_variant={args.variant}; timing_contract=e0-e1-loop-timing/1")
    if not args.live:
        print('CHECK_ONLY_PASS: camera/GUI NOT_STARTED; no output directory created')
        return 0
    # reserve() exclusively creates the run directory; only its parents belong here.
    target.parent.mkdir(parents=True,exist_ok=True)
    print((f'NON_FORMAL_ENGINEERING_{args.variant}_GUIDED' if args.guided_six else 'NON_FORMAL_ENGINEERING_PREFLIGHT')+
          '; not formal/Patch8 execution authorization')
    print('Use E0 control panel: Enter/Start -> stable 10s; T/Cancel -> cancel; Q/Close -> finish')
    panel_options={}
    if args.guided_six:
        from e0_guided_panel import GuidedPanel
        panel_options['panel_factory']=lambda session:GuidedPanel(session,subject=args.subject)
        print('GUIDED: P0 x5 -> P1 x5 -> P2 x5 -> P3 x5 -> P4 x5 -> P5 x5; 10s each')
    def runner(**kwargs):
        session=kwargs['e0_session']
        session.environment_metadata.update(operation=f'NON_FORMAL_{args.variant}_GUIDED' if args.guided_six else 'NON_FORMAL_PREFLIGHT',
            requested_stream_seconds=args.duration_seconds,
            launcher_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
        if args.guided_six:
            session.environment_metadata['guided_source_sha256']=hashlib.sha256(
                ROOT.joinpath('e0_guided_panel.py').read_bytes()).hexdigest()
        return run_probe(duration_seconds=args.duration_seconds,e0_ui_variant=args.variant,**kwargs)
    run_bound_probe(path,binding,target,execution_authorized=True,pc_id=args.pc_id,mode=args.mode,
                    probe_runner=runner,**panel_options)
    print(f'PREFLIGHT_FINISHED: {target.relative_to(ROOT)}')
    return 0


if __name__=='__main__':raise SystemExit(main())
