"""Background correction, mean expression, and replicate statistics.

Series are per well and aligned to one time vector per signal, which is how a kinetic plate read
arrives. Missing readings are None and propagate as None rather than as zero.
"""

import bisect
import statistics
from dataclasses import dataclass

Series = list[float | None]


@dataclass
class Correction:
    times: list[float]
    corrected: dict[str, Series]
    background: Series
    background_sd: Series
    below_threshold: dict[str, list[bool]]
    control_positions: list[str]


def _snap(value: float, values: list[float]) -> float:
    """Zero a mean that is zero up to float rounding, such as controls corrected against themselves."""
    scale = max((abs(v) for v in values), default=0.0)
    return 0.0 if abs(value) <= 1e-9 * max(scale, 1e-300) else value


def _mean_sd(values: list[float]) -> tuple[float | None, float | None]:
    if not values:
        return None, None
    if len(values) == 1:
        # a sample standard deviation is not estimable from one observation; zero would assert
        # a precision nothing measured
        return values[0], None
    return _snap(statistics.fmean(values), values), statistics.stdev(values)


def background_correct(
    times: list[float],
    values: dict[str, Series],
    control_positions: list[str],
    threshold_sd: float = 2.0,
    drop_below: bool = False,
) -> Correction:
    """Subtract the mean control signal at each time point.

    A corrected point counts as indistinguishable from background when it lies at or below
    `threshold_sd` standard deviations of the controls at that time point. The tolerance keeps a
    reading equal to the background from escaping the flag through float rounding in the mean.
    """
    controls = [p for p in control_positions if p in values]
    background: Series = []
    background_sd: Series = []
    for k in range(len(times)):
        mean, sd = _mean_sd([values[p][k] for p in controls if values[p][k] is not None])
        background.append(mean)
        background_sd.append(sd)

    corrected: dict[str, Series] = {}
    below: dict[str, list[bool]] = {}
    for pos, series in values.items():
        out: Series = []
        flags: list[bool] = []
        for k, v in enumerate(series):
            bg, sd = background[k], background_sd[k]
            if v is None or bg is None:
                out.append(None)
                flags.append(False)
                continue
            c = v - bg
            is_below = c <= threshold_sd * (sd or 0.0) + 1e-9 * max(abs(bg), 1.0)
            flags.append(is_below)
            out.append(None if (drop_below and is_below) else c)
        corrected[pos] = out
        below[pos] = flags
    return Correction(times, corrected, background, background_sd, below, controls)


def align(times_from: list[float], series: Series, times_to: list[float]) -> Series:
    """Resample `series` onto `times_to` by nearest reading; equal lengths align by cycle index."""
    if not times_from or not series:
        return [None] * len(times_to)
    if len(times_from) == len(times_to):
        return list(series)
    order = sorted(range(len(times_from)), key=times_from.__getitem__)
    sorted_times = [times_from[i] for i in order]
    out: Series = []
    for t in times_to:
        j = bisect.bisect_left(sorted_times, t)
        candidates = [c for c in (j - 1, j) if 0 <= c < len(sorted_times)]
        best = min(candidates, key=lambda c: abs(sorted_times[c] - t))
        out.append(series[order[best]] if order[best] < len(series) else None)
    return out


def resample_onto(times_from: list[float], series: Series, times_to: list[float]) -> tuple[Series, list[str]]:
    """Resample conservatively, and say for each target time how its value was obtained.

    Equal array lengths are not equal acquisition times, so this never pairs by index. A target
    time that coincides with a source timestamp takes that reading, even if it is the only one. A
    target time between two source timestamps is interpolated only when both of them were read: a
    missing endpoint leaves the result missing rather than letting the line span the gap. Outside
    the source grid the result is missing, never extrapolated.

    The second return value holds one reason per target time: ``matched``, ``interpolated``,
    ``missing_outside_support``, ``missing_source_reading`` (the coinciding reading is missing) or
    ``missing_bracket_reading`` (an endpoint of the surrounding interval is missing).
    """
    if len(times_from) != len(series):
        raise ValueError(f"the time vector has {len(times_from)} points and the series has {len(series)}")
    for t in times_from:
        if t is None or t != t or t in (float("inf"), float("-inf")):
            raise ValueError("the source time vector holds a value that is not a finite number")
    if any(b <= a for a, b in zip(times_from, times_from[1:])):
        raise ValueError("the source time vector is not strictly increasing, so it cannot be interpolated")

    out: Series = []
    why: list[str] = []
    for t in times_to:
        if not times_from or t is None or t != t or t < times_from[0] - 1e-9 or t > times_from[-1] + 1e-9:
            out.append(None)
            why.append("missing_outside_support")
            continue
        j = bisect.bisect_left(times_from, t)
        if j < len(times_from) and abs(times_from[j] - t) <= 1e-9:
            out.append(series[j])
            why.append("matched" if series[j] is not None else "missing_source_reading")
            continue
        lo, hi = series[j - 1], series[j]
        if lo is None or hi is None:
            out.append(None)
            why.append("missing_bracket_reading")
            continue
        span = times_from[j] - times_from[j - 1]
        out.append(lo + (hi - lo) * (t - times_from[j - 1]) / span)
        why.append("interpolated")
    return out, why


def interpolate_onto(times_from: list[float], series: Series, times_to: list[float]) -> Series:
    return resample_onto(times_from, series, times_to)[0]


def alignment_counts(why: list[str]) -> dict:
    """Counts per target time, named for what they actually are."""
    return {
        "target_points": len(why),
        "points_matched_exactly": why.count("matched"),
        "points_interpolated": why.count("interpolated"),
        "points_missing_outside_support": why.count("missing_outside_support"),
        "points_missing_source_reading": why.count("missing_source_reading"),
        "points_missing_bracket_reading": why.count("missing_bracket_reading"),
    }


def mean_expression(
    times: list[float],
    fluorescence: Series,
    od: Series | None = None,
    min_od: float = 0.05,
    t_start: float | None = None,
    t_end: float | None = None,
) -> float | None:
    """Average reporter level over the kinetic run, optionally per unit OD.

    With `od`, points where OD is below `min_od` are skipped: dividing by a near-zero OD early in
    growth produces spikes that dominate the mean.
    """
    picked: list[float] = []
    for k, t in enumerate(times):
        if (t_start is not None and t < t_start) or (t_end is not None and t > t_end):
            continue
        f = fluorescence[k]
        if f is None:
            continue
        if od is not None:
            o = od[k]
            if o is None or o <= 0 or o < min_od:
                continue
            picked.append(f / o)
        else:
            picked.append(f)
    return _snap(statistics.fmean(picked), picked) if picked else None


@dataclass
class GroupSeries:
    group: str
    positions: list[str]
    times: list[float]
    mean: Series
    sd: Series
    n: list[int]


def grouped_series(times: list[float], values: dict[str, Series], groups: dict[str, list[str]]) -> list[GroupSeries]:
    result = []
    for name, positions in groups.items():
        present = [p for p in positions if p in values]
        means: Series = []
        sds: Series = []
        ns: list[int] = []
        for k in range(len(times)):
            m, s = _mean_sd([values[p][k] for p in present if values[p][k] is not None])
            means.append(m)
            sds.append(s)
            ns.append(sum(1 for p in present if values[p][k] is not None))
        result.append(GroupSeries(name, present, list(times), means, sds, ns))
    return result


def group_stats(per_position: dict[str, float | None], groups: dict[str, list[str]]) -> dict[str, dict]:
    out = {}
    for name, positions in groups.items():
        vals = [per_position[p] for p in positions if per_position.get(p) is not None]
        mean, sd = _mean_sd(vals)
        out[name] = {"mean": mean, "sd": sd, "n": len(vals)}
    return out
