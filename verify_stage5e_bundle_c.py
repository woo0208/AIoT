"""Bundle C read-only B analysis, synthetic evidence and bounded regression.

No camera is opened. No artifacts/ content is read. Requires a new output path
under an explicitly supplied start-state directory. Never overwrites evidence.
"""
import argparse
from contextlib import ExitStack, redirect_stdout, redirect_stderr
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

import engineering_exports as out
import performance_output as perf
import posture_geometry_probe as probe
import stage5e_bundle_c as bundle
import test_h9_probe_integration as integration
import verify_stage5e_bundle_a as bundle_a


def default_equivalence(source_path, root):
    """Original ed22f0f probe vs current probe, exact same virtual SDK stream.

    Models/geometry are explicit test fakes. Compare the entire legacy timing
    report; Performance identity hashes correctly differ when code differs.
    """
    spec=importlib.util.spec_from_file_location('bundle_c_original_probe',source_path)
    original=importlib.util.module_from_spec(spec); sys.modules[spec.name]=original; spec.loader.exec_module(original)
    records=[]
    for name,module,headless in (('original_default',original,False),('current_default',probe,False),('current_headless',probe,True)):
        directory=out.reserve(root/name)
        with ExitStack() as stack:
            stack.enter_context(patch.object(integration,'probe',module))
            fake=integration.SyntheticProbe(NS(enterContext=stack.enter_context),[0,100,200,300],keys=[-1]*4)
            model=root/'SYNTHETIC-PIN.bin'
            if not model.exists():
                with model.open('xb') as stream: stream.write(b'SYNTHETIC; fake SDK never loads this')
            sys.modules['analyze_d455'].ensure_models=lambda:dict(pose=model,mesh=model,face=model)
            stack.enter_context(redirect_stdout(io.StringIO())); stack.enter_context(redirect_stderr(io.StringIO()))
            args=dict(duration_seconds=.3,show_3d_views='none',performance_output_dir=str(directory/'performance'),
                      frame_callback=fake.callbacks.append)
            if headless: args['headless']=True
            module.run_probe(**args)
            document=json.loads((directory/'performance/performance.json').read_text(encoding='utf-8'))
            records.append(dict(name=name,timing=document['timing'],config=document['config'],
                pose_calls=fake.pose.detect_for_video.call_count,face_calls=fake.face.detect_for_video.call_count,
                geometry_calls=fake.calculate.call_count,callback_count=len(fake.callbacks),
                imshow_calls=fake.cv.imshow.call_count,waitKey_calls=fake.cv.waitKey.call_count,
                same_result_objects=all(f.result is fake.geometry for f in fake.callbacks),
                journal_sha256=perf.sha256(directory/'performance/events.jsonl')))
    checks=dict(original_vs_current_legacy_timing=records[0]['timing']==records[1]['timing'],
        original_vs_current_config=records[0]['config']==records[1]['config'],
        all_same_counts=all(r['timing']['counts']==records[0]['timing']['counts'] for r in records),
        all_same_processing_calls=all((r['pose_calls'],r['face_calls'],r['geometry_calls'],r['callback_count'])==(3,3,3,3) for r in records),
        headless_no_builtin_ui=records[2]['imshow_calls']==records[2]['waitKey_calls']==0,
        synthetic_result_identity=all(r['same_result_objects'] for r in records))
    return dict(scope='SYNTHETIC_VIRTUAL_SDK_NOT_REAL_CLASSIFICATION_EQUIVALENCE',checks=checks,runs=records)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('start_directory'); parser.add_argument('bundle_b'); parser.add_argument('new_directory')
    args=parser.parse_args(argv)
    start=Path(args.start_directory)
    root=out.reserve(args.new_directory,(args.bundle_b,))
    state=json.loads((start/'start_state.json').read_text(encoding='utf-8'))
    baseline=bundle.analyze_baselines(args.bundle_b)
    perf._write_json(root/'baseline.json',baseline)
    clock=bundle.clock_diagnostic(); perf._write_json(root/'clock.json',clock)
    render=bundle.render_microbenchmark(); perf._write_json(root/'render.json',render)
    equivalent=default_equivalence(start/'source_before/posture_geometry_probe.py',root)
    perf._write_json(root/'default_equivalence.json',equivalent)
    # A separately published QPC sidecar on the real probe control path with a
    # fully synthetic SDK. This demonstrates contracts/endpoints, not speed.
    with ExitStack() as stack:
        fake=integration.SyntheticProbe(NS(enterContext=stack.enter_context),[0,100,200,300],keys=[-1]*4)
        stack.enter_context(redirect_stdout(io.StringIO())); stack.enter_context(redirect_stderr(io.StringIO()))
        probe.run_probe(duration_seconds=.3,timing_output_path=str(root/'synthetic_host_timing.json'),
                        diagnostics_output_dir=str(root/'synthetic_qpc_diagnostics'))
    names=['test_stage5e_bundle_c',*bundle_a.MODULES,'test_f0_fcal_features']
    names += ['test_formal6_evaluation.FormalEvaluationTests.'+n for n in bundle_a.FORMAL_TESTS]
    suite=unittest.defaultTestLoader.loadTestsFromNames(names)
    with (root/'integrated_tests.log').open('x',encoding='utf-8') as stream:
        result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    preserved_b={p:Path(p).is_file() and perf.sha256(p)==digest for p,digest in state['bundle_b_sha256'].items()}
    changed={name:perf.sha256(name)!=digest for name,digest in state['source_sha256'].items()}
    check=subprocess.run(['git','diff','--check'],capture_output=True,text=True)
    head=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
    status=subprocess.run(['git','status','--short'],capture_output=True,text=True)
    for name,value in (('git_status.txt',status.stdout+status.stderr),('git_diff_check.txt',check.stdout+check.stderr)):
        with (root/name).open('x',encoding='utf-8') as stream: stream.write(value)
    summary=dict(scope='ENGINEERING_ONLY_NO_NEW_D455_ACQUISITION',tests_run=result.testsRun,
        failures=len(result.failures),errors=len(result.errors),skipped=len(result.skipped),
        passed=result.testsRun-len(result.failures)-len(result.errors)-len(result.skipped),
        success=result.wasSuccessful(),test_modules=names,start_head=state['head'],end_head=head,
        baseline_all_crosschecks=baseline['all_checks_passed'],bundle_b_preserved=all(preserved_b.values()),
        bundle_b_file_checks=preserved_b,changed_initial_sources=[n for n,v in changed.items() if v],
        preserved_initial_sources=[n for n,v in changed.items() if not v],
        default_equivalence=equivalent['checks'],git_diff_check_exit_code=check.returncode,
        strict_live_ab='BLOCKED_NO_IDENTICAL_INPUT',new_hardware_acquisition='NOT_RUN',
        research_data_access='NOT_RUN',model_training='NOT_RUN',artifacts_directory='NOT_ACCESSED',commit_push='NOT_RUN')
    perf._write_json(root/'verification.json',summary)
    print(json.dumps({k:summary[k] for k in ('tests_run','passed','failures','errors','skipped','success',
        'bundle_b_preserved','changed_initial_sources','default_equivalence','git_diff_check_exit_code')},indent=2))
    return 0 if (result.wasSuccessful() and all(equivalent['checks'].values()) and all(preserved_b.values()) and check.returncode==0) else 1


if __name__=='__main__': raise SystemExit(main())
