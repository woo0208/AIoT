"""Research B1: demand-gated idle RGB-D work, never cached measurements.

Engineering scope only. During armed/active holds the original E0 path runs
on every received pair, including the end-boundary observation. E0 is unchanged
when the optional policy is absent; variant E0 is an observe-only control.
"""
from collections import Counter
import hashlib
from pathlib import Path


class DemandPolicy:
    def __init__(self, variant):
        if variant not in ('E0', 'B1'):
            raise ValueError('Expected E0 or B1')
        self.variant = variant
        self.state = None
        self.counts = Counter()
        self.transitions = Counter()
        self.gaps = {name: dict(valid=True, received=0, gaps=0, advances=0)
                     for name in ('rgb', 'depth')}

    def select(self, session, row):
        demand = bool(session.armed or session.active is not None)
        state = 'FULL' if self.variant == 'E0' or demand else 'IDLE'
        if state != self.state:
            self.transitions[f'{self.state or "INITIAL"}->{state}'] += 1
            self.state = state
        self.counts['selected'] += 1
        self.counts['demand_inputs' if demand else 'idle_inputs'] += 1
        self.counts['full_attempts' if state == 'FULL' else 'idle_skips'] += 1
        row.update(research_b_state=state, research_b_demand=demand,
                   measurement_available=False)
        # Read existing pre-align metadata only. Never treat deliberate idle
        # omission as SDK loss. Any uncertain edge invalidates the gap fraction.
        for name, stats in self.gaps.items():
            current = row.get('raw', {}).get(name, {})
            edge = row.get('raw_relations', {}).get(name, {})
            if current.get('status') != 'MEASURED':
                stats['valid'] = False
            if stats['received']:
                if edge.get('classification') not in ('ADVANCED', 'ADVANCED_WITH_NUMBER_GAP'):
                    stats['valid'] = False
                else:
                    stats['gaps'] += edge['source_gap']
                    stats['advances'] += 1
            stats['received'] += 1
        return state == 'FULL'

    def completed(self, session, row, *, skipped):
        kind = 'idle' if skipped else 'full'
        self.counts[kind + '_completed'] += 1
        row['measurement_available'] = not skipped and bool(row.get('h9_common_success'))
        elapsed = row['processing_end_ns'] - row['receive_end_ns']
        session.timing.record_ns('research_b.' + kind + '.receive_to_complete',
                                 elapsed, row['frame_id'])
        if not skipped:
            phase = 'demand' if row['research_b_demand'] else 'idle'
            session.timing.record_ns('research_b.full.' + phase + '.receive_to_complete',
                                     elapsed, row['frame_id'])

    def summary(self):
        gaps = {}
        for name, stats in self.gaps.items():
            denominator = stats['advances'] + stats['gaps']
            valid = stats['valid'] and denominator > 0
            gaps[name] = dict(**stats, status='MEASURED' if valid else 'NOT_MEASURED',
                observed_number_gap_fraction=stats['gaps']/denominator if valid else None,
                denominator='sum of positive same-stream frame-number increments',
                sensor_missing_rate='NOT_MEASURED')
        return dict(variant=self.variant, policy='manual-hold-demand/1',
            scope='NON_FORMAL_ENGINEERING', counts=dict(self.counts),
            transitions=dict(self.transitions), raw_frame_number_gaps=gaps,
            accuracy='NOT_MEASURED', macro_f1='NOT_MEASURED',
            p0_recall='NOT_MEASURED', p1_recall='NOT_MEASURED',
            performance_improvement='UNVERIFIED',
            source_sha256={name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                           for name in ('research_b.py', 'run_research_b.py', 'research_b_report.py')},
            limitations=['No active-hold inference decimation or cached features',
                'VIDEO tracking history after idle differs; reacquisition accuracy unverified',
                'Idle preview has no geometry or current prediction',
                'Gap fraction is a host-observed diagnostic, not formal sensor loss'])
