"""Automation engine internals (Tier 3 Phase 1, §5.2): condition evaluation
semantics. Scoping, the depth guard, module gating and the executors are
covered end-to-end in tests/test_automations.py."""

from utils.automation_engine import evaluate_conditions


def _c(field, operator, value=None):
    return {"field": field, "operator": operator, "value": value}


def test_empty_conditions_always_match():
    assert evaluate_conditions([], {"anything": 1}) is True
    assert evaluate_conditions(None, {}) is True


def test_equals_and_not_equals_with_type_coercion():
    payload = {"points": 100, "name": "Ada"}
    assert evaluate_conditions([_c("points", "equals", 100)], payload)
    # String/number coercion: a form-built rule stores "100".
    assert evaluate_conditions([_c("points", "equals", "100")], payload)
    assert evaluate_conditions([_c("name", "equals", "Ada")], payload)
    assert not evaluate_conditions([_c("name", "equals", "Bob")], payload)
    assert evaluate_conditions([_c("name", "not_equals", "Bob")], payload)
    assert not evaluate_conditions([_c("points", "not_equals", "100")], payload)


def test_boolean_payload_fields():
    payload = {"is_first_blood": True}
    assert evaluate_conditions([_c("is_first_blood", "equals", True)], payload)
    assert not evaluate_conditions([_c("is_first_blood", "equals", False)], payload)


def test_numeric_comparisons():
    payload = {"points": 250}
    assert evaluate_conditions([_c("points", "gt", 100)], payload)
    assert evaluate_conditions([_c("points", "gte", 250)], payload)
    assert not evaluate_conditions([_c("points", "lt", 250)], payload)
    assert evaluate_conditions([_c("points", "lte", "250")], payload)
    # Non-numeric operand → False, never a crash (§5.2 defensive evaluation).
    assert not evaluate_conditions([_c("points", "gt", "high")], payload)
    assert not evaluate_conditions(
        [_c("subject", "gt", 10)], {"subject": "not a number"}
    )


def test_contains_on_strings_and_lists():
    assert evaluate_conditions(
        [_c("subject", "contains", "rsa")], {"subject": "baby rsa challenge"}
    )
    assert evaluate_conditions(
        [_c("tags", "contains", "web")], {"tags": ["web", "easy"]}
    )
    assert not evaluate_conditions(
        [_c("tags", "contains", "pwn")], {"tags": ["web"]}
    )
    # contains against a number → False, not a TypeError.
    assert not evaluate_conditions([_c("points", "contains", "1")], {"points": 100})


def test_exists_and_not_exists():
    payload = {"team_id": "t1", "empty": None}
    assert evaluate_conditions([_c("team_id", "exists")], payload)
    assert not evaluate_conditions([_c("empty", "exists")], payload)  # None = absent
    assert evaluate_conditions([_c("missing", "not_exists")], payload)
    assert not evaluate_conditions([_c("team_id", "not_exists")], payload)


def test_conditions_are_anded():
    payload = {"points": 500, "is_first_blood": True}
    both = [_c("points", "gt", 100), _c("is_first_blood", "equals", True)]
    assert evaluate_conditions(both, payload)
    one_fails = [_c("points", "gt", 1000), _c("is_first_blood", "equals", True)]
    assert not evaluate_conditions(one_fails, payload)


def test_unknown_operator_is_false():
    assert not evaluate_conditions([_c("points", "matches", ".*")], {"points": 1})
