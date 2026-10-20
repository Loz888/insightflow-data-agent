from decimal import Decimal
import pytest
from insightflow.evaluation.scorer import equivalent, cell


def result(rows, types=None):
    value = {"columns": ["code"], "rows": [[v] for v in rows]}
    if types is not None:
        value["column_types"] = types
    return value


@pytest.mark.parametrize(
    "left,right",
    [(["001"], ["1"]), ([True], [1]), ([None], [0]), (["2026-01-01"], ["2026-1-1"]), ([1, 1], [1, 2])],
)
def test_exact_semantics_and_multiplicity(left, right):
    assert not equivalent(result(left), result(right))


def test_numeric_tolerance_matching_cannot_sort_numeric_strings():
    assert equivalent(result([9.999999999, 2]), result([10, 2]))
    assert equivalent(result(["9.999999999", "2"], [1700]), result(["10", "2"], [1700]))
    assert not equivalent(result([2, 10]), result([10, 2]), ordered=True)


def test_augmenting_path_avoids_greedy_tolerance_failure():
    assert equivalent(
        result([Decimal("0.000000005"), Decimal("-0.00000001")]), result([0, Decimal("0.00000001")])
    )
    assert equivalent(result([1, 1, 2]), result([2, 1, 1]))


def test_only_reference_contract_can_coerce_numeric_strings():
    assert cell("001") == ("text", "001")
    assert not equivalent(result(["1"], [1700]), result(["001"]))
    assert equivalent(result(["1.00"], [1700]), result([1], [23]))
    assert not equivalent(result(["1"], [25]), result([1], [1700]))
    assert not equivalent(result(["NaN"], [1700]), result(["NaN"], [1700]))
    assert not equivalent(result([False]), result([0], [1700]))


def test_result_shape_and_matching_budget_are_explicit():
    assert not equivalent({"columns": ["code"], "rows": [[1, 2]]}, result([1]))
    with pytest.raises(ValueError, match="matching budget"):
        equivalent(result(list(range(257))), result(list(range(257))))


def test_api_evidence_type_metadata_remains_strict_and_backward_compatible():
    from pydantic import ValidationError
    from insightflow.api.schemas import Evidence

    original = {"columns": ["value"], "rows": [["1.0"]], "row_count": 1}
    assert Evidence.model_validate(original).column_types is None
    assert Evidence.model_validate({**original, "column_types": [1700]}).column_types == [1700]
    for types in ([], [True], [0], [-1], [4294967296]):
        with pytest.raises(ValidationError):
            Evidence.model_validate({**original, "column_types": types})
    with pytest.raises(ValidationError):
        Evidence.model_validate({**original, "principal": "forged"})
