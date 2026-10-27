import pytest

from bob import recipes


def _layout(**over):
    base = {
        "A1": {"sample_id": "s1", "sample_type": "sample", "components": [("medium", "urn:LB", None, None)]},
        "A2": {"sample_id": "s1", "sample_type": "sample", "components": [("medium", "urn:LB", None, None)]},
        "G1": {"sample_id": "h1", "sample_type": "untransformed", "components": [("medium", "urn:LB", None, None)]},
        "H1": {"sample_id": "m1", "sample_type": "medium", "components": [("medium", "urn:LB", None, None)]},
    }
    base.update(over)
    return base


def test_a_fingerprint_is_stable_for_the_same_layout():
    a = recipes.layout_fingerprint(_layout())
    b = recipes.layout_fingerprint(_layout())
    assert a == b and len(a) == 64


def test_moving_a_well_to_another_sample_changes_the_fingerprint():
    moved = _layout(A2={"sample_id": "h1", "sample_type": "untransformed", "components": [("medium", "urn:LB", None, None)]})
    assert recipes.layout_fingerprint(_layout()) != recipes.layout_fingerprint(moved)


def test_changing_an_inducer_dose_changes_the_fingerprint():
    dosed = _layout(A1={"sample_id": "s1", "sample_type": "sample",
                        "components": [("medium", "urn:LB", None, None), ("inducer", "urn:IPTG", 1.0, "mM")]})
    assert recipes.layout_fingerprint(_layout()) != recipes.layout_fingerprint(dosed)


def test_well_order_does_not_change_the_fingerprint():
    d = _layout()
    reordered = {k: d[k] for k in reversed(list(d))}
    assert recipes.layout_fingerprint(d) == recipes.layout_fingerprint(reordered)


def test_every_preset_declares_what_it_needs():
    assert set(recipes.PRESETS) == {
        "growth_curve", "reporter_trajectory", "reporter_per_biomass", "rate_profiles", "mean_over_run"}
    for key, spec in recipes.PRESETS.items():
        assert spec["label"] and spec["measurement"]
        assert isinstance(spec["needs"], tuple)


def test_the_rate_profile_preset_is_not_described_as_the_direct_estimator():
    spec = recipes.PRESETS["rate_profiles"]
    assert "proxy" in spec["measurement"].lower() or "inverse" in spec["measurement"].lower()


def test_reporter_per_biomass_is_never_called_a_production_rate():
    # a negated mention is correct and wanted; what must not appear is the bare claim
    spec = recipes.PRESETS["reporter_per_biomass"]
    m = (spec["measurement"] + " " + spec["caveat"]).lower()
    for phrase in ("production rate", "molecules per cell"):
        if phrase in m:
            denied = f"not a {phrase}" in m or f"not {phrase}" in m
            assert denied, f"{phrase!r} appears without being denied"
    assert "ratio" in m


def test_mean_over_run_names_its_aggregation():
    m = recipes.PRESETS["mean_over_run"]["measurement"].lower()
    assert "arithmetic mean" in m


def test_a_recipe_payload_round_trips():
    cfg = recipes.normalise_config("rate_profiles", {
        "reporter_signal": "YFP", "biomass_signal": "OD600",
        "sample_id": "s1", "biomass_control_id": "m1", "reporter_control_id": "h1",
        "delta": 1.0, "gamma": 0.0, "lam": None})
    assert cfg["preset"] == "rate_profiles"
    assert cfg["sample_id"] == "s1"
    assert "wells" not in cfg, "well identifiers must never be stored in a recipe"
    assert "context_acknowledged" not in cfg, "an acknowledgement must never be stored"


def test_an_unknown_preset_is_refused():
    with pytest.raises(ValueError):
        recipes.normalise_config("dose_response", {})


def test_a_preset_missing_a_required_selection_is_refused():
    with pytest.raises(ValueError, match="biomass"):
        recipes.normalise_config("growth_curve", {"sample_id": "s1"})


def test_reuse_strips_identity_and_acknowledgement():
    cfg = recipes.normalise_config("rate_profiles", {
        "reporter_signal": "YFP", "biomass_signal": "OD600",
        "sample_id": "s1", "biomass_control_id": "m1", "reporter_control_id": "h1"})
    carried = recipes.for_reuse(cfg)
    assert carried["preset"] == "rate_profiles"
    for gone in ("sample_id", "biomass_control_id", "reporter_control_id"):
        assert carried.get(gone) is None, f"{gone} must be re-selected on another assay"
    assert carried["reporter_signal"] == "YFP", "signal roles are offered as a starting point"


def test_markup_is_refused_as_a_preview():
    with pytest.raises(ValueError, match="markup"):
        recipes.normalise_preview("<svg onload=alert(1)></svg>")
    with pytest.raises(ValueError, match="markup"):
        recipes.normalise_preview("  <script>x</script>")


def test_a_preview_accepts_only_bounded_numeric_series():
    ok = recipes.normalise_preview([{"label": "Growth", "x": [0, 1, 2], "y": [0.1, 0.2, None]}])
    import json
    assert json.loads(ok)[0]["label"] == "Growth"
    with pytest.raises(ValueError, match="at most"):
        recipes.normalise_preview([{"x": list(range(100)), "y": list(range(100))}])
    with pytest.raises(ValueError, match="equal-length"):
        recipes.normalise_preview([{"x": [0, 1], "y": [0]}])
    with pytest.raises(ValueError, match="numbers"):
        recipes.normalise_preview([{"x": [0], "y": ["<img onerror=1>"]}])
    assert recipes.normalise_preview(None) == ""


def test_every_preset_asks_the_user_for_the_controls_its_analysis_requires():
    from bob import services
    roles = {"biomass": "biomass_control_id", "reporter": "reporter_control_id"}
    for preset, required in services._PRESET_CONTROLS.items():
        needs = recipes.PRESETS[preset]["needs"]
        for role, key in roles.items():
            assert (role in required) == (key in needs), f"{preset} disagrees about {role} controls"
            channel = f"{role}_signal"
            if role in required:
                assert channel in needs, f"{preset} corrects a {role} channel it never asks for"


def test_rate_profiles_asks_for_both_controls_its_fit_subtracts():
    needs = recipes.PRESETS["rate_profiles"]["needs"]
    assert "biomass_control_id" in needs and "reporter_control_id" in needs


def test_a_mean_over_run_recipe_cannot_be_saved_without_its_reporter_control():
    with pytest.raises(ValueError, match="reporter_control_id"):
        recipes.normalise_config("mean_over_run", {"reporter_signal": "YFP", "sample_id": "s1"})


def test_a_fingerprint_of_resolved_samples_matches_the_plain_rows():
    class C:
        def __init__(self): self.role, self.iri, self.amount, self.unit, self.label = "medium", "urn:LB", None, None, ""

    class S:
        def __init__(self): self.id, self.name, self.sample_type, self.components = "s1", "Reporter", "sample", [C()]

    rows = {"A1": {"sample_id": "s1", "sample_name": "Reporter", "sample_type": "sample",
                   "components": [("medium", "urn:LB", None, None, "")]}}
    assert recipes.source_fingerprint({"A1": S()}) == recipes.layout_fingerprint(rows)
