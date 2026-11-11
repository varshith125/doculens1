"""Global one-to-one assignment with explicit abstention and ambiguity margins."""

import numpy as np


def maximum_assignment(weights: np.ndarray) -> tuple[list[int], float]:
    """Rectangular Hungarian assignment; callers include an abstention per row.

    No field names or document geometry are involved. Returns the column chosen
    for each row and the total score. Rows must not outnumber columns.
    """
    n, m = weights.shape
    if n == 0:
        return [], 0.
    if n > m or not np.isfinite(weights).all():
        raise ValueError("Assignment requires finite weights and at least as many columns as rows")
    costs = -weights
    u, v = np.zeros(n + 1), np.zeros(m + 1)
    owner, path = np.zeros(m + 1, dtype=int), np.zeros(m + 1, dtype=int)
    for row in range(1, n + 1):
        owner[0] = row
        column = 0
        distances = np.full(m + 1, np.inf)
        visited = np.zeros(m + 1, dtype=bool)
        while True:
            visited[column] = True
            current = owner[column]
            delta, following = np.inf, 0
            for candidate in range(1, m + 1):
                if visited[candidate]:
                    continue
                reduced = costs[current - 1, candidate - 1] - u[current] - v[candidate]
                if reduced < distances[candidate]:
                    distances[candidate], path[candidate] = reduced, column
                if distances[candidate] < delta:
                    delta, following = distances[candidate], candidate
            for candidate in range(m + 1):
                if visited[candidate]:
                    u[owner[candidate]] += delta
                    v[candidate] -= delta
                else:
                    distances[candidate] -= delta
            column = following
            if owner[column] == 0:
                break
        while column:
            previous = path[column]
            owner[column] = owner[previous]
            column = previous
    result = [-1] * n
    for column in range(1, m + 1):
        if owner[column]:
            result[owner[column] - 1] = column - 1
    return result, float(sum(weights[row, column] for row, column in enumerate(result)))


def resolve_associations(candidates, headings, minimum=.70, ambiguity_margin=.075):
    """Choose a global assignment and test its best competing assignment.

    Overlapping grouping hypotheses share a resource. This prevents one OCR
    fragment from silently becoming two different fields, even in merged blocks.
    """
    resources: list[set[int]] = []
    for edges in candidates:
        for edge in edges:
            overlaps = [r for r in resources if r & edge.value.sources]
            merged = set(edge.value.sources).union(*overlaps)
            resources = [r for r in resources if not r & merged] + [merged]
    count = len(resources)
    weights = np.full((len(headings), count + len(headings)), -1e6)
    choices = {}
    for row, edges in enumerate(candidates):
        weights[row, count:] = minimum
        if headings[row].meaning.margin < .045:
            continue
        for edge in edges:
            column = next(i for i, source in enumerate(resources) if source & edge.value.sources)
            if edge.score > weights[row, column]:
                weights[row, column] = edge.score
                choices[row, column] = edge
    assignment, total = maximum_assignment(weights)
    result = []
    for row, column in enumerate(assignment):
        chosen = choices.get((row, column))
        if chosen is None:
            result.append((None, False))
            continue
        alternative = weights.copy()
        alternative[row, column] = -1e6
        _, competing = maximum_assignment(alternative)
        result.append((chosen, total - competing < ambiguity_margin))
    return result
