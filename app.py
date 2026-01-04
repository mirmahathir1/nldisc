import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import graphviz
import numpy as np
import pandas as pd
import streamlit as st


def _inject_css():
    st.markdown(
        """
<style>
  /* Layout */
  .block-container { padding-top: 1.25rem; padding-bottom: 2rem; max-width: 1200px; }

  /* App header */
  .nldisc-header {
    padding: 1.1rem 1.2rem;
    border-radius: 16px;
    background: linear-gradient(135deg, rgba(37,99,235,0.12), rgba(99,102,241,0.10));
    border: 1px solid rgba(17,24,39,0.08);
    margin-bottom: 0.85rem;
  }
  .nldisc-title { font-size: 2.0rem; font-weight: 800; letter-spacing: -0.02em; margin: 0; color: #111827; }
  .nldisc-subtitle { margin-top: 0.25rem; color: rgba(17,24,39,0.72); font-size: 0.98rem; }

  /* Stepper */
  .stepper { display: flex; gap: 0.5rem; flex-wrap: wrap; margin: 0.6rem 0 1.0rem; }
  .step {
    padding: 0.35rem 0.6rem;
    border-radius: 999px;
    border: 1px solid rgba(17,24,39,0.10);
    background: rgba(243,244,246,0.75);
    color: rgba(17,24,39,0.75);
    font-size: 0.86rem;
    line-height: 1.1rem;
    white-space: nowrap;
  }
  .step-active {
    background: rgba(37,99,235,0.14);
    border-color: rgba(37,99,235,0.35);
    color: rgba(17,24,39,0.92);
    font-weight: 650;
  }

  /* Card styling (Streamlit bordered containers) */
  div[data-testid="stVerticalBlockBorderWrapper"] {
    border-radius: 16px !important;
    border: 1px solid rgba(17,24,39,0.10) !important;
    box-shadow: 0 1px 0 rgba(17,24,39,0.04);
    background: rgba(255,255,255,0.75);
  }
  /* Make widgets feel slightly tighter */
  .stButton > button, .stDownloadButton > button { border-radius: 12px; }
  .stTextInput input, .stNumberInput input, .stSelectbox div, .stSlider div { border-radius: 12px; }
</style>
        """,
        unsafe_allow_html=True,
    )


def _render_stepper(active_stage: str):
    steps = [
        "1) Upload data lake",
        "2) Preprocess & build indexes",
        "3) Query & disambiguate (query tables)",
        "4) Join paths, SQL & download",
    ]
    items = []
    for s in steps:
        cls = "step step-active" if s == active_stage else "step"
        label = s.split(") ", 1)[1]
        items.append(f'<span class="{cls}">{label}</span>')
    st.markdown(f'<div class="stepper">{"".join(items)}</div>', unsafe_allow_html=True)


@dataclass(frozen=True)
class JoinEdge:
    left_table: str
    left_col: str
    right_table: str
    right_col: str
    kind: str  # "equi" | "semantic"
    confidence: float

    def other(self, table: str) -> str:
        if table == self.left_table:
            return self.right_table
        if table == self.right_table:
            return self.left_table
        raise ValueError(f"Table {table} not part of edge {self}")

    def join_cols(self, left: str, right: str) -> Tuple[Tuple[str, str], Tuple[str, str]]:
        """Return ((left_table,left_col),(right_table,right_col)) in the requested direction."""
        if left == self.left_table and right == self.right_table:
            return (self.left_table, self.left_col), (self.right_table, self.right_col)
        if left == self.right_table and right == self.left_table:
            return (self.right_table, self.right_col), (self.left_table, self.left_col)
        raise ValueError(f"Edge {self} does not connect {left} -> {right}")


def _seed_from_string(s: str) -> int:
    return abs(hash(s)) % (2**31 - 1)


@st.cache_data(show_spinner=False)
def make_default_data_lake(seed: int = 7) -> Dict[str, pd.DataFrame]:
    rng = np.random.default_rng(seed)

    products = pd.DataFrame(
        {
            "product_id": np.arange(1, 11),
            "product_name": [
                "Road Bike",
                "Mountain Bike",
                "Helmet",
                "Cycling Jersey",
                "Water Bottle",
                "Bike Lock",
                "Tire Pump",
                "Chain Lube",
                "Gloves",
                "Sunglasses",
            ],
            "category": [
                "Bikes",
                "Bikes",
                "Safety",
                "Apparel",
                "Accessories",
                "Accessories",
                "Accessories",
                "Accessories",
                "Apparel",
                "Accessories",
            ],
        }
    )

    stores = pd.DataFrame(
        {
            "store_id": np.arange(1, 6),
            "store_name": ["Downtown", "Mall", "Airport", "Suburb", "Outlet"],
            "region": ["West", "West", "East", "South", "North"],
        }
    )

    quarters = []
    qid = 1
    for year in [2024, 2025]:
        for q in [1, 2, 3, 4]:
            quarters.append(
                {
                    "quarter_id": qid,
                    "year": year,
                    "quarter": f"Q{q}",
                    "quarter_label": f"{year}-Q{q}",
                }
            )
            qid += 1
    quarters = pd.DataFrame(quarters)

    n_sales = 180
    sales_quantities = pd.DataFrame(
        {
            "sale_id": np.arange(10001, 10001 + n_sales),
            "product_id": rng.integers(1, 11, size=n_sales),
            "store_id": rng.integers(1, 6, size=n_sales),
            "quarter_id": rng.integers(1, len(quarters) + 1, size=n_sales),
            "quantity": rng.integers(1, 7, size=n_sales),
        }
    )

    # Intentionally: total_amount lives in a different table, connected via sale_id.
    price_map = {
        1: 899.0,
        2: 1099.0,
        3: 49.0,
        4: 79.0,
        5: 12.0,
        6: 25.0,
        7: 35.0,
        8: 9.0,
        9: 29.0,
        10: 59.0,
    }
    unit_prices = sales_quantities["product_id"].map(price_map).astype(float)
    noise = rng.normal(0.0, 0.06, size=n_sales)  # small variation
    total_amount = (sales_quantities["quantity"] * unit_prices * (1.0 + noise)).round(2)

    sales_amounts = pd.DataFrame(
        {
            "sale_id": sales_quantities["sale_id"].values,
            "quarter_id": sales_quantities["quarter_id"].values,
            "total_amount": total_amount,
            "currency": ["USD"] * n_sales,
        }
    )

    return {
        "products": products,
        "stores": stores,
        "quarters": quarters,
        "sales_quantities": sales_quantities,
        "sales_amounts": sales_amounts,
    }


def build_join_graph(params: Dict[str, Any]) -> List[JoinEdge]:
    # Fixed join graph. Params are used to filter low-confidence edges.
    edges = [
        JoinEdge("sales_quantities", "product_id", "products", "product_id", "equi", 0.99),
        JoinEdge("sales_quantities", "store_id", "stores", "store_id", "equi", 0.98),
        JoinEdge("sales_quantities", "quarter_id", "quarters", "quarter_id", "equi", 0.97),
        # The "hidden table" story: to get from sales_amounts to products, we need sales_quantities.
        JoinEdge("sales_amounts", "sale_id", "sales_quantities", "sale_id", "equi", 0.96),
        # Redundant but plausible path:
        JoinEdge("sales_amounts", "quarter_id", "quarters", "quarter_id", "semantic", 0.75),
    ]
    equi_thr = float(params.get("equi_joinability_threshold", 0.9))
    sem_thr = float(params.get("semantic_joinability_threshold", 0.75))
    out: List[JoinEdge] = []
    for e in edges:
        if e.kind == "equi" and e.confidence >= equi_thr:
            out.append(e)
        if e.kind == "semantic" and e.confidence >= sem_thr:
            out.append(e)
    return out


def _adjacency(edges: List[JoinEdge]) -> Dict[str, List[JoinEdge]]:
    adj: Dict[str, List[JoinEdge]] = {}
    for e in edges:
        adj.setdefault(e.left_table, []).append(e)
        adj.setdefault(e.right_table, []).append(e)
    return adj


def enumerate_simple_paths(edges: List[JoinEdge], max_len: int) -> List[List[str]]:
    adj = _adjacency(edges)
    tables = sorted(adj.keys())
    paths: List[List[str]] = []

    def dfs(cur: str, visited: List[str]):
        if len(visited) >= 2:
            paths.append(visited.copy())
        if len(visited) >= max_len:
            return
        for e in adj.get(cur, []):
            nxt = e.other(cur)
            if nxt in visited:
                continue
            visited.append(nxt)
            dfs(nxt, visited)
            visited.pop()

    for t in tables:
        dfs(t, [t])

    # Deduplicate by canonical (path or reversed path)
    seen = set()
    uniq: List[List[str]] = []
    for p in paths:
        key = tuple(p)
        rkey = tuple(reversed(p))
        canon = min(key, rkey)
        if canon in seen:
            continue
        seen.add(canon)
        uniq.append(p)
    return uniq


def score_path(path: List[str], edges: List[JoinEdge]) -> float:
    # Simple: average confidence of edges used, prefer shorter paths slightly.
    edge_map = {(e.left_table, e.right_table): e for e in edges}
    edge_map.update({(e.right_table, e.left_table): e for e in edges})
    confs = []
    for a, b in zip(path, path[1:]):
        e = edge_map.get((a, b))
        if e:
            confs.append(e.confidence)
    avg = float(np.mean(confs)) if confs else 0.0
    length_penalty = 0.02 * max(0, len(path) - 2)
    return avg - length_penalty


def build_join_path_index(edges: List[JoinEdge], max_path_len: int) -> pd.DataFrame:
    paths = enumerate_simple_paths(edges, max_len=max_path_len)
    rows = []
    for i, p in enumerate(paths, start=1):
        rows.append(
            {
                "path_id": f"JP-{i:03d}",
                "tables": " → ".join(p),
                "tables_set": tuple(p),
                "length": len(p),
                "score": round(score_path(p, edges), 4),
            }
        )
    df = pd.DataFrame(rows).sort_values(["score", "length"], ascending=[False, True]).reset_index(drop=True)
    return df


def build_semantic_type_index(data_lake: Dict[str, pd.DataFrame], seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)

    def infer_type(col: str, series: pd.Series) -> str:
        lc = col.lower()
        if lc.endswith("_id"):
            return "Identifier"
        if "amount" in lc or "price" in lc:
            return "Money"
        if "quarter" in lc or "year" in lc:
            return "TimePeriod"
        if series.dtype.kind in {"i", "u", "f"}:
            return "Number"
        return "Text"

    rows = []
    for tname, df in data_lake.items():
        for col in df.columns:
            stype = infer_type(col, df[col])
            # Embedding: small fixed-size vector
            emb = rng.normal(size=8).round(3).tolist()
            rows.append(
                {
                    "table": tname,
                    "column": col,
                    "semantic_type": stype,
                    "example_values": ", ".join(map(str, df[col].head(3).tolist())),
                    "embedding(8d)": emb,
                }
            )
    return pd.DataFrame(rows)


def parse_nl_query(query: str) -> Dict[str, Any]:
    q = query.lower()
    wants_sales = "sales" in q or "revenue" in q or "amount" in q
    wants_products = "product" in q or "sku" in q or "item" in q
    wants_store = "store" in q or "region" in q
    wants_quarter = "quarter" in q or "quarters" in q or "q1" in q or "q2" in q or "q3" in q or "q4" in q
    wants_past = "past" in q or "last" in q or "previous" in q

    semantic_types = []
    if wants_sales:
        semantic_types.append("Money")
    if wants_quarter:
        semantic_types.append("TimePeriod")
    if wants_products:
        semantic_types.append("Text")
    if wants_store:
        semantic_types.append("Text")

    examples = []
    if wants_quarter:
        examples += ["2025-Q1", "2025-Q2"]
    if wants_sales:
        examples += ["1500.00", "3200.50"]
    if wants_products:
        examples += ["Road Bike", "Helmet"]

    preds = []
    if wants_past and wants_quarter:
        preds.append({"field": "quarter_label", "op": "IN", "value": "past quarters"})

    return {
        "semantic_types": semantic_types or ["(unknown)"],
        "example_values": examples or ["(none)"],
        "selection_predicates": preds or [],
        "signals": {
            "wants_sales": wants_sales,
            "wants_products": wants_products,
            "wants_store": wants_store,
            "wants_quarter": wants_quarter,
        },
    }


def _apply_predicates_to_query_tables(
    query_tables: List[Tuple[str, pd.DataFrame]], predicates: List[Dict[str, Any]], seed: int
) -> List[Tuple[str, pd.DataFrame]]:
    if not predicates:
        return query_tables

    rng = np.random.default_rng(seed ^ 0xC0FFEE)

    def adjust_series(s: pd.Series, op: str, v: float) -> pd.Series:
        if not pd.api.types.is_numeric_dtype(s):
            return s
        if op == ">":
            bump = rng.integers(1, 250, size=len(s)).astype(float)
            return np.maximum(s.astype(float), v + bump)
        if op == "<":
            bump = rng.integers(1, 250, size=len(s)).astype(float)
            out = np.minimum(s.astype(float), v - bump)
            return np.maximum(out, 0.0)
        if op in {"==", "="}:
            return pd.Series([float(v)] * len(s), index=s.index)
        return s

    out: List[Tuple[str, pd.DataFrame]] = []
    for name, df in query_tables:
        df2 = df.copy()
        for pred in predicates:
            field = str(pred.get("field", ""))
            if not field or field not in df2.columns:
                continue
            op = str(pred.get("op", ">"))
            v = float(pred.get("value", 0))
            df2[field] = adjust_series(df2[field], op=op, v=v)
        out.append((name, df2))
    return out


def generate_query_tables(
    query: str,
    seed: int,
    predicates: Optional[List[Dict[str, Any]]] = None,
    suggestion_count: int = 4,
) -> List[Tuple[str, pd.DataFrame]]:
    rng = np.random.default_rng(seed)
    parsed = parse_nl_query(query)
    s = parsed["signals"]

    base_quarters = pd.DataFrame({"quarter_label": ["2025-Q1", "2025-Q2", "2025-Q3"]})

    qt1 = base_quarters.copy()
    if s["wants_sales"]:
        qt1["total_amount"] = rng.integers(900, 4500, size=len(qt1)).astype(float)
    if s["wants_products"]:
        qt1["product_name"] = ["Road Bike", "Helmet", "Cycling Jersey"][: len(qt1)]

    qt2 = base_quarters.copy()
    if s["wants_sales"]:
        qt2["total_amount"] = rng.integers(500, 9000, size=len(qt2)).astype(float)
    qt2["store_name"] = ["Downtown", "Mall", "Outlet"][: len(qt2)]

    qt3 = pd.DataFrame(
        {
            "product_name": ["Road Bike", "Mountain Bike", "Helmet"],
            "quarter_label": ["2025-Q1", "2025-Q1", "2025-Q2"],
            "total_amount": rng.integers(1200, 7000, size=3).astype(float),
        }
    )

    qt4 = pd.DataFrame(
        {
            "quarter_label": ["2024-Q4", "2025-Q1", "2025-Q2"],
            "total_amount": rng.integers(800, 5000, size=3).astype(float),
            "currency": ["USD", "USD", "USD"],
        }
    )

    qts: List[Tuple[str, pd.DataFrame]] = [
        ("Query Table 1 (balanced)", qt1),
        ("Query Table 2 (by store)", qt2),
        ("Query Table 3 (matches sales + quarter + product)", qt3),
        ("Query Table 4 (sales-only)", qt4),
    ]

    # Produce up to N suggestions by creating additional variants.
    target = int(max(1, min(10, suggestion_count)))
    if target > len(qts):
        for i in range(len(qts) + 1, target + 1):
            v = base_quarters.copy()
            # Vary which identifying columns are present.
            pick = (i - 1) % 3
            if s["wants_sales"]:
                lo = int(rng.integers(400, 1400))
                hi = int(rng.integers(4500, 12000))
                v["total_amount"] = rng.integers(lo, hi, size=len(v)).astype(float)
            if pick == 0:
                v["product_name"] = ["Road Bike", "Helmet", "Sunglasses"][: len(v)]
            elif pick == 1:
                v["store_name"] = ["Downtown", "Airport", "Outlet"][: len(v)]
            else:
                v["currency"] = ["USD"] * len(v)
            qts.append((f"Query Table {i}", v))

    qts = qts[:target]
    return _apply_predicates_to_query_tables(qts, predicates or [], seed=seed)


def infer_candidate_tables_from_query_table(df: pd.DataFrame) -> List[str]:
    cols = [c.lower() for c in df.columns]
    candidates = set()
    if any("product" in c for c in cols):
        candidates.add("products")
    if any("store" in c or "region" in c for c in cols):
        candidates.add("stores")
    if any("quarter" in c or "year" in c for c in cols):
        candidates.add("quarters")
    if any("amount" in c or "currency" in c for c in cols):
        candidates.add("sales_amounts")
    # Hidden-table possibility:
    if "sales_amounts" in candidates and "products" in candidates:
        candidates.add("sales_quantities")
    return sorted(candidates)


def find_top_join_paths(
    join_path_index: pd.DataFrame, required_tables: List[str], k: int
) -> pd.DataFrame:
    req = set(required_tables)

    def covers(tables_str: str) -> bool:
        tables = [t.strip() for t in tables_str.split("→")]
        return req.issubset(set(tables))

    filt = join_path_index[join_path_index["tables"].apply(covers)].copy()
    if filt.empty:
        return filt
    return filt.head(k).reset_index(drop=True)


def edge_lookup(edges: List[JoinEdge]) -> Dict[Tuple[str, str], JoinEdge]:
    m = {(e.left_table, e.right_table): e for e in edges}
    m.update({(e.right_table, e.left_table): e for e in edges})
    return m


def materialize_path(
    data_lake: Dict[str, pd.DataFrame], path: List[str], edges: List[JoinEdge], limit: int = 2000
) -> pd.DataFrame:
    m = edge_lookup(edges)
    df = data_lake[path[0]].copy()
    df = df.add_prefix(f"{path[0]}.")

    for left_t, right_t in zip(path, path[1:]):
        e = m[(left_t, right_t)]
        (lt, lc), (rt, rc) = e.join_cols(left_t, right_t)

        right_df = data_lake[right_t].copy().add_prefix(f"{right_t}.")
        left_key = f"{lt}.{lc}"
        right_key = f"{rt}.{rc}"
        df = df.merge(right_df, how="inner", left_on=left_key, right_on=right_key)

    return df.head(limit)


def sql_for_path(path: List[str], edges: List[JoinEdge]) -> str:
    m = edge_lookup(edges)
    aliases = {t: f"t{i}" for i, t in enumerate(path, start=1)}
    lines = []
    lines.append("SELECT")
    lines.append("  *")
    lines.append(f"FROM {path[0]} {aliases[path[0]]}")
    for left_t, right_t in zip(path, path[1:]):
        e = m[(left_t, right_t)]
        (lt, lc), (rt, rc) = e.join_cols(left_t, right_t)
        lines.append(
            f"JOIN {right_t} {aliases[right_t]} ON {aliases[lt]}.{lc} = {aliases[rt]}.{rc}"
        )
    return "\n".join(lines) + ";"


def graphviz_for_join_graph(edges: List[JoinEdge]) -> graphviz.Digraph:
    g = graphviz.Digraph("join_graph")
    g.attr(rankdir="LR", bgcolor="transparent", splines="spline")
    g.attr("node", shape="box", style="rounded,filled", fillcolor="#F3F4F6", color="#9CA3AF", fontname="Helvetica")
    g.attr("edge", color="#6B7280", fontname="Helvetica", fontsize="10")

    tables = sorted({t for e in edges for t in (e.left_table, e.right_table)})
    for t in tables:
        g.node(t, label=t)

    for e in edges:
        label = f"{e.left_col} = {e.right_col}\\n{e.kind} ({e.confidence:.2f})"
        g.edge(e.left_table, e.right_table, label=label)

    return g


def graphviz_for_join_path(path: List[str], edges: List[JoinEdge]) -> graphviz.Digraph:
    g = graphviz.Digraph("join_path")
    g.attr(rankdir="LR", bgcolor="transparent", splines="spline")
    g.attr("node", shape="box", style="rounded,filled", fillcolor="#EEF2FF", color="#6366F1", fontname="Helvetica")
    g.attr("edge", color="#4F46E5", fontname="Helvetica", fontsize="10", penwidth="2")

    m = edge_lookup(edges)
    for t in path:
        g.node(t, label=t)
    for left_t, right_t in zip(path, path[1:]):
        e = m[(left_t, right_t)]
        (lt, lc), (rt, rc) = e.join_cols(left_t, right_t)
        label = f"{lc} = {rc}\\n{e.kind} ({e.confidence:.2f})"
        g.edge(lt, rt, label=label)
    return g


def count_rows_for_path(data_lake: Dict[str, pd.DataFrame], path: List[str], edges: List[JoinEdge]) -> int:
    """Count output rows for a join path using only join key columns (faster than full materialization)."""
    m = edge_lookup(edges)

    needed: Dict[str, set[str]] = {t: set() for t in path}
    for left_t, right_t in zip(path, path[1:]):
        e = m[(left_t, right_t)]
        (lt, lc), (rt, rc) = e.join_cols(left_t, right_t)
        needed[lt].add(lc)
        needed[rt].add(rc)

    df = data_lake[path[0]][sorted(needed[path[0]])].copy().add_prefix(f"{path[0]}.")
    for left_t, right_t in zip(path, path[1:]):
        e = m[(left_t, right_t)]
        (lt, lc), (rt, rc) = e.join_cols(left_t, right_t)
        right_df = data_lake[right_t][sorted(needed[right_t])].copy().add_prefix(f"{right_t}.")

        left_key = f"{lt}.{lc}"
        right_key = f"{rt}.{rc}"
        df = df.merge(right_df, how="inner", left_on=left_key, right_on=right_key)

    return int(len(df))


def _preprocess_signature() -> str:
    # Used to invalidate cached per-path counts when thresholds / data lake changes.
    lake = st.session_state.data_lake or {}
    lake_sig = "|".join(f"{k}:{len(v)}x{len(v.columns)}" for k, v in sorted(lake.items()))
    p = st.session_state.params
    p_sig = "|".join(
        [
            str(p.get("semantic_type_similarity_threshold")),
            str(p.get("semantic_joinability_threshold")),
            str(p.get("equi_joinability_threshold")),
            str(p.get("max_join_path_length")),
        ]
    )
    return f"{lake_sig}::{p_sig}"


def init_state():
    st.session_state.setdefault("stage", "1) Upload data lake")
    st.session_state.setdefault("data_lake", None)
    st.session_state.setdefault("preprocessed", False)
    st.session_state.setdefault("semantic_index", None)
    st.session_state.setdefault("join_edges", None)
    st.session_state.setdefault("join_path_index", None)
    st.session_state.setdefault("nl_query", "Show me sales data for the past quarters.")
    st.session_state.setdefault("query_tables", None)
    st.session_state.setdefault("selected_qt_name", None)
    st.session_state.setdefault("edited_qt", None)
    st.session_state.setdefault("confirmed_qt", None)
    st.session_state.setdefault("predicates", [])
    st.session_state.setdefault("top_paths", None)
    st.session_state.setdefault("selected_path_id", None)
    st.session_state.setdefault("query_tables_seed", None)
    st.session_state.setdefault("query_tables_pred_sig", None)
    st.session_state.setdefault("qt_editor_version", 0)
    st.session_state.setdefault("preprocess_expanded_paths", set())
    st.session_state.setdefault("preprocess_row_counts", {})  # key: (signature, path_id) -> count
    st.session_state.setdefault(
        "params",
        {
            "semantic_type_similarity_threshold": 0.75,
            "semantic_joinability_threshold": 0.75,
            "equi_joinability_threshold": 0.9,
            "max_join_path_length": 5,
            "top_k_paths": 5,
            "ann_topk": 25,
            "query_table_suggestion_count": 4,
        },
    )


def main():
    st.set_page_config(page_title="NLDisc — Join Discovery via Natural Language", layout="wide")
    init_state()

    _inject_css()

    st.markdown(
        """
<div class="nldisc-header">
  <div class="nldisc-title">NLDisc</div>
  <div class="nldisc-subtitle">Join discovery from natural language via iterative disambiguation and join-path search</div>
</div>
        """,
        unsafe_allow_html=True,
    )

    with st.sidebar:
        st.subheader("Stages")
        st.session_state.stage = st.radio(
            "Navigate",
            options=[
                "1) Upload data lake",
                "2) Preprocess & build indexes",
                "3) Query & disambiguate (query tables)",
                "4) Join paths, SQL & download",
            ],
            index=[
                "1) Upload data lake",
                "2) Preprocess & build indexes",
                "3) Query & disambiguate (query tables)",
                "4) Join paths, SQL & download",
            ].index(st.session_state.stage),
        )

    stage = st.session_state.stage
    _render_stepper(stage)

    if stage == "1) Upload data lake":
        render_stage_upload()
    elif stage == "2) Preprocess & build indexes":
        render_stage_preprocess()
    elif stage == "3) Query & disambiguate (query tables)":
        render_stage_query_tables()
    elif stage == "4) Join paths, SQL & download":
        render_stage_results()


def require_data_lake():
    if st.session_state.data_lake is None:
        st.warning("Please complete **Stage 1** first (load the data lake).")
        st.stop()


def require_preprocessed():
    require_data_lake()
    if not st.session_state.preprocessed:
        st.warning("Please complete **Stage 2** first (preprocess and build indexes).")
        st.stop()


def _reset_pipeline_state():
    st.session_state.preprocessed = False
    st.session_state.semantic_index = None
    st.session_state.join_edges = None
    st.session_state.join_path_index = None
    st.session_state.query_tables = None
    st.session_state.selected_qt_name = None
    st.session_state.edited_qt = None
    st.session_state.confirmed_qt = None
    st.session_state.predicates = []
    st.session_state.top_paths = None
    st.session_state.selected_path_id = None
    st.session_state.query_tables_seed = None
    st.session_state.query_tables_pred_sig = None
    st.session_state.qt_editor_version = int(st.session_state.get("qt_editor_version", 0)) + 1
    st.session_state.preprocess_expanded_paths = set()
    st.session_state.preprocess_row_counts = {}


def render_stage_upload():
    left, right = st.columns([1.2, 1.0], gap="large")

    with left:
        with st.container(border=True):
            st.subheader("Upload a data lake")
            st.caption("Upload one or more CSV tables. Each CSV becomes a table named after its filename.")

            uploaded = st.file_uploader("Upload CSVs", type=["csv"], accept_multiple_files=True)

            a, b = st.columns([1, 1])
            with a:
                if st.button("Load uploaded data lake", type="primary", disabled=not uploaded):
                    tables: Dict[str, pd.DataFrame] = {}
                    for f in uploaded or []:
                        name = f.name.rsplit(".", 1)[0]
                        tables[name] = pd.read_csv(f)
                    st.session_state.data_lake = tables
                    _reset_pipeline_state()
                    st.success("Loaded data lake.")
            with b:
                if st.button("Load default data lake"):
                    st.session_state.data_lake = make_default_data_lake(seed=7)
                    _reset_pipeline_state()
                    st.success("Loaded data lake.")

    with right:
        with st.container(border=True):
            st.subheader("Data lake")
            if st.session_state.data_lake is None:
                st.write("No tables loaded yet.")
                return

            lake = st.session_state.data_lake
            meta = []
            for name, df in lake.items():
                meta.append({"table": name, "rows": len(df), "cols": len(df.columns), "columns": ", ".join(df.columns)})
            st.dataframe(pd.DataFrame(meta), use_container_width=True, hide_index=True)

            c1, c2 = st.columns([1, 1])
            with c1:
                st.metric("Tables", len(lake))
            with c2:
                st.metric("Total rows", int(sum(len(df) for df in lake.values())))

            preview_table = st.selectbox("Preview table", options=sorted(lake.keys()))
            st.dataframe(lake[preview_table].head(25), use_container_width=True)


def render_stage_preprocess():
    require_data_lake()
    params = st.session_state.params

    st.subheader("Preprocess")
    st.caption("Build semantic type index, join graph, and join path index for the current data lake.")

    with st.container(border=True):
        st.markdown("**Thresholds**")
        t1, t2, t3, t4 = st.columns([1, 1, 1, 1], gap="large")
        with t1:
            params["semantic_type_similarity_threshold"] = st.slider(
                "Semantic Type Similarity Threshold",
                0.0,
                1.0,
                float(params["semantic_type_similarity_threshold"]),
                0.01,
            )
        with t2:
            params["semantic_joinability_threshold"] = st.slider(
                "Semantic Joinability Threshold",
                0.0,
                1.0,
                float(params["semantic_joinability_threshold"]),
                0.01,
            )
        with t3:
            params["equi_joinability_threshold"] = st.slider(
                "Equi Joinability Threshold",
                0.0,
                1.0,
                float(params["equi_joinability_threshold"]),
                0.01,
            )
        with t4:
            params["max_join_path_length"] = st.slider(
                "Maximum Join Path Length",
                2,
                10,
                int(params["max_join_path_length"]),
                1,
            )

    cols = st.columns([1.0, 1.0], gap="large")
    with cols[0]:
        with st.container(border=True):
            st.markdown("**Build indexes**")
            st.caption("Runs indexing for the current data lake and threshold settings.")
            if st.button("Run preprocessing", type="primary"):
                with st.status("Preprocessing...", expanded=True) as status:
                    st.write("Extracting semantic types and embeddings…")
                    time.sleep(0.4)
                    st.session_state.semantic_index = build_semantic_type_index(
                        st.session_state.data_lake, seed=_seed_from_string("semantic")
                    )
                    st.write("Building join graph…")
                    time.sleep(0.4)
                    st.session_state.join_edges = build_join_graph(params)
                    st.write("Enumerating join paths + building join path index…")
                    time.sleep(0.4)
                    st.session_state.join_path_index = build_join_path_index(
                        st.session_state.join_edges, max_path_len=int(params["max_join_path_length"])
                    )
                    st.session_state.preprocessed = True
                    status.update(label="Done", state="complete")

    with cols[1]:
        if not st.session_state.preprocessed:
            with st.container(border=True):
                st.info("Run preprocessing to view the join graph and join paths.")
            return

        edges = st.session_state.join_edges
        with st.container(border=True):
            st.markdown("**Join graph**")
            st.graphviz_chart(graphviz_for_join_graph(edges), use_container_width=True)

        with st.expander("Show join edges as a table"):
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "left": f"{e.left_table}.{e.left_col}",
                            "right": f"{e.right_table}.{e.right_col}",
                            "kind": e.kind,
                            "confidence": e.confidence,
                        }
                        for e in edges
                    ]
                ),
                use_container_width=True,
                hide_index=True,
            )

        with st.container(border=True):
            st.markdown("**Join paths**")
            jpi = st.session_state.join_path_index

            lake = st.session_state.data_lake
            sig = _preprocess_signature()
            row_counts: Dict[Tuple[str, str], int] = st.session_state.preprocess_row_counts

            top = jpi[["path_id", "tables", "length"]].head(12).copy()
            computed_counts: List[Optional[int]] = []
            for _, r in top.iterrows():
                key = (sig, r["path_id"])
                if key not in row_counts:
                    path = [t.strip() for t in r["tables"].split("→")]
                    try:
                        row_counts[key] = count_rows_for_path(lake, path, edges)
                    except Exception:
                        row_counts[key] = -1
                computed_counts.append(row_counts[key])
            top["row_count"] = computed_counts

            # Show paths as rows with a per-path action.
            header = st.columns([0.9, 3.0, 0.7, 0.9, 1.5])
            header[0].markdown("**Path**")
            header[1].markdown("**Tables**")
            header[2].markdown("**Len**")
            header[3].markdown("**Rows**")
            header[4].markdown("**Action**")

            for _, r in top.iterrows():
                c = st.columns([0.9, 3.0, 0.7, 0.9, 1.5])
                c[0].write(r["path_id"])
                c[1].write(r["tables"])
                c[2].write(int(r["length"]))
                rc = int(r["row_count"])
                c[3].write("—" if rc < 0 else rc)
                pid = str(r["path_id"])
                expanded = pid in st.session_state.preprocess_expanded_paths
                label = "Hide path" if expanded else "Show path"
                if c[4].button(label, key=f"preprocess_toggle_{pid}", use_container_width=True):
                    if expanded:
                        st.session_state.preprocess_expanded_paths.remove(pid)
                    else:
                        st.session_state.preprocess_expanded_paths.add(pid)
                    st.rerun()

                if pid in st.session_state.preprocess_expanded_paths:
                    path = [t.strip() for t in str(r["tables"]).split("→")]
                    st.graphviz_chart(graphviz_for_join_path(path, edges), use_container_width=True)

        with st.expander("Semantic type index (sample)"):
            st.dataframe(st.session_state.semantic_index.head(20), use_container_width=True, hide_index=True)


def render_stage_query_tables():
    require_preprocessed()

    st.subheader("Query: natural language → query tables → iterative disambiguation")

    params = st.session_state.params
    lake = st.session_state.data_lake
    col1, col2 = st.columns([1.1, 1.0], gap="large")

    def pred_signature(preds: List[Dict[str, Any]]) -> str:
        if not preds:
            return ""
        parts = []
        for p in preds:
            parts.append(f"{p.get('field','')}|{p.get('op','')}|{p.get('value','')}")
        return ";".join(parts)

    def set_query_tables(seed: int):
        prev_selected = st.session_state.selected_qt_name
        qts = generate_query_tables(
            st.session_state.nl_query,
            seed=seed,
            predicates=st.session_state.predicates,
            suggestion_count=int(params.get("query_table_suggestion_count", 4)),
        )
        st.session_state.query_tables = qts
        names = [n for n, _ in qts]
        st.session_state.selected_qt_name = prev_selected if prev_selected in names else names[0]
        st.session_state.edited_qt = dict(qts)[st.session_state.selected_qt_name].copy()
        st.session_state.confirmed_qt = None
        st.session_state.top_paths = None
        st.session_state.query_tables_seed = seed
        st.session_state.query_tables_pred_sig = pred_signature(st.session_state.predicates)

    with col1:
        with st.container(border=True):
            st.markdown("**Natural language query**")
            q = st.text_input(
                "Query",
                value=st.session_state.nl_query,
                placeholder="e.g., Show me sales data for the past quarters.",
            )
            st.session_state.nl_query = q

            params["query_table_suggestion_count"] = st.slider(
                "Query table suggestions",
                min_value=1,
                max_value=10,
                value=int(params.get("query_table_suggestion_count", 4)),
                step=1,
            )

            if st.button("Generate query tables", type="primary"):
                seed = _seed_from_string(q) ^ 0xA5A5
                set_query_tables(seed)
                st.success("Generated candidate query tables.")

    with col2:
        if st.session_state.query_tables is None:
            return

        with st.container(border=True):
            st.markdown("**Candidate query tables**")
            qt_names = [name for name, _ in st.session_state.query_tables]
            st.session_state.selected_qt_name = st.radio(
                "Pick the query table that best matches your intent",
                options=qt_names,
                index=qt_names.index(st.session_state.selected_qt_name)
                if st.session_state.selected_qt_name in qt_names
                else 0,
            )

            selected_df = dict(st.session_state.query_tables)[st.session_state.selected_qt_name]
            st.dataframe(selected_df, use_container_width=True, hide_index=True)

        with st.container(border=True):
            st.markdown("**Edit query table (query-by-example)**")
            edited = st.data_editor(
                selected_df,
                use_container_width=True,
                hide_index=True,
                num_rows="dynamic",
                key=f"qt_editor_{st.session_state.qt_editor_version}",
            )
            st.session_state.edited_qt = edited

            st.markdown("**Optional predicate**")
            num_cols = [c for c in edited.columns if pd.api.types.is_numeric_dtype(edited[c])]
            pred_col = st.selectbox("Numeric column", options=(["(none)"] + num_cols), index=0)
            op_label_to_op = {"greater than": ">", "less than": "<", "equal": "=="}
            pred_op_label = st.selectbox(
                "Operator",
                options=list(op_label_to_op.keys()),
                index=0,
                disabled=(pred_col == "(none)"),
            )
            pred_val = st.number_input(
                "Value",
                value=2000.0,
                step=100.0,
                disabled=(pred_col == "(none)"),
            )
            if pred_col != "(none)":
                st.session_state.predicates = [
                    {"field": pred_col, "op": op_label_to_op[pred_op_label], "value": float(pred_val)}
                ]
            else:
                st.session_state.predicates = []

            # If a predicate is selected/changed and we already have query tables, regenerate them using the predicate values.
            if st.session_state.query_tables is not None and st.session_state.query_tables_seed is not None:
                cur_sig = pred_signature(st.session_state.predicates)
                if cur_sig != (st.session_state.query_tables_pred_sig or ""):
                    set_query_tables(int(st.session_state.query_tables_seed))

            actions = st.columns([1, 1, 1])
            with actions[0]:
                if st.button("Resubmit (generate new query tables)"):
                    seed = _seed_from_string(edited.to_csv(index=False)) ^ 0x5A5A
                    set_query_tables(seed)
                    st.success("Generated a new batch of query tables from your edits.")

            with actions[1]:
                if st.button("Confirm this query table", type="primary"):
                    st.session_state.confirmed_qt = edited.copy()
                    st.success("Confirmed query table. Proceed to Stage 4 to retrieve join paths.")

            with actions[2]:
                if st.button("Reset disambiguation"):
                    st.session_state.query_tables = None
                    st.session_state.selected_qt_name = None
                    st.session_state.edited_qt = None
                    st.session_state.confirmed_qt = None
                    st.session_state.predicates = []
                    st.session_state.top_paths = None
                    st.session_state.selected_path_id = None
                    st.session_state.query_tables_seed = None
                    st.session_state.query_tables_pred_sig = None
                    st.session_state.qt_editor_version = int(st.session_state.qt_editor_version) + 1
                    st.success("Reset.")
                    st.rerun()


def render_stage_results():
    require_preprocessed()
    if st.session_state.confirmed_qt is None:
        st.warning("Confirm a query table in **Stage 3** first.")
        st.stop()

    params = st.session_state.params
    lake = st.session_state.data_lake
    edges = st.session_state.join_edges
    jpi = st.session_state.join_path_index

    st.subheader("Join path search results")

    qt = st.session_state.confirmed_qt
    with st.container(border=True):
        st.markdown("**Confirmed query table**")
        st.dataframe(qt, use_container_width=True, hide_index=True)

    required_tables = infer_candidate_tables_from_query_table(qt)
    with st.container(border=True):
        st.markdown("**Candidate / required tables (inferred)**")
        st.write(required_tables)

    st.markdown("**Search join paths that contain all candidate tables**")
    topk = int(params["top_k_paths"])
    top = find_top_join_paths(jpi, required_tables, k=topk)
    st.session_state.top_paths = top

    if top.empty:
        st.error("No join paths cover all required tables under the current hyperparameters.")
        st.stop()

    left, right = st.columns([1.05, 1.0], gap="large")
    with left:
        with st.container(border=True):
            st.markdown("**Candidate join paths**")
            st.dataframe(top[["path_id", "tables", "length"]], use_container_width=True, hide_index=True)
            st.session_state.selected_path_id = st.selectbox(
                "Pick a join path",
                options=top["path_id"].tolist(),
                index=0,
            )

    with right:
        pid = st.session_state.selected_path_id
        row = top[top["path_id"] == pid].iloc[0]
        path = [t.strip() for t in row["tables"].split("→")]

        with st.container(border=True):
            st.markdown(f"**Selected:** `{pid}`")
            st.write("**Tables:**", " → ".join(path))
            if st.session_state.predicates:
                st.write("**Predicates:**", st.session_state.predicates)

            st.markdown("**Join path**")
            st.graphviz_chart(graphviz_for_join_path(path, edges), use_container_width=True)

        with st.container(border=True):
            sql = sql_for_path(path, edges)
            st.markdown("**SQL used to materialize**")
            st.code(sql, language="sql")

            out = materialize_path(lake, path, edges, limit=200)
            # Apply predicate if present (operates on output columns if they exist)
            for pred in st.session_state.predicates:
                field = pred["field"]
                candidates = [c for c in out.columns if c.endswith(f".{field}") or c == field]
                if candidates:
                    c = candidates[0]
                    v = float(pred["value"])
                    op = pred.get("op", ">")
                    if op == ">":
                        out = out[out[c] > v]
                    elif op == "<":
                        out = out[out[c] < v]
                    elif op in {"==", "="}:
                        out = out[out[c] == v]

            st.markdown("**Materialized preview**")
            st.dataframe(out.head(50), use_container_width=True, hide_index=True)

            csv_bytes = out.to_csv(index=False).encode("utf-8")
            st.download_button(
                "Download joined table (CSV)",
                data=csv_bytes,
                file_name=f"nldisc_{pid}.csv",
                mime="text/csv",
            )


if __name__ == "__main__":
    main()


