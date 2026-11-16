"""Synthetic routing/fit-boundary tests only; no participant data or SVM fits."""
import unittest
import numpy as np
from compare_svm_c1_two_stage import train_stages, route, route_errors


class Predictor:
    def __init__(self, predictions):
        self.predictions = predictions
        self.calls = []

    def predict(self, x):
        self.calls.append(np.array(x, copy=True))
        if self.predictions is None:
            raise AssertionError("Specialist must not receive normal-routed inputs")
        return np.array(self.predictions)


class TwoStageCase(unittest.TestCase):
    def test_normal_route_does_not_call_specialist(self):
        gate, specialist = Predictor([0,0]), Predictor(None)
        final,g,indices = route(gate,specialist,np.zeros((2,7)))
        self.assertEqual(final.tolist(),[0,0])
        self.assertEqual(g.tolist(),[0,0])
        self.assertEqual(indices.tolist(),[])
        self.assertEqual(specialist.calls,[])

    def test_gate_routes_original_positions_without_test_targets(self):
        x=np.arange(28).reshape(4,7)
        original=x.copy()
        gate,specialist=Predictor([1,0,1,0]),Predictor([5,2])
        final,g,indices=route(gate,specialist,x)
        self.assertEqual(final.tolist(),[5,0,2,0])
        self.assertEqual(indices.tolist(),[0,2])
        np.testing.assert_array_equal(specialist.calls[0],x[[0,2]])
        np.testing.assert_array_equal(x,original)

    def test_training_uses_all_binary_and_only_abnormal_multiclass(self):
        fitted=[]
        class FitSpy:
            def fit(self,x,y):
                fitted.append((x.copy(),y.copy()))
                return self
        x=np.arange(84).reshape(12,7)
        y=np.tile(np.arange(6),2)
        old_x,old_y=x.copy(),y.copy()
        train_stages(x,y,FitSpy)
        self.assertEqual(len(fitted),2)
        np.testing.assert_array_equal(fitted[0][0],x)
        np.testing.assert_array_equal(fitted[0][1],y!=0)
        np.testing.assert_array_equal(fitted[1][0],x[y!=0])
        np.testing.assert_array_equal(fitted[1][1],y[y!=0])
        np.testing.assert_array_equal(x,old_x)
        np.testing.assert_array_equal(y,old_y)

    def test_routing_error_categories_cover_final_errors(self):
        y=np.array([0,1,2,3,4,5])
        final=np.array([2,0,3,3,4,5])
        gates=np.array([1,0,1,1,1,1])
        errors=route_errors(y,final,gates)
        self.assertEqual(list(errors.values()),[1,1,1])
        self.assertEqual(sum(errors.values()),int((y!=final).sum()))

    def test_invalid_routes_cannot_invent_final_labels(self):
        with self.assertRaises(ValueError):
            route(Predictor([2]),Predictor(None),np.zeros((1,7)))
        with self.assertRaises(ValueError):
            route(Predictor([1]),Predictor([0]),np.zeros((1,7)))


if __name__ == "__main__":
    unittest.main()
