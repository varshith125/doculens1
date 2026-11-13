from types import SimpleNamespace

from app.extractors.association_assignment import resolve_associations


def _heading(margin=.5):
    return SimpleNamespace(meaning=SimpleNamespace(margin=margin))


def _edge(source, score):
    return SimpleNamespace(value=SimpleNamespace(sources=frozenset({source})), score=score)


def test_uncontested_value_just_above_minimum_is_not_ambiguous():
    # A caption with one far-right date and no rival heading: abstaining is
    # not a competing reading, so the printed date must be kept.
    edge = _edge(0, .726)
    assert resolve_associations([[edge]], [_heading()]) == [(edge, False)]


def test_two_headings_wanting_one_value_stay_ambiguous():
    first, second = _edge(0, .80), _edge(0, .79)
    result = resolve_associations([[first], [second]], [_heading(), _heading()])
    assert result == [(first, True), (None, False)]


def test_two_close_values_for_one_heading_stay_ambiguous():
    first, second = _edge(0, .80), _edge(1, .78)
    assert resolve_associations([[first, second]], [_heading()]) == [(first, True)]


def test_value_below_minimum_is_not_assigned():
    assert resolve_associations([[_edge(0, .65)]], [_heading()]) == [(None, False)]
