import copy
import csv
import hashlib
import json
from pathlib import Path
import unittest
from verify_public import verify

ROOT=Path(__file__).resolve().parent


class AggregateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.d=json.loads((ROOT/'aggregate_results.json').read_text(encoding='utf-8'))

    def test_45_saved_cases(self):self.assertEqual(verify(self.d)['saved_metric_cases'],45)

    def test_mismatched_metric_is_rejected(self):
        d=copy.deepcopy(self.d);d['results']['C']['scopes']['pooled']['mean']['macro_f1']=1.
        with self.assertRaises(ValueError):verify(d)

    def test_private_predictions_are_rejected(self):
        d=copy.deepcopy(self.d);d['results']['A']['predictions_by_seed']=[]
        with self.assertRaises(ValueError):verify(d)

    def test_csv_matches_saved_evidence(self):
        with (ROOT/'performance.csv').open(encoding='utf-8-sig',newline='') as f:rows=list(csv.DictReader(f))
        self.assertEqual(len(rows),9)
        for r in rows:
            s=self.d['results'][r['condition']]['scopes'][r['scope']]
            self.assertAlmostEqual(float(r['accuracy_percent']),100*s['mean']['accuracy'])
            self.assertAlmostEqual(float(r['macro_f1_percent']),100*s['mean']['macro_f1'])

    def test_archive_byte_identities(self):
        for name,expected in self.d['provenance']['archived_code_sha256'].items():
            self.assertEqual(hashlib.sha256((ROOT/'experiment'/name).read_bytes()).hexdigest(),expected)


if __name__=='__main__':unittest.main()
