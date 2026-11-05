"""Exclusive engineering exports shared by the Stage 5-E adapters."""
import csv
import hashlib
from pathlib import Path

import performance_output as perf


SYNTHETIC = 'SYNTHETIC_STRUCTURAL_TEST_ONLY'


def validate_scope(identity):
    if identity['scope'] not in (SYNTHETIC, 'NON_FORMAL_ENGINEERING'):
        raise ValueError('engineering/synthetic scope required; no formal result publication')
    marked = 'SYNTHETIC' in str(identity.get('data_id', '')) or 'SYNTHETIC' in str(identity.get('model_id', ''))
    if marked != (identity['scope'] == SYNTHETIC):
        raise ValueError('synthetic identity/scope mismatch')


def digest(value):
    return hashlib.sha256(perf.canonical(value).encode('utf-8')).hexdigest()


def reserve(directory, inputs=()):
    root = Path(directory).resolve()
    if Path(directory).exists() or Path(directory).is_symlink():
        raise FileExistsError(directory)
    for source in inputs:
        path = Path(source).resolve()
        if path == root or root in path.parents or path in root.parents:
            raise ValueError('output overlaps input')
    root.mkdir()  # exclusive, parent must already exist
    return root


def csv_write(path, fields, rows):
    with Path(path).open('x', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)


def common(identity, evidence):
    """Keep the 5-E-4 common columns and their meanings, including null cells."""
    return dict(run_id=identity['run_id'], data_id=identity['data_id'],
                model_id=identity['model_id'], config_id=identity['config_id'],
                config_sha256=identity['config_sha256'], git_commit=identity['git']['commit'],
                git_dirty=identity['git']['dirty'], environment_json=perf.canonical(identity['environment']),
                run_status=identity['run_status'], evidence=evidence)
