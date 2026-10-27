import math

import numpy as np
import pytest

from bob import rates

HOUR = 3600.0


def _grid(hours, step_h=0.25, t0_s=0.0):
    n = int(round(hours / step_h)) + 1
    return [t0_s + k * step_h * HOUR for k in range(n)]


def _exp_biomass(times_s, b0=0.1, mu=0.4, t0_s=0.0):
    return [b0 * math.exp(mu * (t - t0_s) / HOUR) for t in times_s]


def _analytic_reporter(times_s, y0=2.0, phi=100.0, b0=0.1, mu=0.4, t0_s=0.0):
    # closed form of dy/dt = phi*B - 0*y for B = b0*exp(mu*t)
    return [y0 + (phi * b0 / mu) * (math.exp(mu * (t - t0_s) / HOUR) - 1.0) for t in times_s]


def test_growth_rate_recovers_a_constant_exponential_rate():
    t = _grid(8.0)
    fit = rates.growth_rate(t, _exp_biomass(t))
    assert fit.converged
    interior = fit.rate[2:-2]
    assert all(abs(r - 0.4) < 0.02 for r in interior), interior


def test_growth_rate_is_reported_per_hour_not_per_second():
    t = _grid(8.0)
    fit = rates.growth_rate(t, _exp_biomass(t))
    assert abs(float(np.mean(fit.rate[2:-2])) - 0.4) < 0.02


def test_a_nonzero_time_origin_does_not_shift_the_rate():
    t = _grid(8.0, t0_s=7200.0)
    fit = rates.growth_rate(t, _exp_biomass(t, t0_s=7200.0))
    assert all(abs(r - 0.4) < 0.02 for r in fit.rate[2:-2])


def test_production_rate_recovers_the_analytic_constant_synthesis():
    t = _grid(8.0)
    b = _exp_biomass(t)
    fit = rates.production_rate(t, _analytic_reporter(t), b)
    assert fit.converged
    interior = fit.rate[2:-2]
    assert all(abs(r - 100.0) < 5.0 for r in interior), interior


def test_production_rate_is_not_the_derivative_of_fluorescence():
    t = _grid(8.0)
    b = _exp_biomass(t)
    y = _analytic_reporter(t)
    fit = rates.production_rate(t, y, b)
    dydt = np.gradient(np.array(y), np.array(t) / HOUR)
    assert abs(float(np.mean(fit.rate[2:-2])) - 100.0) < 5.0
    assert abs(float(np.mean(dydt[2:-2])) - 100.0) > 20.0


def test_production_rate_is_not_the_derivative_of_fluorescence_over_biomass():
    # y0/B0 = 300 exceeds the steady state phi/mu = 250, so y/B falls while synthesis stays positive
    t = _grid(8.0)
    b = _exp_biomass(t)
    y = _analytic_reporter(t, y0=30.0)
    fit = rates.production_rate(t, y, b)
    ratio = np.array(y) / np.array(b)
    dratio = np.gradient(ratio, np.array(t) / HOUR)
    assert float(np.min(dratio)) < -1.0
    assert all(r >= -1e-9 for r in fit.rate)
    assert abs(float(np.mean(fit.rate[2:-2])) - 100.0) < 8.0


def test_production_rate_handles_a_decaying_reporter():
    t = _grid(8.0)
    mu, gamma, phi, b0, y0 = 0.4, 0.3, 100.0, 0.1, 2.0
    b = _exp_biomass(t, b0=b0, mu=mu)
    y = [
        y0 * math.exp(-gamma * tt / HOUR)
        + phi * b0 / (mu + gamma) * (math.exp(mu * tt / HOUR) - math.exp(-gamma * tt / HOUR))
        for tt in t
    ]
    fit = rates.production_rate(t, y, b, gamma=gamma)
    assert all(abs(r - phi) < 8.0 for r in fit.rate[2:-2])
    # the fitted curve must track the analytic reporter, which a wrong initial-condition
    # decay term breaks even when the interior rate still looks plausible
    scale = max(abs(v) for v in y)
    assert max(abs(f - o) for f, o in zip(fit.fitted, y)) < 0.02 * scale
    assert abs(fit.fitted[0] - y0) < 0.25


def test_zero_synthesis_gives_zero_and_never_negative():
    t = _grid(8.0)
    b = _exp_biomass(t)
    fit = rates.production_rate(t, [2.0] * len(t), b)
    assert all(r >= -1e-9 for r in fit.rate)
    assert all(r < 1.0 for r in fit.rate[2:-2])


def test_stationary_biomass_gives_near_zero_growth():
    t = _grid(8.0)
    fit = rates.growth_rate(t, [0.4] * len(t))
    assert all(abs(r) < 0.02 for r in fit.rate[2:-2])


def test_an_irregular_time_grid_is_accepted():
    t = [k * 0.25 * HOUR for k in range(0, 12)] + [3.0 * HOUR + k * 0.5 * HOUR for k in range(1, 11)]
    fit = rates.growth_rate(t, _exp_biomass(t))
    assert all(abs(r - 0.4) < 0.03 for r in fit.rate[2:-2])


def test_missing_readings_are_dropped_not_treated_as_zero():
    t = _grid(8.0)
    b = _exp_biomass(t)
    holed = list(b)
    holed[5] = None
    holed[11] = None
    fit = rates.growth_rate(t, holed)
    assert all(abs(r - 0.4) < 0.03 for r in fit.rate[2:-2])


def test_negative_background_corrected_readings_are_kept_in_the_residual():
    t = _grid(8.0)
    b = _exp_biomass(t)
    y = _analytic_reporter(t)
    y[1] = -0.5
    fit = rates.production_rate(t, y, b)
    assert fit.diagnostics["observations_used"] == len(t)


def test_mismatched_timestamp_lengths_are_refused():
    t = _grid(8.0)
    with pytest.raises(ValueError):
        rates.growth_rate(t, _exp_biomass(t)[:-3])


def test_too_few_informative_points_are_refused():
    with pytest.raises(ValueError):
        rates.growth_rate([0.0, 900.0], [0.1, 0.11])


def test_all_missing_biomass_is_refused():
    t = _grid(8.0)
    with pytest.raises(ValueError):
        rates.growth_rate(t, [None] * len(t))


def test_delta_below_the_sampling_interval_is_refused():
    # a delta under the sampling interval always asks for more basis functions than there are
    # observations, so it is underdetermined rather than merely imprecise
    t = _grid(8.0, step_h=0.5)
    with pytest.raises(ValueError, match="cannot determine"):
        rates.growth_rate(t, _exp_biomass(t), delta=0.25)


def test_an_underdetermined_four_point_fit_is_refused():
    with pytest.raises(ValueError, match="cannot determine"):
        rates.growth_rate([0.0, 7200.0, 14400.0, 21600.0], [0.1, 0.2, 0.3, 0.4])


def test_biomass_with_no_positive_reading_is_refused():
    t = _grid(8.0)
    with pytest.raises(ValueError, match="no positive readings"):
        rates.growth_rate(t, [-0.1] * len(t))
    with pytest.raises(ValueError, match="no positive readings"):
        rates.growth_rate(t, [0.0] * len(t))


def test_an_isolated_negative_reading_still_fits():
    t = _grid(8.0)
    b = _exp_biomass(t)
    b[3] = -0.01
    fit = rates.growth_rate(t, b)
    assert fit.converged
    assert fit.diagnostics["observations_used"] == len(t)


def test_a_tiny_delta_is_refused_before_allocating():
    t = _grid(8.0)
    with pytest.raises(ValueError):
        rates.growth_rate(t, _exp_biomass(t), delta=1e-6)


def test_non_finite_inputs_are_refused():
    t = _grid(8.0)
    b = _exp_biomass(t)
    b[4] = float("nan")
    with pytest.raises(ValueError, match="not finite"):
        rates.growth_rate(t, b)


def test_bad_hyperparameters_are_refused():
    t = _grid(8.0)
    b = _exp_biomass(t)
    for kwargs in ({"delta": 0.0}, {"delta": float("inf")}, {"lam": -1.0}):
        with pytest.raises(ValueError):
            rates.growth_rate(t, b, **kwargs)
    with pytest.raises(ValueError):
        rates.production_rate(t, _analytic_reporter(t), b, gamma=-0.5)


def test_missing_biomass_at_the_run_edges_is_refused_not_extrapolated():
    t = _grid(8.0)
    b = _exp_biomass(t)
    y = _analytic_reporter(t)
    b[0] = None
    with pytest.raises(ValueError, match="extrapolate"):
        rates.production_rate(t, y, b)


def test_solver_nonconvergence_is_propagated(monkeypatch):
    real = rates.least_squares

    def flaky(*a, **k):
        out = real(*a, **k)
        out.success = False
        out.status = 0
        out.message = "maximum number of function evaluations exceeded"
        return out

    monkeypatch.setattr(rates, "least_squares", flaky)
    t = _grid(8.0)
    fit = rates.growth_rate(t, _exp_biomass(t), lam=1e-6)
    assert fit.converged is False
    assert fit.diagnostics["converged"] is False
    assert "maximum number" in fit.diagnostics["solver_message"]


def test_a_near_flat_noisy_series_does_not_invent_growth():
    rng = np.random.default_rng(20261020)
    t = _grid(8.0)
    b = [0.4 + float(rng.normal(0.0, 0.004)) for _ in t]
    fit = rates.growth_rate(t, b)
    assert fit.converged
    assert abs(fit.fitted[0] - 0.4) < 0.06, fit.fitted[0]
    assert all(abs(r) < 0.05 for r in fit.rate[2:-2]), max(abs(r) for r in fit.rate[2:-2])


def test_the_gaussian_basis_uses_delta_as_published():
    t = np.array([0.0, 1.0, 2.0])
    g = rates.gaussian_basis(t, delta=1.0, n=3)
    assert abs(g[0, 0] - 1.0) < 1e-12
    assert abs(g[1, 0] - math.exp(-0.5)) < 1e-12
    assert abs(g[2, 0] - math.exp(-2.0)) < 1e-12


def test_the_basis_denominator_is_two_delta_not_two_delta_squared():
    # at delta=1 both forms give 2, so only delta != 1 can tell them apart
    g = rates.gaussian_basis(np.array([1.0]), delta=0.5, n=1)
    assert abs(g[0, 0] - math.exp(-1.0)) < 1e-12
    assert abs(g[0, 0] - math.exp(-2.0)) > 0.1


def test_lambda_selection_records_its_scan():
    t = _grid(8.0)
    fit = rates.growth_rate(t, _exp_biomass(t))
    d = fit.diagnostics
    assert len(d["lambda_scan"]) >= 5
    assert d["lambda_selected"] in [p["lam"] for p in d["lambda_scan"]]
    assert "lambda_at_scan_boundary" in d


def test_the_linear_reporter_solve_matches_a_nonlinear_solve():
    t = _grid(6.0)
    b = _exp_biomass(t)
    y = _analytic_reporter(t)
    lin = rates.production_rate(t, y, b, lam=1e-3)
    non = rates.production_rate(t, y, b, lam=1e-3, _force_nonlinear=True)
    assert max(abs(a - c) for a, c in zip(lin.rate, non.rate)) < 1.0


def test_finer_quadrature_does_not_move_the_answer():
    t = _grid(6.0)
    b = _exp_biomass(t)
    y = _analytic_reporter(t)
    coarse = rates.production_rate(t, y, b, lam=1e-3, quadrature_refinement=1)
    fine = rates.production_rate(t, y, b, lam=1e-3, quadrature_refinement=8)
    assert max(abs(a - c) for a, c in zip(coarse.rate, fine.rate)) < 2.0


def test_a_decay_dominated_reporter_pins_the_initial_condition_term():
    # y0 dominates and phi is small, so a wrong exp(-gamma*t) on the initial-condition column
    # changes the fitted curve instead of hiding under the synthesis signal
    t = _grid(8.0)
    mu, gamma, phi, b0, y0 = 0.1, 0.8, 5.0, 0.02, 300.0
    b = _exp_biomass(t, b0=b0, mu=mu)
    y = [
        y0 * math.exp(-gamma * tt / HOUR)
        + phi * b0 / (mu + gamma) * (math.exp(mu * tt / HOUR) - math.exp(-gamma * tt / HOUR))
        for tt in t
    ]
    fit = rates.production_rate(t, y, b, gamma=gamma)
    scale = max(abs(v) for v in y)
    assert max(abs(f - o) for f, o in zip(fit.fitted, y)) < 0.02 * scale


def test_the_tikhonov_penalty_is_applied_as_sqrt_lambda_in_the_residual():
    # the reporter fit is linear in [y0, phi], so the regularised solution must equal the
    # closed-form ridge estimate for the stated objective when no bound is active
    t = _grid(6.0)
    b = _exp_biomass(t)
    y = _analytic_reporter(t)
    lam = 0.5
    fit = rates.production_rate(t, y, b, lam=lam)

    th = (np.array(t) - t[0]) / HOUR
    n = len(fit.basis_centers)
    conv = rates._convolution(th, np.array(b), np.ones(len(t), dtype=bool), 1.0, n, 0.0, 4)
    A = np.column_stack([np.ones(len(t)), conv])
    ridge = np.linalg.solve(A.T @ A + lam * np.eye(n + 1), A.T @ np.array(y))
    assert np.all(ridge >= -1e-9), "fixture must keep the bounds inactive for this comparison"

    design = rates.gaussian_basis(th, 1.0, n)
    expected = design @ ridge[1:]
    assert max(abs(a - c) for a, c in zip(fit.rate, expected)) < 1e-6


def test_the_growth_penalty_matches_an_independently_built_objective():
    # the growth fit is nonlinear, so the objective ||B - F(theta)||^2 + lam*||theta||^2 is
    # rebuilt here from scratch; using lam instead of sqrt(lam) in the residual changes the answer
    from scipy.optimize import least_squares as ls

    t = _grid(6.0)
    b = _exp_biomass(t)
    lam = 4.0
    fit = rates.growth_rate(t, b, lam=lam)

    th = (np.array(t) - t[0]) / HOUR
    n = len(fit.basis_centers)
    integral = rates._basis_integral(th, 1.0, n)
    obs = np.array(b)

    def resid(theta):
        return np.concatenate([theta[0] * np.exp(integral @ theta[1:]) - obs, math.sqrt(lam) * theta])

    x0 = np.concatenate([[obs[0]], np.full(n, 0.1)])
    mine = ls(resid, x0, bounds=(np.zeros(n + 1), np.full(n + 1, np.inf)), method="trf").x
    expected = rates.gaussian_basis(th, 1.0, n) @ mine[1:]
    assert max(abs(a - c) for a, c in zip(fit.rate, expected)) < 1e-4


def test_the_near_exact_shortcut_is_labelled_a_heuristic():
    t = _grid(8.0)
    fit = rates.growth_rate(t, [0.4] * len(t))
    d = fit.diagnostics
    assert d["lambda_selection_rule"] == "near-exact-residual-heuristic"
    assert d["lambda_selection_rule_is_heuristic"] is True
    assert d["near_exact_residual_relative_threshold"] == rates.NEAR_EXACT_RESIDUAL_REL


def test_curvature_uses_actual_log_lambda_spacing_when_candidates_drop_out(monkeypatch):
    # fail a contiguous block and one isolated candidate so the surviving log-lambda grid has
    # genuinely uneven gaps; dropping alternate points would leave it uniform and prove nothing
    real = rates.least_squares
    failed_indices = {3, 4, 5, 6, 11, 17}
    seen = {"n": -1}

    def patchy(*a, **k):
        out = real(*a, **k)
        seen["n"] += 1
        if seen["n"] in failed_indices:
            out.success = False
            out.message = "injected failure"
        return out

    rng = np.random.default_rng(7)
    t = _grid(8.0)
    b = [0.05 * math.exp(0.35 * tt / HOUR) * (1.0 + float(rng.normal(0, 0.05))) for tt in t]
    monkeypatch.setattr(rates, "least_squares", patchy)
    fit = rates.growth_rate(t, b)

    scan = fit.diagnostics["lambda_scan"]
    usable = [p for p in scan if p["converged"]]
    assert any(not p["converged"] for p in scan)
    gaps = np.diff(np.log10([p["lam"] for p in usable]))
    assert float(gaps.max()) > 1.5 * float(gaps.min()), f"spacing is still even: {gaps}"

    if fit.diagnostics["lambda_selection_rule"] == "l-curve-corner":
        u = np.log10([p["lam"] for p in usable])
        x = np.log10([p["residual_norm"] + 1e-300 for p in usable])
        y = np.log10([p["parameter_norm"] + 1e-300 for p in usable])
        x1, y1 = np.gradient(x, u), np.gradient(y, u)
        x2, y2 = np.gradient(x1, u), np.gradient(y1, u)
        denom = (x1 ** 2 + y1 ** 2) ** 1.5
        curv = np.where(denom > 1e-18, np.abs(x1 * y2 - y1 * x2) / np.where(denom > 1e-18, denom, 1.0), -np.inf)
        curv[0] = curv[-1] = -np.inf
        assert fit.diagnostics["lambda_selected"] == usable[int(np.argmax(curv))]["lam"]
    else:
        assert fit.diagnostics["lambda_selected"] in [p["lam"] for p in usable]
