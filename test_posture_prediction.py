"""Structural Prediction V0 tests; synthetic outputs are not research results."""

import math
import unittest

import posture_prediction as prediction
import rf_experiment as rf


CONTRACT = prediction.FeatureContract(
    "test-only-synthetic/1.0.0",
    ("synthetic_a", "synthetic_b"),
    ("m", "deg"),
)
TEST_BINARY_MAPPING = {
    "upright": prediction.PredictionClass.NORMAL,
    "forward_head": prediction.PredictionClass.POOR,
    "lean_back": prediction.PredictionClass.POOR,
    "lean_left": prediction.PredictionClass.POOR,
    "lean_right": prediction.PredictionClass.POOR,
}


class SyntheticPredictor:
    """Test-only model adapter; never imported by a production module."""

    feature_contract = CONTRACT

    def __init__(self, output="upright", error=None):
        self.output = output
        self.error = error
        self.calls = 0

    def predict_label(self, features):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.output


class SyntheticLoader:
    def __init__(self, model=None, error=None):
        self.model = model
        self.error = error
        self.calls = 0

    def load(self):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.model


def vector(contract=CONTRACT, values=(1.0, 2.0)):
    return prediction.FeatureVector.from_contract(contract, values)


class LabelAndResultTests(unittest.TestCase):
    def test_lab5_order_matches_existing_classifier(self):
        self.assertEqual(
            prediction.LAB5_LABELS,
            (
                "upright",
                "forward_head",
                "lean_back",
                "lean_left",
                "lean_right",
            ),
        )
        self.assertEqual(prediction.LAB5_LABELS, tuple(rf.LAB5))
        self.assertNotIn("body_forward", prediction.LAB5_LABELS)

    def test_classified_result_requires_an_explicit_binary_class(self):
        with self.assertRaises(TypeError):
            prediction.PredictionResult.classified("upright")

        normal = prediction.PredictionResult.classified(
            "upright", prediction.PredictionClass.NORMAL
        )
        self.assertEqual(
            (normal.prediction, normal.label),
            (prediction.PredictionClass.NORMAL, "upright"),
        )
        poor = prediction.PredictionResult.classified(
            "forward_head", prediction.PredictionClass.POOR
        )
        self.assertEqual(
            (poor.prediction, poor.label),
            (prediction.PredictionClass.POOR, "forward_head"),
        )

    def test_result_invariants_reject_inconsistent_states(self):
        invalid = (
            (
                prediction.PredictionClass.UNKNOWN,
                prediction.PredictionReason.MODEL_PREDICTION,
                "lean_back",
            ),
            (
                prediction.PredictionClass.NORMAL,
                prediction.PredictionReason.MODEL_ABSTAINED,
                "forward_head",
            ),
            (
                prediction.PredictionClass.UNKNOWN,
                prediction.PredictionReason.MODEL_ABSTAINED,
                "upright",
            ),
            (
                prediction.PredictionClass.UNAVAILABLE,
                prediction.PredictionReason.MODEL_LOAD_FAILED,
                "upright",
            ),
            (
                prediction.PredictionClass.UNKNOWN,
                prediction.PredictionReason.MODEL_LOAD_FAILED,
                None,
            ),
        )
        for args in invalid:
            with self.subTest(args=args), self.assertRaises(ValueError):
                prediction.PredictionResult(*args)

    def test_unknown_label_cannot_be_constructed_as_a_classification(self):
        with self.assertRaises(ValueError):
            prediction.PredictionResult.classified(
                "body_forward", prediction.PredictionClass.POOR
            )


class FeatureContractTests(unittest.TestCase):
    def test_contract_requires_ordered_unique_names_and_units(self):
        for names in ((), ("x", "x"), ("",), (" x",)):
            with self.subTest(names=names), self.assertRaises(ValueError):
                prediction.FeatureContract(
                    "contract/1", names, tuple("m" for _ in names)
                )

        invalid_units = ((), ("m",), ("m", ""), ("m", " cm"))
        for units in invalid_units:
            with self.subTest(units=units), self.assertRaises(ValueError):
                prediction.FeatureContract(
                    "contract/1", ("x", "angle"), units
                )

    def test_valid_feature_vector_matches_exact_contract(self):
        features = vector()
        self.assertIsNone(features.validate())
        self.assertIsNone(CONTRACT.validate(features))

    def test_contract_id_name_order_and_unit_mismatch_are_rejected(self):
        wrong_id = prediction.FeatureVector(
            "other/1",
            CONTRACT.feature_names,
            (1.0, 2.0),
            CONTRACT.feature_units,
        )
        wrong_order = prediction.FeatureVector(
            CONTRACT.contract_id,
            tuple(reversed(CONTRACT.feature_names)),
            (1.0, 2.0),
            CONTRACT.feature_units,
        )
        meters_vs_centimeters = prediction.FeatureVector(
            CONTRACT.contract_id,
            CONTRACT.feature_names,
            (1.0, 2.0),
            ("cm", "deg"),
        )
        degrees_vs_radians = prediction.FeatureVector(
            CONTRACT.contract_id,
            CONTRACT.feature_names,
            (1.0, 2.0),
            ("m", "rad"),
        )
        for features in (
            wrong_id,
            wrong_order,
            meters_vs_centimeters,
            degrees_vs_radians,
        ):
            with self.subTest(features=features), self.assertRaises(
                prediction.FeatureContractMismatch
            ):
                CONTRACT.validate(features)

    def test_vector_rejects_missing_or_wrong_unit_count(self):
        invalid = (
            prediction.FeatureVector(
                CONTRACT.contract_id,
                CONTRACT.feature_names,
                (1.0, 2.0),
            ),
            prediction.FeatureVector(
                CONTRACT.contract_id,
                CONTRACT.feature_names,
                (1.0, 2.0),
                ("m",),
            ),
        )
        for features in invalid:
            with self.subTest(features=features), self.assertRaises(
                prediction.FeatureValidationError
            ):
                features.validate()

    def test_vector_rejects_wrong_value_count_and_abnormal_numbers(self):
        invalid = (
            prediction.FeatureVector(
                CONTRACT.contract_id,
                CONTRACT.feature_names,
                (1.0,),
                CONTRACT.feature_units,
            ),
            prediction.FeatureVector(
                CONTRACT.contract_id,
                CONTRACT.feature_names,
                (1.0, "2"),
                CONTRACT.feature_units,
            ),
            prediction.FeatureVector(
                CONTRACT.contract_id,
                CONTRACT.feature_names,
                (1.0, True),
                CONTRACT.feature_units,
            ),
            prediction.FeatureVector(
                CONTRACT.contract_id,
                CONTRACT.feature_names,
                (1.0, math.nan),
                CONTRACT.feature_units,
            ),
            prediction.FeatureVector(
                CONTRACT.contract_id,
                CONTRACT.feature_names,
                (1.0, math.inf),
                CONTRACT.feature_units,
            ),
        )
        for features in invalid:
            with self.subTest(features=features), self.assertRaises(
                prediction.FeatureValidationError
            ):
                features.validate()


class ExecutionTests(unittest.TestCase):
    def test_default_production_executor_is_unavailable(self):
        executor = prediction.build_prediction_executor()
        result = executor.predict(vector())
        self.assertIsInstance(executor, prediction.UnavailablePredictor)
        self.assertEqual(
            result.prediction, prediction.PredictionClass.UNAVAILABLE
        )
        self.assertEqual(
            result.reason,
            prediction.PredictionReason.MODEL_ARTIFACT_UNAVAILABLE,
        )
        self.assertIsNone(result.label)

    def test_production_rejects_arbitrary_model_and_loader_injection(self):
        self.assertFalse(hasattr(prediction, "ModelPredictionRunner"))
        model = SyntheticPredictor("upright")
        loader = SyntheticLoader(model=model)

        for injected in (model, loader):
            with self.subTest(injected=type(injected).__name__):
                result = prediction.build_prediction_executor(
                    injected
                ).predict(vector())
                self.assertEqual(
                    result,
                    prediction.PredictionResult.unavailable(
                        prediction.PredictionReason.MODEL_ARTIFACT_UNAVAILABLE
                    ),
                )
        self.assertEqual(model.calls, 0)
        self.assertEqual(loader.calls, 0)

    def test_self_declared_verification_and_sha_cannot_authorize_production(self):
        class SelfDeclaredVerifiedLoader(SyntheticLoader):
            verified = True
            artifact_sha256 = "0" * 64

        loader = SelfDeclaredVerifiedLoader(
            model=SyntheticPredictor("upright")
        )
        result = prediction.build_prediction_executor(loader).predict(vector())
        self.assertEqual(
            result.prediction, prediction.PredictionClass.UNAVAILABLE
        )
        self.assertEqual(
            result.reason,
            prediction.PredictionReason.MODEL_ARTIFACT_UNAVAILABLE,
        )
        self.assertEqual(loader.calls, 0)

    def test_test_only_loader_errors_have_distinct_reasons(self):
        cases = (
            (
                FileNotFoundError("no artifact"),
                prediction.PredictionReason.MODEL_ARTIFACT_UNAVAILABLE,
            ),
            (
                RuntimeError("bad artifact"),
                prediction.PredictionReason.MODEL_LOAD_FAILED,
            ),
            (
                prediction.ModelIntegrityValidationError("hash mismatch"),
                prediction.PredictionReason.MODEL_INTEGRITY_VALIDATION_FAILED,
            ),
        )
        for error, reason in cases:
            with self.subTest(reason=reason):
                result = prediction.build_test_prediction_executor_from_loader(
                    SyntheticLoader(error=error), TEST_BINARY_MAPPING
                ).predict(vector())
                self.assertEqual(
                    result, prediction.PredictionResult.unavailable(reason)
                )
                self.assertIsNone(result.label)

    def test_test_only_malformed_loaded_model_fails_closed(self):
        result = prediction.build_test_prediction_executor_from_loader(
            SyntheticLoader(model=object()), TEST_BINARY_MAPPING
        ).predict(vector())
        self.assertEqual(
            result.prediction, prediction.PredictionClass.UNAVAILABLE
        )
        self.assertEqual(
            result.reason, prediction.PredictionReason.MODEL_LOAD_FAILED
        )

    def test_test_only_loader_rejects_invalid_mapping_before_loading(self):
        loader = SyntheticLoader(model=SyntheticPredictor())

        with self.assertRaises(ValueError):
            prediction.build_test_prediction_executor_from_loader(
                loader,
                {"body_forward": prediction.PredictionClass.POOR},
            )

        self.assertEqual(loader.calls, 0)

    def test_test_only_builders_reject_plain_string_mapping_values(self):
        for value in ("NORMAL", "POOR"):
            with self.subTest(builder="model", value=value):
                with self.assertRaises(ValueError):
                    prediction.build_test_prediction_executor(
                        SyntheticPredictor(), {"upright": value}
                    )

            loader = SyntheticLoader(model=SyntheticPredictor())
            with self.subTest(builder="loader", value=value):
                with self.assertRaises(ValueError):
                    prediction.build_test_prediction_executor_from_loader(
                        loader, {"upright": value}
                    )
                self.assertEqual(loader.calls, 0)

    def test_test_only_synthetic_model_can_exercise_normal_and_poor_mapping(self):
        cases = (
            ("upright", prediction.PredictionClass.NORMAL),
            ("forward_head", prediction.PredictionClass.POOR),
        )
        for label, expected in cases:
            with self.subTest(label=label):
                runner = prediction.build_test_prediction_executor(
                    SyntheticPredictor(label), TEST_BINARY_MAPPING
                )
                result = runner.predict(vector())
                self.assertEqual(
                    (result.prediction, result.label), (expected, label)
                )
                self.assertEqual(
                    result.reason,
                    prediction.PredictionReason.MODEL_PREDICTION,
                )

    def test_missing_binary_mapping_cannot_classify(self):
        for mapping in (None, {}):
            with self.subTest(mapping=mapping):
                result = prediction.build_test_prediction_executor(
                    SyntheticPredictor("upright"), mapping
                ).predict(vector())
                self.assertEqual(
                    result.prediction, prediction.PredictionClass.UNKNOWN
                )
                self.assertEqual(
                    result.reason,
                    prediction.PredictionReason.BINARY_MAPPING_NOT_CONFIGURED,
                )
                self.assertIsNone(result.label)

    def test_lab5_label_missing_from_mapping_fails_closed(self):
        result = prediction.build_test_prediction_executor(
            SyntheticPredictor("lean_right"),
            {"upright": prediction.PredictionClass.NORMAL},
        ).predict(vector())
        self.assertEqual(
            result,
            prediction.PredictionResult.unknown(
                prediction.PredictionReason.BINARY_MAPPING_NOT_CONFIGURED
            ),
        )

    def test_non_lab5_mapping_key_is_rejected(self):
        with self.assertRaises(ValueError):
            prediction.build_test_prediction_executor(
                SyntheticPredictor(),
                {"body_forward": prediction.PredictionClass.POOR},
            )

    def test_invalid_or_mismatched_features_never_reach_model(self):
        model = SyntheticPredictor()
        runner = prediction.build_test_prediction_executor(
            model, TEST_BINARY_MAPPING
        )
        malformed = prediction.FeatureVector(
            CONTRACT.contract_id,
            CONTRACT.feature_names,
            (1.0, math.nan),
            CONTRACT.feature_units,
        )
        mismatch = prediction.FeatureVector(
            "other/1",
            CONTRACT.feature_names,
            (1.0, 2.0),
            CONTRACT.feature_units,
        )
        self.assertEqual(
            runner.predict(malformed).reason,
            prediction.PredictionReason.FEATURE_VECTOR_INVALID,
        )
        self.assertEqual(
            runner.predict(mismatch).reason,
            prediction.PredictionReason.FEATURE_CONTRACT_MISMATCH,
        )
        self.assertEqual(model.calls, 0)

    def test_abstention_and_invalid_output_are_unknown(self):
        cases = (
            (None, prediction.PredictionReason.MODEL_ABSTAINED),
            (
                "body_forward",
                prediction.PredictionReason.MODEL_OUTPUT_INVALID,
            ),
            (1, prediction.PredictionReason.MODEL_OUTPUT_INVALID),
        )
        for output, reason in cases:
            with self.subTest(output=output):
                result = prediction.build_test_prediction_executor(
                    SyntheticPredictor(output), TEST_BINARY_MAPPING
                ).predict(vector())
                self.assertEqual(
                    result.prediction, prediction.PredictionClass.UNKNOWN
                )
                self.assertEqual(result.reason, reason)
                self.assertIsNone(result.label)

    def test_model_exception_is_unavailable_not_a_synthetic_classification(self):
        runner = prediction.build_test_prediction_executor(
            SyntheticPredictor(error=RuntimeError("inference failed")),
            TEST_BINARY_MAPPING,
        )
        result = runner.predict(vector())
        self.assertEqual(
            result.prediction, prediction.PredictionClass.UNAVAILABLE
        )
        self.assertEqual(
            result.reason,
            prediction.PredictionReason.MODEL_EXECUTION_FAILED,
        )
        self.assertIsNone(result.label)


if __name__ == "__main__":
    unittest.main()
