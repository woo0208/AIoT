"""Research B launcher. Default check-only; optional lossless raw recording controls."""
import argparse
import hashlib
import json
import math
from pathlib import Path
from functools import partial
import shutil
import uuid

from e0_model import load_fs3, environment_record
from e0_panel import run_bound_probe
from posture_geometry_probe import run_probe
from research_b import DemandPolicy
from run_e0_check import ROOT, BINDING
from raw_rgbd_events import add_context_arguments,validate_context


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group()
    action.add_argument('--live', action='store_true')
    action.add_argument('--check-only', action='store_true')
    action.add_argument('--replay', type=Path, help='file-only E0: DB3/BAG or NPZ session/clip')
    parser.add_argument('--pacing', choices=('throughput','realtime15'), default='throughput')
    parser.add_argument('--replay-method', choices=('E0','Fixed','Adaptive'), default='E0')
    parser.add_argument('--fixed-n', type=int, choices=(1,2,3,5), default=1)
    parser.add_argument('--expected-sha256')
    parser.add_argument('--allow-incomplete', action='store_true')
    parser.add_argument('--replay-arm-at-first-frame', action='store_true',
                        help='unlabelled engineering hold; preserves original 10s boundary')
    parser.add_argument('--variant', choices=('E0', 'B1'), default='E0')
    parser.add_argument('--binding', type=Path, default=BINDING)
    parser.add_argument('--duration-seconds', type=float, default=300.)
    parser.add_argument('--mode', choices=('summary', 'detailed'), default='summary')
    parser.add_argument('--save-raw', choices=('on', 'off'), default=None,
                        help='initial raw save state; toggle with the on-screen button')
    parser.add_argument('--pc-id', default='PC01')
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--exchange-capture', action='store_true',
                        help='Require native RGB-D recording with independent acquisition and close-time verification')
    parser.add_argument('--exchange-fps', type=int, choices=(15, 30),
                        help='Exchange RGB and depth profile rate (default: 15)')
    parser.add_argument('--participant-unregistered', action='store_true',
                        help='unregistered technical capture or, with --guided-six, a guided engineering test')
    parser.add_argument('--guided-six', action='store_true', help='15 FPS exchange recording with one guided P0-P5 round')
    parser.add_argument('--capture-environment', type=Path, help='JSON installation and session metadata')
    parser.add_argument('--record-imu', action='store_true', help='Optional motion stream if available')
    add_context_arguments(parser)
    args = parser.parse_args(argv)
    exchange_options = None
    panel_options = {}
    guided_engineering = args.guided_six and args.participant_unregistered
    if args.guided_six:
        if not (args.live and args.exchange_capture) or args.exchange_fps not in (None, 15):
            parser.error('--guided-six requires --live --exchange-capture at 15 FPS')
        if guided_engineering:
            if any(value is not None for value in (args.participant_id, args.session_label, args.repetition)):
                parser.error('Guided engineering tests cannot use a participant ID, session label, or repetition')
            panel_options['engineering_test'] = True
        elif (args.participant_id not in ('P01', 'P02') or
              args.repetition not in {'S1': (1, 2, 3), 'S2': (4, 5)}.get(args.session_label, ())):
            parser.error('--guided-six requires P01 or P02 and S1 repeat 1-3 or S2 repeat 4-5')
        if args.save_raw == 'on':
            parser.error('--guided-six starts with raw recording OFF')
        from e0_guided_panel import GuidedPanel
        panel_options['panel_factory'] = partial(GuidedPanel, subject=args.participant_id, single_round=True)
    if args.exchange_capture:
        if args.replay or (args.save_raw == 'off' and not args.guided_six):
            parser.error('Exchange capture requires live input and raw recording ON')
        if bool(args.participant_id) == args.participant_unregistered:
            parser.error('Choose --participant-id or --participant-unregistered for exchange capture')
        from exchange_capture import read_environment
        exchange_options = dict(environment=read_environment(args.capture_environment),
                                record_imu=args.record_imu, duration=args.duration_seconds,
                                fps=args.exchange_fps or 15)
        if args.guided_six:
            exchange_options['guided'] = True
        args.save_raw = 'off' if args.guided_six else 'on'
    elif args.capture_environment or args.record_imu or args.participant_unregistered or args.exchange_fps:
        parser.error('Exchange options require --exchange-capture')
    args.save_raw = args.save_raw or 'off'
    context=validate_context(args.participant_id,args.session_label,args.repetition)
    if args.replay and (args.variant != 'E0' or args.save_raw != 'off'
                        or any(context[k] for k in ('participant_id','session_label','repetition'))):
        parser.error('Replay supports E0 only, no live recording/context controls')
    if not args.replay and (args.expected_sha256 or args.allow_incomplete or args.replay_arm_at_first_frame
                            or args.pacing != 'throughput' or args.replay_method!='E0' or args.fixed_n!=1):
        parser.error('Replay options require --replay')
    if args.replay_method!='Fixed' and args.fixed_n!=1:
        parser.error('--fixed-n requires --replay-method Fixed')
    if not math.isfinite(args.duration_seconds) or args.duration_seconds <= 0:
        parser.error('duration must be finite and positive')
    private = (ROOT / 'analysis/RESEARCH_B/local_private').resolve()
    engineering_root = private / 'guided_engineering'
    target = (args.output_dir or (engineering_root if guided_engineering else private) /
              (args.variant + '_' + uuid.uuid4().hex)).resolve()
    if not target.is_relative_to(ROOT):
        raise ValueError('Output must be inside workspace')
    if guided_engineering and (target == engineering_root or not target.is_relative_to(engineering_root)):
        parser.error('Guided engineering output must be a run directory under analysis/RESEARCH_B/local_private/guided_engineering')
    if not guided_engineering and target.is_relative_to(engineering_root):
        parser.error('The guided_engineering directory is reserved for unregistered guided engineering tests')
    if target.exists():
        raise FileExistsError(target)
    binding = json.loads(args.binding.read_text(encoding='utf-8'))
    artifact = (ROOT / binding['path']).resolve()
    if not artifact.is_relative_to(ROOT):
        raise ValueError('Artifact must be inside workspace')
    _, _, verified = load_fs3(artifact, binding['artifact_sha256'], binding['feature_ids'],
        expected_model_sha256=binding['model_sha256'], expected_scaler_sha256=binding['scaler_sha256'])
    environment_record(args.pc_id)
    if shutil.disk_usage(ROOT).free < 2**30:
        raise RuntimeError('At least 1 GiB free disk required')
    print(f"MODEL_READY: {verified['artifact_sha256']}; FS3-V0-T0; no refit")
    print(f'variant={args.variant}; output={target.relative_to(ROOT)}; performance=UNVERIFIED')
    print(f'raw_recording_initial={args.save_raw}; raw_format=lossless native RGB-D NPZ')
    if exchange_options:
        print(f"exchange_requested_fps={exchange_options['fps']}; hardware_qualification=NOT_TESTED")
    if args.replay:
        from e0_replay import run_replay
        result = run_replay(args.replay,binding,artifact,target,pacing=args.pacing,
            allow_incomplete=args.allow_incomplete,expected_sha256=args.expected_sha256,
            arm_at_first_frame=args.replay_arm_at_first_frame,pc_id=args.pc_id,
            method=args.replay_method,interval=args.fixed_n)
        print(json.dumps({k:result[k] for k in ('status','input_frames','processed_frames',
            'actual_calls','process_cpu_seconds','processed_fps','prediction_successes')},ensure_ascii=False))
        print(f'FINISHED_REPLAY: {target.relative_to(ROOT)}; offline only; live/HOLD unchanged')
        return 0 if result['status']=='COMPLETED' else 1
    if not args.live:
        print('CHECK_ONLY_PASS: camera/GUI NOT_STARTED; no output created')
        return 0
    target.parent.mkdir(parents=True, exist_ok=True)
    print('NON_FORMAL_ENGINEERING; formal evaluation/B6/Patch8 HOLD unchanged')
    if guided_engineering:
        print('GUIDED ENGINEERING TEST ONLY; participant, session label, and repetition are unassigned.')
    if args.guided_six:
        print('Guided P0-P5: start raw recording in the preview, then follow the six 10-second holds.')
    elif exchange_options:
        print('Raw recording starts automatically. Manual stable hold: Enter/Start; cancel: T; quit: Q.')
    else:
        print('Manual stable hold: Enter/Start; cancel: T; quit: Q. Raw save uses its separate ON/OFF button.')
    policy = DemandPolicy(args.variant)
    def runner(**kwargs):
        kwargs['e0_session'].environment_metadata.update(
            requested_stream_seconds=args.duration_seconds,
            launcher_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
        return run_probe(duration_seconds=args.duration_seconds, rgbd_policy=policy, **kwargs)
    run_bound_probe(artifact, binding, target, execution_authorized=True,
                    pc_id=args.pc_id, mode=args.mode, probe_runner=runner, save_raw=args.save_raw,
                    recording_context=context, **panel_options,
                    **(dict(exchange_options=exchange_options) if exchange_options else {}))
    print(f'FINISHED: {target.relative_to(ROOT)}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
