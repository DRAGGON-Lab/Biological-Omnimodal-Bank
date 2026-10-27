"""Growth and reporter production rate profiles by the published Gaussian-basis inverse method."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import least_squares, lsq_linear
from scipy.special import erf

HOUR = 3600.0
METHOD = "gaussian-basis-inverse"
METHOD_VERSION = "1"
MAX_BASIS = 512
NEAR_EXACT_RESIDUAL_REL = 1e-3

Series = list[float | None]


@dataclass
class RateFit:
    times: list[float]
    rate: list[float]
    fitted: list[float]
    basis_centers: list[float]
    lam: float
    converged: bool
    diagnostics: dict = field(default_factory=dict)


def _hours(times_s: list[float]) -> np.ndarray:
    t = np.asarray(times_s, dtype=float)
    if t.ndim != 1 or t.size == 0:
        raise ValueError("times must be a non-empty one-dimensional series")
    if not np.all(np.isfinite(t)):
        raise ValueError("times contain non-finite values")
    if np.any(np.diff(t) <= 0):
        raise ValueError("times must be strictly increasing")
    # stored times are seconds since the run started; the method is defined in hours
    return (t - t[0]) / HOUR


def _observed(values: Series, n: int, *, positive: bool = False) -> tuple[np.ndarray, np.ndarray]:
    if len(values) != n:
        raise ValueError(f"expected {n} readings to match the timestamps, got {len(values)}")
    missing = sum(1 for x in values if x is None)
    v = np.array([np.nan if x is None else float(x) for x in values], dtype=float)
    nonfinite = int(np.sum(~np.isfinite(v))) - missing
    if nonfinite > 0:
        raise ValueError(f"{nonfinite} reading(s) are not finite; missing readings must be None")
    mask = np.isfinite(v)
    if mask.sum() < 4:
        raise ValueError("at least four informative readings are required")
    # a negative reading inside a real run stays in the residual, but a series with no positive
    # value carries no biomass signal at all and must not be fitted
    if positive and not np.any(v[mask] > 0):
        raise ValueError("biomass series contains no positive readings")
    return v, mask


def _check_hyperparameters(delta: float, lam: float | None, gamma: float | None) -> None:
    if not math.isfinite(delta) or delta <= 0:
        raise ValueError("delta must be a finite positive number of hours")
    if lam is not None and (not math.isfinite(lam) or lam < 0):
        raise ValueError("lambda must be finite and non-negative")
    if gamma is not None and (not math.isfinite(gamma) or gamma < 0):
        raise ValueError("gamma must be finite and non-negative")


def gaussian_basis(times_h: np.ndarray, delta: float, n: int) -> np.ndarray:
    """Eq 5 as published: delta is both the centre spacing and the variance, so the denominator is 2*delta."""
    t = np.asarray(times_h, dtype=float)
    centers = delta * np.arange(n)
    return np.exp(-((t[:, None] - centers[None, :]) ** 2) / (2.0 * delta))


def _basis_integral(times_h: np.ndarray, delta: float, n: int) -> np.ndarray:
    centers = delta * np.arange(n)
    s = math.sqrt(2.0 * delta)
    scale = math.sqrt(math.pi * delta / 2.0)
    upper = erf((times_h[:, None] - centers[None, :]) / s)
    lower = erf((times_h[0] - centers[None, :]) / s)
    return scale * (upper - lower)


def _basis_count(times_h: np.ndarray, delta: float, observations: int) -> int:
    span = float(times_h[-1] - times_h[0])
    wanted = max(2, int(math.floor(span / delta)) + 2)
    if wanted > MAX_BASIS:
        raise ValueError(f"delta={delta} h over a {span:.2f} h run needs {wanted} basis functions, above the {MAX_BASIS} limit")
    if wanted + 1 > observations:
        raise ValueError(f"{observations} informative readings cannot determine {wanted + 1} parameters; use a larger delta or a longer run")
    return wanted


def _l_curve(solve, lams: np.ndarray, scale: float) -> tuple[float, list[dict], bool, str]:
    scan = []
    for lam in lams:
        theta, resid, ok, status, message = solve(lam)
        scan.append({"lam": float(lam), "residual_norm": float(resid),
                     "parameter_norm": float(np.linalg.norm(theta)),
                     "converged": bool(ok), "status": status, "message": message})
    usable = [p for p in scan if p["converged"]]
    if not usable:
        raise ValueError("no regularisation candidate converged")
    scan_all, scan = scan, usable
    lams = np.array([p["lam"] for p in scan])
    # heuristic, not from the paper: a fit this close to the data leaves no visible corner, and
    # the published objective penalises the initial state, so a large lambda would bias it
    floor = max(1e-12, NEAR_EXACT_RESIDUAL_REL * scale)
    exact = [p for p in scan if p["residual_norm"] <= floor]
    if exact:
        return float(min(p["lam"] for p in exact)), scan_all, True, "near-exact-residual-heuristic"
    x = np.log10([p["residual_norm"] + 1e-300 for p in scan])
    y = np.log10([p["parameter_norm"] + 1e-300 for p in scan])
    if len(scan) < 3 or np.allclose(x, x[0]) or np.allclose(y, y[0]):
        return float(lams[len(lams) // 2]), scan_all, True, "degenerate-curve-midpoint"
    # dropping non-converged candidates leaves the surviving log-lambda spacing uneven, so the
    # derivatives are taken against the actual coordinate rather than against the index
    u = np.log10(lams)
    x1, y1 = np.gradient(x, u), np.gradient(y, u)
    x2, y2 = np.gradient(x1, u), np.gradient(y1, u)
    denom = (x1 ** 2 + y1 ** 2) ** 1.5
    curvature = np.where(denom > 1e-18, np.abs(x1 * y2 - y1 * x2) / np.where(denom > 1e-18, denom, 1.0), -np.inf)
    curvature[0] = curvature[-1] = -np.inf
    k = int(np.argmax(curvature))
    degenerate = not np.isfinite(curvature[k])
    return float(lams[k]), scan_all, degenerate, "l-curve-corner"


def _diagnostics(times_h, delta, n_basis, mask, lam, scan, degenerate, lams, rule="l-curve-corner") -> dict:
    gaps = np.diff(times_h)
    return {
        "method": METHOD,
        "method_version": METHOD_VERSION,
        "time_unit": "h",
        "delta_h": float(delta),
        "basis_count": int(n_basis),
        "observations_used": int(mask.sum()),
        "observations_total": int(mask.size),
        "sampling_interval_median_h": float(np.median(gaps)) if gaps.size else 0.0,
        "sampling_interval_max_h": float(np.max(gaps)) if gaps.size else 0.0,
        "delta_below_sampling_interval": bool(delta < np.max(gaps)) if gaps.size else False,
        "basis_exceeds_observations": bool(n_basis > mask.sum()),
        "lambda_selected": float(lam),
        "lambda_scan": scan,
        "lambda_degenerate": bool(degenerate),
        "lambda_selection_rule": rule,
        "lambda_selection_rule_is_heuristic": rule == "near-exact-residual-heuristic",
        "near_exact_residual_relative_threshold": NEAR_EXACT_RESIDUAL_REL,
        "lambda_at_scan_boundary": bool(scan and lam in (scan[0]["lam"], scan[-1]["lam"])),
        "centre_coverage_h": [0.0, float(delta * (n_basis - 1))],
        "support_h": [float(times_h[0]), float(times_h[-1])],
    }


def growth_rate(times_s, biomass: Series, delta: float = 1.0, lam: float | None = None) -> RateFit:
    th = _hours(times_s)
    b, mask = _observed(biomass, th.size, positive=True)
    _check_hyperparameters(delta, lam, None)
    n = _basis_count(th, delta, int(mask.sum()))
    integral = _basis_integral(th, delta, n)
    design = gaussian_basis(th, delta, n)
    tm, bm, im = th[mask], b[mask], integral[mask]
    mask_pos = bm > 0

    def model(theta):
        return theta[0] * np.exp(im @ theta[1:])

    def solve(l):
        root = math.sqrt(l)

        def resid(theta):
            return np.concatenate([model(theta) - bm, root * theta])

        x0 = np.concatenate([[max(bm[mask_pos][0] if mask_pos.any() else 1e-9, 1e-9)], np.full(n, 0.1)])
        out = least_squares(resid, x0, bounds=(np.zeros(n + 1), np.full(n + 1, np.inf)), method="trf")
        return (out.x, float(np.linalg.norm(model(out.x) - bm)),
                bool(getattr(out, "success", False)), int(getattr(out, "status", -99)), str(getattr(out, "message", "")))

    lams = np.logspace(-8, 2, 21)
    if lam is None:
        lam, scan, degenerate, rule = _l_curve(solve, lams, float(np.linalg.norm(bm)))
    else:
        scan, degenerate, rule = [], False, "explicit"
    theta, _, ok, status, message = solve(lam)
    diag = _diagnostics(th, delta, n, mask, lam, scan, degenerate, lams, rule)
    diag["converged"] = bool(ok)
    diag["solver_status"] = status
    diag["solver_message"] = message
    return RateFit(
        times=th.tolist(),
        rate=(design @ theta[1:]).tolist(),
        fitted=(theta[0] * np.exp(integral @ theta[1:])).tolist(),
        basis_centers=(delta * np.arange(n)).tolist(),
        lam=float(lam),
        converged=bool(ok),
        diagnostics=diag,
    )


def _convolution(th: np.ndarray, biomass: np.ndarray, bmask: np.ndarray, delta: float, n: int,
                 gamma: float, refinement: int) -> np.ndarray:
    """Integral of exp(-gamma*(t-s)) * Bbar(s) * G_k(s) ds, with Bbar linearly interpolated between readings."""
    known_t, known_b = th[bmask], biomass[bmask]
    if th[0] < known_t[0] - 1e-12 or th[-1] > known_t[-1] + 1e-12:
        raise ValueError("biomass is missing at the start or end of the run; refusing to extrapolate it")
    out = np.zeros((th.size, n))
    acc = np.zeros(n)
    for i in range(1, th.size):
        a, c = th[i - 1], th[i]
        grid = np.linspace(a, c, refinement + 1)
        bb = np.interp(grid, known_t, known_b)
        gg = gaussian_basis(grid, delta, n)
        f = bb[:, None] * gg * np.exp(gamma * (grid[:, None] - th[0]))
        seg = np.trapezoid(f, grid, axis=0) if hasattr(np, "trapezoid") else np.trapz(f, grid, axis=0)
        acc = acc + seg
        out[i] = acc
    return out * np.exp(-gamma * (th[:, None] - th[0]))


def production_rate(times_s, reporter: Series, biomass: Series, gamma: float = 0.0,
                    delta: float = 1.0, lam: float | None = None,
                    quadrature_refinement: int = 4, _force_nonlinear: bool = False) -> RateFit:
    th = _hours(times_s)
    y, ymask = _observed(reporter, th.size)
    b, bmask = _observed(biomass, th.size, positive=True)
    _check_hyperparameters(delta, lam, gamma)
    n = _basis_count(th, delta, int(ymask.sum()))
    conv = _convolution(th, b, bmask, delta, n, gamma, max(1, quadrature_refinement))
    decay = np.exp(-gamma * (th - th[0]))
    # for fixed biomass and gamma the reporter model is linear in [y0, phi]
    full = np.column_stack([decay, conv])
    design = gaussian_basis(th, delta, n)
    A, obs = full[ymask], y[ymask]

    def solve(l):
        root = math.sqrt(l)
        aug = np.vstack([A, root * np.eye(n + 1)])
        rhs = np.concatenate([obs, np.zeros(n + 1)])
        if _force_nonlinear:
            def resid(theta):
                return np.concatenate([A @ theta - obs, root * theta])
            out = least_squares(resid, np.full(n + 1, 1e-6),
                                bounds=(np.zeros(n + 1), np.full(n + 1, np.inf)), method="trf")
        else:
            out = lsq_linear(aug, rhs, bounds=(0.0, np.inf), method="trf")
        theta = out.x
        return (theta, float(np.linalg.norm(A @ theta - obs)),
                bool(getattr(out, "success", False)), int(getattr(out, "status", -99)), str(getattr(out, "message", "")))

    lams = np.logspace(-8, 2, 21)
    if lam is None:
        lam, scan, degenerate, rule = _l_curve(solve, lams, float(np.linalg.norm(obs)))
    else:
        scan, degenerate, rule = [], False, "explicit"
    theta, _, ok, status, message = solve(lam)
    diag = _diagnostics(th, delta, n, ymask, lam, scan, degenerate, lams, rule)
    diag["solver_status"] = status
    diag["solver_message"] = message
    diag["gamma_per_h"] = float(gamma)
    diag["quadrature_refinement"] = int(max(1, quadrature_refinement))
    diag["biomass_observations_used"] = int(bmask.sum())
    diag["converged"] = bool(ok)
    return RateFit(
        times=th.tolist(),
        rate=(design @ theta[1:]).tolist(),
        fitted=(full @ theta).tolist(),
        basis_centers=(delta * np.arange(n)).tolist(),
        lam=float(lam),
        converged=bool(ok),
        diagnostics=diag,
    )
