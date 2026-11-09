from __future__ import annotations

# GraphQL is used for one read only: the "blocked by" edges, which the REST list does not hold. Everything tg writes
# goes through REST (one code path, no node ids). The fake gh matches an operation by its name.


def edges_query(owner, name, numbers):
    fields = " ".join(
        f"i{n}: issue(number: {n}) {{ blockedBy(first: 100) {{ totalCount pageInfo {{ hasNextPage endCursor }} nodes {{ number }} }} }}"
        for n in numbers
    )
    return f'query Edges {{ repository(owner: "{owner}", name: "{name}") {{ {fields} }} }}'


EDGES_MORE = """query EdgesMore($owner: String!, $name: String!, $number: Int!, $after: String!) {
  repository(owner: $owner, name: $name) { issue(number: $number) { blockedBy(first: 100, after: $after) { pageInfo { hasNextPage endCursor } nodes { number } } } }
}"""
