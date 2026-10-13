"""DELIVFIX-01 / FW-28: the schedule S-curve names the product as it is, and every curve shows.

Found by the Director reading the report, 22/09/2026. The legend read *"DP Review baseline
(current strawman state)"* - the strawman stopped being a separate workbook, and the Mode
classification is the register's own. The title read *"three Mode scenarios"* over a Stage 3
headline that applies no Mode multiplier. And on wind the DP Review curve could not be seen: the
comparators were drawn faded UNDER the headline, where a coincident one vanishes. The value labels
sat on the curve they label.

"Mode classification" is not the replacement: it is on the SR9 v3.3 Path A list of phrases no
chart legend may carry (``test_sr9_v35_narrative_data_driven``, and the PNG OCR test).
"""
from unittest import mock

import matplotlib.pyplot as plt
import numpy as np
import pytest
from matplotlib.text import Annotation

from src.final import charts
from src.final.executive_summary import format_scenario_label

OLD = "strawman state"


def test_no_scenario_label_names_the_strawman():
    for scenario in ("DP_Review", "Dummy_Realistic", "All_Series"):
        for variant in (None, "Series", "Hybrid", "Parallel"):
            label = format_scenario_label(scenario, variant=variant)
            assert OLD not in label.lower(), label
    assert format_scenario_label("DP_Review") == "DP Review baseline (Mode as registered)"


def test_the_mode_sensitivity_table_names_no_strawman():
    import pandas as pd

    from src.final.sections.schedule_drivers import build_mode_sensitivity_summary

    cf = pd.DataFrame([
        {"scenario_name": n, "mc_mean_days": m, "mc_p50_days": m, "mc_p80_days": m + 5}
        for n, m in (("Baseline (DP Review)", 30.0), ("All Series", 32.0),
                     ("All Hybrid", 20.0), ("All Parallel", 0.0))])
    for variant in (None, "Series"):
        out = build_mode_sensitivity_summary(cf, strawman_variant=variant)
        text = " ".join(out["table"]["Scenario"]) + " " + out["orienting"]
        assert OLD not in text.lower() and "strawman builder" not in text.lower(), text


def _render(tmp_path, distributions, headline):
    captured = {}
    orig_close = plt.close

    def _capture(fig):
        if hasattr(fig, "axes") and fig.axes:
            ax = fig.axes[0]
            captured["curves"] = {ln.get_label(): (ln.get_linestyle(), ln.get_zorder())
                                  for ln in ax.lines if len(ln.get_xdata()) > 2}
            captured["legend"] = [t.get_text() for t in ax.get_legend().get_texts()]
            captured["labels"] = [t.get_ha() for t in ax.texts if isinstance(t, Annotation)]
        orig_close(fig)

    with mock.patch("matplotlib.pyplot.close", side_effect=_capture):
        charts.make_s_curve(distributions=distributions, percentile_markers=[50, 80, 90, 95],
                            title="t", output_path=tmp_path / "s.png", headline_label=headline,
                            value_label_fmt="{value:.1f}d")
    return captured


def test_comparators_are_dashed_and_drawn_above_the_headline(tmp_path):
    rng = np.random.default_rng(3)
    head = "Stage 3 — headline"
    c = _render(tmp_path, {"A": rng.exponential(20, 2000), "B": rng.exponential(21, 2000),
                           head: rng.exponential(20, 2000)}, head)
    head_style, head_z = c["curves"][head]
    for name in ("A", "B"):
        style, z = c["curves"][name]
        assert style != "-", f"comparator {name} is solid, so it disappears under the headline"
        assert z > head_z, f"comparator {name} is drawn under the headline"
    assert c["curves"]["A"][0] != c["curves"]["B"][0], "two comparators share one dash pattern"


def test_identical_comparators_share_one_legend_entry(tmp_path):
    rng = np.random.default_rng(4)
    same = rng.exponential(20, 2000)
    head = "Stage 3 — headline"
    c = _render(tmp_path, {"All Series": same, "DP Review": same.copy(),
                           head: rng.exponential(19, 2000)}, head)
    assert c["legend"] == [head, "All Series = DP Review"], c["legend"]


def test_value_labels_sit_left_of_the_curve(tmp_path):
    rng = np.random.default_rng(5)
    head = "Stage 3 — headline"
    c = _render(tmp_path, {head: rng.exponential(20, 2000)}, head)
    assert c["labels"] == ["right"] * 4, "a label anchored left of its text sits on the curve"


@pytest.mark.slow
def test_a_stage3_led_report_titles_its_s_curve_for_the_stage3_headline(tmp_path):
    """The title is chosen in the composer from whether Stage 3 leads, so it needs a real compose."""
    from scripts.inventory_composed_keys import compose_one
    from src.final import composer

    titles = []
    real = composer.make_s_curve

    def spy(*args, **kwargs):
        titles.append(kwargs.get("title"))
        return real(*args, **kwargs)

    with mock.patch.object(composer, "make_s_curve", side_effect=spy):
        compose_one("synthetic_wind", "synthetic_wind", "wind", tmp_path)
    schedule = [t for t in titles if t and t.startswith("Schedule slip S-curve")]
    # Composed more than once per deliverable (the summary and the standalone); every one must read so.
    assert schedule and set(schedule) == {"Schedule slip S-curve - Stage 3 headline, with Mode comparators"}, titles
