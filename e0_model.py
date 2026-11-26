"""Explicit trusted-local FS3 artifact binding. Never trains/selects a model."""
import hashlib
from importlib import metadata
import os
from pathlib import Path
import pickle
import platform
import re
import subprocess
import warnings
from sklearn.exceptions import InconsistentVersionWarning

from e0_fs3 import FEATURE_IDS, validate_model


class ModelNotReady(ValueError):
    pass


def component_sha256(value):
    """Fingerprint of protocol-5 component serialization; no model bytes exported."""
    return hashlib.sha256(pickle.dumps(value,protocol=5)).hexdigest()


def load_fs3(path, expected_sha256, feature_ids, *, expected_model_sha256=None, expected_scaler_sha256=None):
    if tuple(feature_ids)!=FEATURE_IDS or not re.fullmatch('[0-9a-f]{64}',expected_sha256 or ''):
        raise ModelNotReady('MODEL_NOT_READY: binding/order')
    try:
        raw=Path(path).read_bytes()
        artifact_sha=hashlib.sha256(raw).hexdigest()
        if artifact_sha!=expected_sha256:raise ValueError('hash mismatch')
        # Only explicitly bound, known local research artifacts are accepted.
        with warnings.catch_warnings():
            warnings.simplefilter('error',InconsistentVersionWarning)
            model,scaler=pickle.loads(raw)
        validate_model(model,scaler)
        if getattr(model,'fit_status_',0)!=0:raise ValueError('fit not converged')
        model_sha,scaler_sha=component_sha256(model),component_sha256(scaler)
        if expected_model_sha256 is not None and expected_model_sha256!=model_sha:raise ValueError('component mismatch')
        if expected_scaler_sha256 is not None and expected_scaler_sha256!=scaler_sha:raise ValueError('component mismatch')
        count=int(scaler.n_samples_seen_)
    except Exception as exc:
        raise ModelNotReady('MODEL_NOT_READY: '+type(exc).__name__) from None
    return model,scaler,dict(status='MODEL_READY',artifact_sha256=artifact_sha,
        model_sha256=model_sha,scaler_sha256=scaler_sha,component_hash_method='pickle-protocol-5',
        feature_ids=list(FEATURE_IDS),training_samples=count,
        settings='SVM-FS3-V0-T0; no refit',purpose='EXISTING_ARTIFACT; live selection not implied')


def environment_record(pc_id='PC_UNSPECIFIED'):
    if pc_id!='PC_UNSPECIFIED' and not re.fullmatch('PC[0-9]{2,3}',pc_id):
        raise ValueError('Use an anonymous PC id')
    packages={}
    for name in ('numpy','scikit-learn','mediapipe','pyrealsense2','opencv-python','opencv-contrib-python'):
        try:packages[name]=metadata.version(name)
        except metadata.PackageNotFoundError:packages[name]='NOT_MEASURED'
    try:
        commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True,stderr=subprocess.DEVNULL).strip()
    except Exception:commit='NOT_MEASURED'
    try:
        dirty=bool(subprocess.check_output(['git','status','--porcelain','--untracked-files=normal'],
            text=True,stderr=subprocess.DEVNULL))
    except Exception:dirty='NOT_MEASURED'
    try:
        if os.name=='nt':
            import ctypes
            installed=ctypes.c_ulonglong()
            query=ctypes.WinDLL('kernel32',use_last_error=True).GetPhysicallyInstalledSystemMemory
            query.argtypes=[ctypes.POINTER(ctypes.c_ulonglong)]
            query.restype=ctypes.c_int
            if not query(ctypes.byref(installed)):raise OSError('unavailable')
            ram=installed.value*1024
        else:
            ram=os.sysconf('SC_PAGE_SIZE')*os.sysconf('SC_PHYS_PAGES')
    except Exception:ram='NOT_MEASURED'
    files=('e0_fs3.py','e0_resources.py','e0_storage.py','probe_diagnostics.py',
           'e0_model.py','e0_panel.py','posture_geometry_probe.py','posture_geometry.py','f1_sample_aggregator.py')
    return dict(pc_id=pc_id,os=platform.system(),os_release=platform.release(),os_version=platform.version(),
        architecture=platform.machine(),cpu_model=platform.processor() or 'NOT_MEASURED',
        logical_cpus=os.cpu_count(),installed_ram_bytes=ram,python=platform.python_version(),packages=packages,
        git_commit=commit,git_dirty=dirty,
        source_sha256={name:hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() for name in files},
        gpu='resources.jsonl device-wide observations; backend attestation separate',
        ram='installed physical memory separately from resources.jsonl RSS/Private',
        identity_policy='No hostname/user/path/serial/UUID/UTC')
