from __future__ import annotations


SAMPLE_QUERIES: dict[str, list[dict[str, str]]] = {
    "orders": [
        {
            "label": "Query 1",
            "query": "Show me recent order records of customers",
        },
        {
            "label": "Query 2",
            "query": "Build a table of customers, orders, product families, quantities, and preferred carriers.",
        },
    ],
    "country": [
        {
            "label": "Query 1",
            "query": "Show a table containing a country's education situation",
        },
        {
            "label": "Query 2",
            "query": "Build a country profile table with renewable energy, temperature, inflation, tourism, and GDP details.",
        },
    ],
}


def sample_queries_for(datalake: str) -> list[dict[str, str]]:
    return SAMPLE_QUERIES.get(datalake, [])

