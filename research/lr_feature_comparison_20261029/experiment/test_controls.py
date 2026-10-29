"""Minimal alignment/missingness/scaling controls; synthetic tests only."""
from dataclasses import dataclass, replace
import unittest
import numpy as np
from sklearn.preprocessing import StandardScaler
import evaluate as experiment


@dataclass
class Sample:
    sample_key: tuple
    subject: str
    label: str
    input_frame_indices: tuple
    eligible: bool
    values: tuple

    def ordered_values(self,*args):
        return self.values


class Controls(unittest.TestCase):
    def setUp(self):
        self.a=Sample(('run','recording','segment'),'synthetic','upright',(1,2,3),True,tuple(range(9)))

    def test_missing_c3_cannot_drop_or_impute_original_segment(self):
        with self.assertRaisesRegex(ValueError,'eligibility'):
            experiment.aligned_candidate([self.a],[replace(self.a,eligible=False)])
        with self.assertRaisesRegex(ValueError,'sample-key'):
            experiment.aligned_candidate([self.a],[])

    def test_conflicting_labels_and_duplicate_keys_fail_closed(self):
        with self.assertRaisesRegex(ValueError,'identity'):
            experiment.aligned_candidate([self.a],[replace(self.a,label='forward_head')])
        with self.assertRaisesRegex(ValueError,'duplicate'):
            experiment.aligned_candidate([self.a],[self.a,self.a])

    def test_drop_f9_is_column_only_and_candidate_is_native(self):
        c=replace(self.a,values=tuple(range(8))+(100,))
        matrices,_=experiment.matrices([self.a],[c])
        np.testing.assert_array_equal(matrices['B'],matrices['A'][:,:8])
        self.assertEqual(matrices['C'][0,-1],100)
        np.testing.assert_array_equal(matrices['C'][:,:8],matrices['B'])

    def test_held_out_transform_cannot_fit_training_scaler(self):
        train=np.arange(96,dtype=float).reshape(12,8)
        scaler=StandardScaler().fit(train);expected=scaler.mean_.copy()
        scaler.transform(np.full((12,8),1e9))
        np.testing.assert_array_equal(scaler.mean_,expected)
        self.assertEqual(scaler.n_samples_seen_,12)


if __name__=='__main__':unittest.main()
