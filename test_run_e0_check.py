"""CLI wiring only; camera, UI and real telemetry execution are prohibited."""
from contextlib import redirect_stdout,redirect_stderr
import io
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

import run_e0_check as cli


class CheckCommandTests(unittest.TestCase):
    def setUp(self):
        self.output=cli.ROOT/'analysis/E0_COMMAND_STRUCTURAL_ONLY_DO_NOT_CREATE'
        self.binding=dict(path='models/SYNTHETIC_NOT_A_REAL_MODEL.pkl',artifact_sha256='a'*64,
            model_sha256='b'*64,scaler_sha256='c'*64,feature_ids=['F1','F3','F4','F5','F6','F7','F8'])
        self.enterContext(redirect_stdout(io.StringIO()));self.enterContext(redirect_stderr(io.StringIO()))
        self.enterContext(patch('run_e0_check.json.loads',return_value=self.binding))
        self.enterContext(patch.object(Path,'read_text',return_value='{}'))
        self.enterContext(patch('run_e0_check.environment_record',return_value={}))
        self.loader=self.enterContext(patch('run_e0_check.load_fs3',return_value=(None,None,
            dict(training_samples=60,artifact_sha256='a'*64))))
        self.run=self.enterContext(patch('run_e0_check.run_bound_probe'))
        self.camera=self.enterContext(patch('run_e0_check.run_probe',side_effect=AssertionError('no camera')))
        self.enterContext(patch('run_e0_check.shutil.disk_usage',return_value=type('Disk',(),{'free':2**32})()))

    def test_default_and_check_only_never_open_camera_or_create_output(self):
        for argv in ([],['--check-only']):
            self.assertEqual(cli.main(argv+['--output-dir',str(self.output)]),0)
        self.loader.assert_called();self.run.assert_not_called();self.camera.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_live_is_explicit_and_forwards_fixed_duration_and_verified_binding(self):
        self.assertEqual(cli.main(['--live','--duration-seconds','90','--output-dir',str(self.output)]),0)
        self.assertTrue(self.run.call_args.kwargs['execution_authorized'])
        self.assertEqual(self.run.call_args.kwargs['mode'],'summary')
        runner=self.run.call_args.kwargs['probe_runner']
        session=type('Session',(),{'environment_metadata':{}})()
        with patch('run_e0_check.run_probe',return_value=None) as fake:
            runner(e0_session=session)
        self.assertEqual(fake.call_args.kwargs['duration_seconds'],90)
        self.assertEqual(session.environment_metadata['operation'],'NON_FORMAL_PREFLIGHT')
        self.camera.assert_not_called()

    def test_invalid_duration_and_existing_output_refuse_launch(self):
        for value in ['0','-1','nan','inf']:
            with self.assertRaises(SystemExit):cli.main(['--live','--duration-seconds',value])
        with tempfile.TemporaryDirectory(dir=cli.ROOT/'analysis') as folder:
            with self.assertRaises(FileExistsError):cli.main(['--live','--output-dir',folder])
        self.run.assert_not_called();self.camera.assert_not_called()

    def test_model_failure_never_reaches_live_path(self):
        self.loader.side_effect=ValueError('MODEL_NOT_READY')
        with self.assertRaises(ValueError):cli.main(['--live'])
        self.run.assert_not_called();self.camera.assert_not_called()

    def test_first_live_run_creates_missing_parents_but_reserves_run_exclusively(self):
        from engineering_exports import reserve
        with tempfile.TemporaryDirectory(dir=cli.ROOT/'analysis') as folder:
            target=Path(folder)/'new_preflight'/'local_private'/'new_run'
            self.assertEqual(cli.main(['--check-only','--output-dir',str(target)]),0)
            self.assertFalse(target.parent.exists())
            def initialize(path,binding,directory,**kwargs):
                self.assertTrue(directory.parent.is_dir())
                self.assertFalse(directory.exists())
                reserve(directory)  # Real initialization boundary; no camera or GUI.
            self.run.side_effect=initialize
            self.assertEqual(cli.main(['--live','--output-dir',str(target)]),0)
            self.assertTrue(target.is_dir())
            with self.assertRaises(FileExistsError):cli.main(['--live','--output-dir',str(target)])
        self.camera.assert_not_called()

    def test_guided_check_only_is_no_camera_and_requires_subject_and_transition_time(self):
        for subject in ('P01','P02'):
            self.assertEqual(cli.main(['--check-only','--guided-six','--subject',subject]),0)
        self.run.assert_not_called();self.camera.assert_not_called()
        for argv in (['--guided-six'],['--subject','P01'],
                     ['--guided-six','--subject','P01','--duration-seconds','300']):
            with self.assertRaises(SystemExit):cli.main(argv)

    def test_guided_live_forwards_panel_and_anonymous_plan_without_opening_ui(self):
        session=type('Session',(),{'environment_metadata':{}})()
        with patch('e0_guided_panel.GuidedPanel') as panel:
            self.assertEqual(cli.main(['--live','--guided-six','--subject','P01',
                                      '--output-dir',str(self.output)]),0)
            options=self.run.call_args.kwargs
            options['panel_factory'](session)
        self.assertEqual(panel.call_args.kwargs['subject'],'P01')
        with patch('run_e0_check.run_probe') as fake:
            options['probe_runner'](e0_session=session)
        self.assertEqual(fake.call_args.kwargs['duration_seconds'],1800.)
        self.assertEqual(session.environment_metadata['operation'],'NON_FORMAL_E0_GUIDED')
        self.assertNotIn('P01',str(session.environment_metadata))
        self.camera.assert_not_called()

    def test_e1_explicit_variant_support_and_forwarding_without_camera(self):
        with patch('run_e0_check.e0_ui_backend',return_value='WIN32') as check:
            self.assertEqual(cli.main(['--check-only','--variant','E1','--output-dir',str(self.output)]),0)
            self.run.assert_not_called()
            self.assertEqual(cli.main(['--live','--variant','E1','--output-dir',str(self.output)]),0)
        self.assertEqual(check.call_count,2)
        session=type('Session',(),{'environment_metadata':{}})()
        with patch('run_e0_check.run_probe') as fake:
            self.run.call_args.kwargs['probe_runner'](e0_session=session)
        self.assertEqual(fake.call_args.kwargs['e0_ui_variant'],'E1')
        self.camera.assert_not_called()

    def test_e1_unsupported_backend_never_reaches_live_launch(self):
        with patch('run_e0_check.e0_ui_backend',side_effect=RuntimeError('unsupported')):
            with self.assertRaises(RuntimeError):cli.main(['--live','--variant','E1'])
        self.run.assert_not_called();self.camera.assert_not_called()


if __name__=='__main__':unittest.main()
