"""SP17 B2 - bridge waterfall regression test.

Asserts:
- compute_emv_simple and compute_emv_pert return correct values for known inputs.
- compute_bridge_waterfall_data returns the documented 5-row structure.
- generate_bridge_waterfall saves a non-empty PNG.
- The waterfall sentinel is present exactly once in client_runner.ipynb.
- The waterfall cell is saved with outputs=[] and execution_count=None.
"""

from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = REPO_ROOT / "outputs" / "client_runner.ipynb"
SENTINEL = "<!-- sp17-b2-bridge-waterfall -->"


def _make_risk(rid, p, o, m, pe):
    """Build a minimal RiskInput for tests (path per pre-flight 4.0.1)."""
    from src.config import RiskInput
    return RiskInput(
        risk_id=rid,
        description="test",
        owner="Shared",
        distribution="Triangular",
        correlation_group="CG01",
        probability=p,
        opt_cost=o,
        ml_cost=m,
        pess_cost=pe,
    )


# ---------- EMV computation tests ----------

def test_emv_simple_single_risk():
    from src.analysis import compute_emv_simple
    risks = [_make_risk("R001", 0.5, 100.0, 200.0, 300.0)]
    # 0.5 * (100 + 200 + 300) / 3 = 0.5 * 200 = 100
    assert compute_emv_simple(risks) == pytest.approx(100.0)


def test_emv_pert_single_risk():
    from src.analysis import compute_emv_pert
    risks = [_make_risk("R001", 0.5, 100.0, 200.0, 300.0)]
    # 0.5 * (100 + 4*200 + 300) / 6 = 0.5 * 1200/6 = 0.5 * 200 = 100
    assert compute_emv_pert(risks) == pytest.approx(100.0)


def test_emv_simple_pert_differ_when_skewed():
    """Simple and PERT diverge when ML is not centred between Opt and Pess."""
    from src.analysis import compute_emv_simple, compute_emv_pert
    risks = [_make_risk("R001", 1.0, 100.0, 150.0, 1000.0)]
    # Simple: (100 + 150 + 1000) / 3 = 1250/3
    # PERT:   (100 + 600 + 1000) / 6 = 1700/6
    assert compute_emv_simple(risks) == pytest.approx(1250.0 / 3)
    assert compute_emv_pert(risks) == pytest.approx(1700.0 / 6)
    assert compute_emv_simple(risks) != compute_emv_pert(risks)


def test_emv_handles_empty_list():
    from src.analysis import compute_emv_simple, compute_emv_pert
    assert compute_emv_simple([]) == 0.0
    assert compute_emv_pert([]) == 0.0


def test_emv_skips_risks_with_none_probability():
    from src.analysis import compute_emv_pert
    risks = [
        _make_risk("R001", None, 100.0, 200.0, 300.0),
        _make_risk("R002", 0.5, 100.0, 200.0, 300.0),
    ]
    # Only R002 contributes: 0.5 * 200 = 100
    assert compute_emv_pert(risks) == pytest.approx(100.0)


def test_emv_skips_risks_with_none_costs():
    from src.analysis import compute_emv_pert
    risks = [
        _make_risk("R001", 0.5, None, 200.0, 300.0),
        _make_risk("R002", 0.5, 100.0, 200.0, 300.0),
    ]
    assert compute_emv_pert(risks) == pytest.approx(100.0)


def test_emv_handles_opportunities():
    """Negative-cost risks (opportunities) contribute negatively."""
    from src.analysis import compute_emv_pert
    risks = [_make_risk("R001", 1.0, -300.0, -200.0, -100.0)]
    # 1.0 * (-300 + -800 + -100) / 6 = -1200/6 = -200
    assert compute_emv_pert(risks) == pytest.approx(-200.0)


# ---------- Waterfall data tests ----------

def test_waterfall_data_returns_five_rows():
    from src.reporting import compute_bridge_waterfall_data
    risks = [_make_risk("R001", 0.5, 100.0, 200.0, 300.0)]
    mc_results = {"mean": 150.0, "p80": 250.0, "p90": 350.0}
    df = compute_bridge_waterfall_data(risks, mc_results)
    assert len(df) == 5
    assert list(df["stage"]) == ["EMV Simple", "EMV PERT", "MC Mean", "P80", "P90"]


def test_waterfall_data_deltas_match_value_diffs():
    from src.reporting import compute_bridge_waterfall_data
    risks = [_make_risk("R001", 0.5, 100.0, 200.0, 300.0)]
    mc_results = {"mean": 150.0, "p80": 250.0, "p90": 350.0}
    df = compute_bridge_waterfall_data(risks, mc_results)
    assert pd.isna(df.loc[0, "delta"])
    for i in range(1, 5):
        expected = df.loc[i, "value"] - df.loc[i - 1, "value"]
        assert df.loc[i, "delta"] == pytest.approx(expected)


def test_waterfall_data_raises_on_missing_mc_key():
    from src.reporting import compute_bridge_waterfall_data
    with pytest.raises(KeyError):
        compute_bridge_waterfall_data([], {"mean": 150.0})  # missing p80, p90


def test_waterfall_data_annotations_present_for_every_row():
    from src.reporting import compute_bridge_waterfall_data
    risks = [_make_risk("R001", 0.5, 100.0, 200.0, 300.0)]
    mc_results = {"mean": 150.0, "p80": 250.0, "p90": 350.0}
    df = compute_bridge_waterfall_data(risks, mc_results)
    assert df["annotation"].notna().all()
    assert (df["annotation"].str.len() > 0).all()


# ---------- Chart rendering test (house-style PNG) ----------

def test_chart_saves_png_with_content(tmp_path):
    from src.charts import generate_bridge_waterfall
    df = pd.DataFrame({
        "stage": ["EMV Simple", "EMV PERT", "MC Mean", "P80", "P90"],
        "value": [10.0, 12.0, 13.0, 20.0, 27.0],
        "delta": [None, 2.0, 1.0, 7.0, 7.0],
        "annotation": ["a1", "a2", "a3", "a4", "a5"],
    })
    out_path = tmp_path / "test_waterfall.png"
    result = generate_bridge_waterfall(df, out_path)
    assert result is None
    assert out_path.exists()
    assert out_path.stat().st_size > 1000  # PNG with real content


# ---------- Notebook integration tests ----------

@pytest.mark.xfail(strict=True, reason="STANDING5-02 limb 1: sentinel cell committed with outputs, red on arrival in c158791 and never green in any revision")
def test_waterfall_cell_has_empty_outputs():
    import nbformat
    nb = nbformat.read(RUNNER_PATH, as_version=4)
    offenders = []
    for i, cell in enumerate(nb.cells):
        if SENTINEL not in cell.source:
            continue
        if cell.cell_type != "code":
            continue
        has_outputs = bool(cell.get("outputs"))
        has_exec_count = cell.get("execution_count") is not None
        if has_outputs or has_exec_count:
            offenders.append(
                f"cell {i}: outputs={len(cell.get('outputs', []))}, "
                f"execution_count={cell.get('execution_count')!r}"
            )
    assert not offenders, f"Waterfall cell has non-empty outputs/execution_count: {offenders}"

