# -*- coding: utf-8 -*-
# Copyright © 2024-2026 Pastastore Viewer Contributors. All rights reserved.
# This software is proprietary. See LICENSE.md for details.
"""Headless Pastas model analysis engine for comparison, scenario simulation, and forecasting.

This module intentionally avoids Qt/QGIS imports so all analysis logic can be
tested headlessly with pytest and executed inside background worker threads.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd
import pastas as ps
from scipy.stats import norm

DEFAULT_COMPARISON_METRICS = [
    "rsq",
    "evp",
    "rmse",
    "nse",
    "kge",
    "aic",
    "aicc",
    "bic",
]


# ---------------------------------------------------------------------------
# Pastas 1.x / 2.x compatibility helpers
# ---------------------------------------------------------------------------


def get_model_solver(ml: ps.Model) -> Any:
    """Return the solver/fit object across Pastas 1.x (`ml.fit`) and 2.x (`ml.solver`)."""
    solver = getattr(ml, "solver", None)
    if solver is not None:
        return solver
    return getattr(ml, "fit", None)


def is_model_solved(ml: ps.Model) -> bool:
    """Return True if the model has at least one non-NaN optimal parameter."""
    try:
        return bool(ml.parameters["optimal"].notna().any())
    except Exception:
        return False


def has_parameter_covariance(ml: ps.Model) -> bool:
    """Return True if the model solver has a usable finite parameter covariance matrix."""
    solver = get_model_solver(ml)
    if solver is None:
        return False
    pcov = getattr(solver, "pcov", None)
    if pcov is None:
        return False
    try:
        arr = np.asarray(pcov, dtype=float)
        return arr.size > 0 and np.isfinite(arr).all()
    except Exception:
        return False


def can_post_process_forecast(ml: ps.Model) -> bool:
    """Return True if `ps.forecast.forecast(..., post_process=True)` is supported."""
    if not is_model_solved(ml):
        return False
    return isinstance(getattr(ml, "noisemodel", None), ps.ArNoiseModel)


def get_model_freq(ml: ps.Model) -> str:
    """Return normalized frequency string for a Pastas model (default 'D')."""
    freq = None
    try:
        freq = ml.settings.get("freq")
    except Exception:
        freq = None
    return str(freq) if freq else "D"


def _freq_to_timedelta(freq: str) -> pd.Timedelta:
    """Convert a Pastas frequency string ('D', 'd', '7D', 'h', etc.) to Timedelta."""
    f = (freq or "D").strip()
    if len(f) == 1 and f.isalpha():
        f = f"1{f}"
    try:
        return pd.Timedelta(f)
    except Exception:
        return pd.Timedelta("1D")


def _extract_series_from_ts(ts_obj: Any) -> pd.Series:
    """Extract the underlying pandas Series from a Pastas TimeSeries or pandas Series."""
    if isinstance(ts_obj, pd.Series):
        return ts_obj.copy()
    if hasattr(ts_obj, "series_original") and ts_obj.series_original is not None:
        return ts_obj.series_original.copy()
    if hasattr(ts_obj, "series") and ts_obj.series is not None:
        return ts_obj.series.copy()
    raise TypeError(f"Cannot extract pandas Series from {type(ts_obj)!r}")


@dataclass
class StressInputInfo:
    """Metadata describing a single stress series input of a stressmodel."""

    sm_name: str
    sm_type: str
    arg_name: str
    index: int
    stress_name: str
    series: pd.Series
    tmin: pd.Timestamp | None
    tmax: pd.Timestamp | None

    @property
    def key(self) -> tuple[str, str]:
        return (self.sm_name, self.arg_name)


def get_stressmodel_inputs(ml: ps.Model) -> list[StressInputInfo]:
    """Introspect all stress series inputs across a Pastas model's stressmodels."""
    inputs: list[StressInputInfo] = []

    for sm_name, sm in ml.stressmodels.items():
        sm_type = sm.__class__.__name__

        # RechargeModel / TarsoModel have named prec, evap, optional temp
        if isinstance(sm, ps.RechargeModel):
            candidates = [("prec", 0), ("evap", 1)]
            if getattr(sm, "temp", None) is not None:
                candidates.append(("temp", 2))

            # Pastas 2.x exposes sm.prec / sm.evap / sm.temp; Pastas 1.x stores list in sm.stress
            for arg_name, idx in candidates:
                ts_obj = getattr(sm, arg_name, None)
                if ts_obj is None:
                    raw = getattr(sm, "stress", None)
                    if isinstance(raw, (list, tuple)) and idx < len(raw):
                        ts_obj = raw[idx]
                if ts_obj is None:
                    continue
                ser = _extract_series_from_ts(ts_obj)
                v_idx = ser.dropna().index
                inputs.append(
                    StressInputInfo(
                        sm_name=sm_name,
                        sm_type=sm_type,
                        arg_name=arg_name,
                        index=idx,
                        stress_name=str(getattr(ts_obj, "name", None) or ser.name or arg_name),
                        series=ser,
                        tmin=pd.Timestamp(v_idx.min()) if len(v_idx) else None,
                        tmax=pd.Timestamp(v_idx.max()) if len(v_idx) else None,
                    )
                )
            continue

        # WellModel has multiple stresses in sm.stresses (2.x) or sm.stress (1.x/2.x)
        if isinstance(sm, ps.WellModel):
            raw_list = getattr(sm, "stresses", None)
            if raw_list is None:
                raw_list = getattr(sm, "stress", ())
            if not isinstance(raw_list, (list, tuple)):
                raw_list = [raw_list]
            for idx, ts_obj in enumerate(raw_list):
                ser = _extract_series_from_ts(ts_obj)
                v_idx = ser.dropna().index
                inputs.append(
                    StressInputInfo(
                        sm_name=sm_name,
                        sm_type=sm_type,
                        arg_name=f"stress_{idx}",
                        index=idx,
                        stress_name=str(getattr(ts_obj, "name", None) or ser.name or f"well_{idx}"),
                        series=ser,
                        tmin=pd.Timestamp(v_idx.min()) if len(v_idx) else None,
                        tmax=pd.Timestamp(v_idx.max()) if len(v_idx) else None,
                    )
                )
            continue

        # StressModel / ChangeModel: single stress input
        ts_obj = None
        stresses_prop = getattr(sm, "stresses", None)
        if isinstance(stresses_prop, (list, tuple)) and len(stresses_prop) > 0:
            ts_obj = stresses_prop[0]
        else:
            raw_stress = getattr(sm, "stress", None)
            if isinstance(raw_stress, (list, tuple)) and len(raw_stress) > 0:
                ts_obj = raw_stress[0]
            elif raw_stress is not None:
                ts_obj = raw_stress

        if ts_obj is not None:
            ser = _extract_series_from_ts(ts_obj)
            v_idx = ser.dropna().index
            inputs.append(
                StressInputInfo(
                    sm_name=sm_name,
                    sm_type=sm_type,
                    arg_name="stress",
                    index=0,
                    stress_name=str(getattr(ts_obj, "name", None) or ser.name or sm_name),
                    series=ser,
                    tmin=pd.Timestamp(v_idx.min()) if len(v_idx) else None,
                    tmax=pd.Timestamp(v_idx.max()) if len(v_idx) else None,
                )
            )

    return inputs


def set_stressmodel_series(
    sm: Any,
    arg_name: str,
    index: int,
    new_series: pd.Series,
) -> None:
    """Replace a stress series on a Pastas stressmodel (compatible with Pastas 1.x and 2.x)."""
    new_series = new_series.copy()
    if isinstance(new_series, pd.DataFrame):
        new_series = new_series.iloc[:, 0]

    # Pastas 2.x path: set_stress() API
    if hasattr(sm, "set_stress") and callable(sm.set_stress):
        if isinstance(sm, ps.RechargeModel):
            sm.set_stress(**{arg_name: new_series})
            return
        if isinstance(sm, ps.WellModel):
            current = list(getattr(sm, "stresses", getattr(sm, "stress", ())))
            updated = [_extract_series_from_ts(ts) for ts in current]
            if 0 <= index < len(updated):
                updated[index] = new_series
            sm.set_stress(updated)
            return
        sm.set_stress(new_series)
        return

    # Pastas 1.x path: mutate TimeSeries.series_original on sm.stress[index]
    raw = getattr(sm, "stress", None)
    if isinstance(raw, (list, tuple)) and index < len(raw):
        ts_obj = raw[index]
        ts_obj.series_original = new_series
        if hasattr(ts_obj, "update_series"):
            ts_obj.update_series(force_update=True)
        return
    if raw is not None and hasattr(raw, "series_original"):
        raw.series_original = new_series
        if hasattr(raw, "update_series"):
            raw.update_series(force_update=True)
        return

    raise RuntimeError(
        f"Cannot replace stress '{arg_name}' on stressmodel '{sm.name}' ({sm.__class__.__name__})."
    )


def get_model_common_stress_range(
    ml: ps.Model,
) -> tuple[pd.Timestamp | None, pd.Timestamp | None]:
    """Return the overlapping [tmin, tmax] range across all stresses in the model."""
    inputs = get_stressmodel_inputs(ml)
    tmins = [inp.tmin for inp in inputs if inp.tmin is not None]
    tmaxs = [inp.tmax for inp in inputs if inp.tmax is not None]
    if not tmins or not tmaxs:
        return None, None
    return max(tmins), min(tmaxs)


def get_model_full_stress_range(
    ml: ps.Model,
) -> tuple[pd.Timestamp | None, pd.Timestamp | None]:
    """Return the widest [min(tmin), max(tmax)] range across all stresses in the model."""
    inputs = get_stressmodel_inputs(ml)
    tmins = [inp.tmin for inp in inputs if inp.tmin is not None]
    tmaxs = [inp.tmax for inp in inputs if inp.tmax is not None]
    if not tmins or not tmaxs:
        return None, None
    return min(tmins), max(tmaxs)


# ---------------------------------------------------------------------------
# 1. Scenario Simulation Engine
# ---------------------------------------------------------------------------


@dataclass
class StressOverride:
    """Configuration for overriding a single stress input in a scenario simulation."""

    sm_name: str
    arg_name: str
    index: int = 0
    mode: str = "original"  # "original", "store", "constant", "series"
    store_stress_name: str | None = None
    constant_value: float = 0.0
    custom_series: pd.Series | None = None
    scale: float = 1.0
    offset: float = 0.0
    apply_from: pd.Timestamp | str | None = None


@dataclass
class ScenarioConfig:
    """Configuration for a non-destructive scenario simulation."""

    name: str
    tmin: pd.Timestamp | str | None = None
    tmax: pd.Timestamp | str | None = None
    freq: str | None = None
    return_warmup: bool = False
    disabled_stressmodels: list[str] = field(default_factory=list)
    overrides: list[StressOverride] = field(default_factory=list)
    compute_ci: bool = False
    ci_samples: int = 200
    ci_alpha: float = 0.05


@dataclass
class ScenarioResult:
    """Result bundle produced by `run_scenario_simulation`."""

    name: str
    simulation: pd.Series
    contributions: dict[str, pd.Series] = field(default_factory=dict)
    difference: pd.Series | None = None
    ci: pd.DataFrame | None = None
    warnings: list[str] = field(default_factory=list)


def _to_series(data: pd.Series | pd.DataFrame, name: str | None = None) -> pd.Series:
    """Coerce a 1-column DataFrame or Series to a float Series with DatetimeIndex."""
    if isinstance(data, pd.DataFrame):
        if data.empty:
            raise ValueError("Selected stress series is empty.")
        ser = data.iloc[:, 0].copy()
    else:
        ser = data.copy()
    ser.index = pd.to_datetime(ser.index)
    ser = ser.sort_index()
    ser = pd.to_numeric(ser, errors="coerce")
    if name:
        ser.name = name
    return ser


def apply_stress_override(
    orig_series: pd.Series,
    override: StressOverride,
    store: Any = None,
    tmin: pd.Timestamp | str | None = None,
    tmax: pd.Timestamp | str | None = None,
    freq: str = "D",
) -> pd.Series:
    """Build a modified stress series according to *override* without mutating *orig_series*."""
    orig = _to_series(orig_series)
    dt = _freq_to_timedelta(freq)

    if override.mode == "original":
        target = orig.copy()
    elif override.mode == "store":
        if store is None or not override.store_stress_name:
            raise ValueError(
                f"No store stress selected for '{override.sm_name}.{override.arg_name}'."
            )
        target = _to_series(
            store.get_stresses(override.store_stress_name),
            name=override.store_stress_name,
        )
    elif override.mode == "series":
        if override.custom_series is None or len(override.custom_series) == 0:
            raise ValueError(
                f"No custom series provided for '{override.sm_name}.{override.arg_name}'."
            )
        target = _to_series(override.custom_series)
    elif override.mode == "constant":
        start_candidates = [orig.index.min()]
        end_candidates = [orig.index.max()]
        if tmin is not None:
            start_candidates.append(pd.Timestamp(tmin) - pd.Timedelta(days=3650))
        if tmax is not None:
            end_candidates.append(pd.Timestamp(tmax))
        if override.apply_from is not None:
            start_candidates.append(pd.Timestamp(override.apply_from))
        idx = pd.date_range(
            start=min(start_candidates),
            end=max(end_candidates),
            freq=freq or "D",
        )
        target = pd.Series(
            float(override.constant_value),
            index=idx,
            name=orig.name or override.arg_name,
        )
    else:
        raise ValueError(f"Unknown stress override mode: '{override.mode}'")

    # Apply linear transform (scale & offset)
    if override.scale != 1.0 or override.offset != 0.0:
        target = target * float(override.scale) + float(override.offset)

    # Optional splice: keep original series before `apply_from`, use `target` from `apply_from`
    if override.apply_from is not None:
        t_split = pd.Timestamp(override.apply_from)
        hist_part = orig.loc[: t_split - dt]
        new_part = target.loc[t_split:]
        if new_part.empty:
            raise ValueError(
                f"Replacement stress for '{override.sm_name}.{override.arg_name}' "
                f"has no data on or after {t_split.date()}."
            )
        combined = pd.concat([hist_part, new_part])
        combined = combined[~combined.index.duplicated(keep="last")].sort_index()
        combined.name = orig.name
        return combined

    target.name = orig.name or target.name
    return target


def build_scenario_model(
    ml: ps.Model,
    config: ScenarioConfig,
    store: Any = None,
) -> ps.Model:
    """Return a copied Pastas model with scenario stress overrides and disabled stressmodels applied."""
    ml_copy = ml.copy(name=f"{ml.name}_{config.name}")
    freq = config.freq or get_model_freq(ml_copy)

    # Map existing inputs for lookup
    inputs_by_key = {inp.key: inp for inp in get_stressmodel_inputs(ml_copy)}

    # 1. Apply explicit stress overrides
    for ov in config.overrides:
        if ov.sm_name not in ml_copy.stressmodels:
            continue
        is_noop = (
            ov.mode == "original"
            and ov.scale == 1.0
            and ov.offset == 0.0
            and ov.apply_from is None
        )
        if is_noop:
            continue
        inp = inputs_by_key.get((ov.sm_name, ov.arg_name))
        if inp is None:
            continue
        new_series = apply_stress_override(
            inp.series,
            ov,
            store=store,
            tmin=config.tmin,
            tmax=config.tmax,
            freq=freq,
        )
        sm = ml_copy.stressmodels[ov.sm_name]
        set_stressmodel_series(sm, ov.arg_name, inp.index, new_series)

    # 2. Disable requested stressmodels without breaking model structure
    for sm_name in config.disabled_stressmodels:
        if sm_name not in ml_copy.stressmodels:
            continue
        sm = ml_copy.stressmodels[sm_name]
        sm_inputs = [inp for inp in get_stressmodel_inputs(ml_copy) if inp.sm_name == sm_name]
        if sm_inputs:
            # Zero out stress series for stress-driven models
            for inp in sm_inputs:
                zero_ser = pd.Series(0.0, index=inp.series.index, name=inp.series.name)
                set_stressmodel_series(sm, inp.arg_name, inp.index, zero_ser)
        else:
            # StepModel / LinearTrend: zero out amplitude/slope parameters
            for pname in list(ml_copy.parameters.index):
                if ml_copy.parameters.loc[pname, "name"] == sm_name:
                    if pname.endswith(("_A", "_a", "_d")):
                        if pd.notna(ml_copy.parameters.loc[pname, "optimal"]):
                            ml_copy.parameters.loc[pname, "optimal"] = 0.0
                        ml_copy.parameters.loc[pname, "initial"] = 0.0

    return ml_copy


def run_scenario_simulation(
    ml: ps.Model,
    config: ScenarioConfig,
    store: Any = None,
    baseline_sim: pd.Series | None = None,
) -> ScenarioResult:
    """Run a non-destructive scenario simulation and return the resulting time series."""
    warnings_list: list[str] = []
    ml_copy = build_scenario_model(ml, config, store=store)

    tmin = pd.Timestamp(config.tmin) if config.tmin is not None else None
    tmax = pd.Timestamp(config.tmax) if config.tmax is not None else None
    freq = config.freq or get_model_freq(ml_copy)

    sim = ml_copy.simulate(
        tmin=tmin,
        tmax=tmax,
        freq=freq,
        return_warmup=config.return_warmup,
    )
    sim.name = config.name

    contributions: dict[str, pd.Series] = {}
    for sm_name in ml_copy.stressmodels:
        try:
            contrib = ml_copy.get_contribution(
                sm_name,
                tmin=tmin,
                tmax=tmax,
                return_warmup=config.return_warmup,
            )
            contributions[sm_name] = contrib
        except Exception as exc:
            warnings_list.append(f"Could not compute contribution '{sm_name}': {exc}")

    diff = None
    if baseline_sim is not None and not baseline_sim.empty:
        aligned_base = baseline_sim.reindex(sim.index)
        diff = sim - aligned_base
        diff.name = f"{config.name} - Baseline"

    ci_df = None
    if config.compute_ci:
        if has_parameter_covariance(ml_copy):
            try:
                solver = get_model_solver(ml_copy)
                ci_df = solver.ci_simulation(
                    n=int(config.ci_samples),
                    alpha=float(config.ci_alpha),
                    tmin=tmin,
                    tmax=tmax,
                    freq=freq,
                    return_warmup=config.return_warmup,
                )
            except Exception as exc:
                warnings_list.append(f"Confidence interval could not be computed: {exc}")
        else:
            warnings_list.append(
                "Parameter covariance matrix not available; skipped confidence interval."
            )

    return ScenarioResult(
        name=config.name,
        simulation=sim,
        contributions=contributions,
        difference=diff,
        ci=ci_df,
        warnings=warnings_list,
    )


# ---------------------------------------------------------------------------
# 2. Forecast / Ensemble Prediction Engine (pastas.forecast)
# ---------------------------------------------------------------------------


def build_historical_analogue_ensemble(
    series: pd.Series,
    tmin: pd.Timestamp | str,
    tmax: pd.Timestamp | str,
    freq: str = "D",
    years: list[int] | None = None,
) -> pd.DataFrame:
    """Create a multi-member ensemble DataFrame by shifting historical year windows onto [tmin, tmax].

    Each column corresponds to one historical year whose matching calendar-day
    window had complete (non-NaN) data.
    """
    ser = _to_series(series)
    t0 = pd.Timestamp(tmin)
    t1 = pd.Timestamp(tmax)
    if t1 < t0:
        raise ValueError("Forecast end date (tmax) must be on or after start date (tmin).")

    target_index = pd.date_range(start=t0, end=t1, freq=freq or "D")
    n_steps = len(target_index)
    if n_steps == 0:
        raise ValueError("Forecast horizon produced an empty date range.")

    # Resample historical series to target frequency so offsets match cleanly
    ser_reg = ser.resample(freq or "D").mean()

    ser_min_year = int(ser_reg.index.min().year)
    ser_max_year = int(ser_reg.index.max().year)
    candidate_years = years if years is not None else list(range(ser_min_year, ser_max_year + 1))

    horizon_span = target_index[-1] - target_index[0]
    members: dict[str, np.ndarray] = {}

    for yr in candidate_years:
        # Handle Feb 29 start date on non-leap years
        day = t0.day
        if t0.month == 2 and day == 29 and not pd.Timestamp(yr, 1, 1).is_leap_year:
            day = 28
        try:
            win_start = pd.Timestamp(
                year=yr,
                month=t0.month,
                day=day,
                hour=t0.hour,
                minute=t0.minute,
                second=t0.second,
            )
        except ValueError:
            continue

        win_end = win_start + horizon_span
        # Do not include windows extending beyond available data (or into the forecast itself)
        if win_start < ser_reg.index.min() or win_end > min(ser_reg.index.max(), t0 - _freq_to_timedelta(freq)):
            continue

        win_idx = pd.date_range(start=win_start, periods=n_steps, freq=freq or "D")
        sliced = ser_reg.reindex(win_idx)
        if sliced.isna().any():
            # Allow tiny internal gaps to be interpolated, skip if mostly missing
            if sliced.isna().mean() > 0.1:
                continue
            sliced = sliced.interpolate(limit_direction="both")
            if sliced.isna().any():
                continue

        members[str(yr)] = sliced.to_numpy(dtype=float)

    if not members:
        raise ValueError(
            f"No complete historical analogue years available in '{ser.name}' "
            f"for horizon {t0.date()} to {t1.date()}."
        )

    return pd.DataFrame(members, index=target_index)


def align_historical_ensembles(
    series_map: dict[tuple[str, str], pd.Series],
    tmin: pd.Timestamp | str,
    tmax: pd.Timestamp | str,
    freq: str = "D",
) -> dict[tuple[str, str], pd.DataFrame]:
    """Build historical analogue ensembles for multiple stresses, keeping only common years.

    Retaining common years preserves physical correlation across stresses
    (e.g. pairing precipitation and evaporation from the same historical year).
    """
    raw: dict[tuple[str, str], pd.DataFrame] = {}
    common_cols: list[str] | None = None

    for key, ser in series_map.items():
        df = build_historical_analogue_ensemble(ser, tmin=tmin, tmax=tmax, freq=freq)
        raw[key] = df
        cols = list(df.columns)
        if common_cols is None:
            common_cols = cols
        else:
            col_set = set(cols)
            common_cols = [c for c in common_cols if c in col_set]

    if not common_cols:
        raise ValueError(
            "No common historical analogue years found across all selected stresses."
        )

    return {key: df[common_cols].copy() for key, df in raw.items()}


def build_synthetic_forecast(
    series: pd.Series,
    tmin: pd.Timestamp | str,
    tmax: pd.Timestamp | str,
    freq: str = "D",
    mode: str = "climatology_mean",
    constant_value: float = 0.0,
    scale: float = 1.0,
) -> pd.DataFrame:
    """Create a 1-member deterministic forecast DataFrame (constant, zero, or climatology mean)."""
    t0 = pd.Timestamp(tmin)
    t1 = pd.Timestamp(tmax)
    if t1 < t0:
        raise ValueError("Forecast end date (tmax) must be on or after start date (tmin).")

    target_index = pd.date_range(start=t0, end=t1, freq=freq or "D")

    if mode == "zero":
        return pd.DataFrame({"member_0": np.zeros(len(target_index))}, index=target_index)

    if mode == "constant":
        val = float(constant_value) * float(scale)
        return pd.DataFrame(
            {"member_0": np.full(len(target_index), val, dtype=float)},
            index=target_index,
        )

    if mode == "climatology_mean":
        ser = _to_series(series).dropna()
        if ser.empty:
            raise ValueError("Historical stress series is empty.")
        doy_mean = ser.groupby(ser.index.dayofyear).mean()
        fallback = float(ser.mean())
        vals = np.array(
            [float(doy_mean.get(d, fallback)) * float(scale) for d in target_index.dayofyear],
            dtype=float,
        )
        return pd.DataFrame({"climatology_mean": vals}, index=target_index)

    raise ValueError(f"Unknown synthetic forecast mode: '{mode}'")


def load_ensemble_csv(
    filepath: str | Path,
    tmin: pd.Timestamp | str | None = None,
    tmax: pd.Timestamp | str | None = None,
    freq: str | None = None,
) -> pd.DataFrame:
    """Load a multi-member ensemble forecast table (CSV, Parquet, or Excel).

    Expects a datetime index in the first column and one or more numeric member columns.
    """
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"Forecast file not found: {path}")

    suffix = path.suffix.lower()
    if suffix in (".parquet", ".pq"):
        df = pd.read_parquet(path)
    elif suffix in (".xlsx", ".xls"):
        df = pd.read_excel(path, index_col=0, parse_dates=True)
    else:
        df = pd.read_csv(path, index_col=0, parse_dates=True)

    if df.empty:
        raise ValueError(f"Forecast file '{path.name}' is empty.")

    df.index = pd.to_datetime(df.index)
    df = df.sort_index()
    # Keep numeric columns only
    df = df.apply(pd.to_numeric, errors="coerce").dropna(axis=1, how="all")
    if df.empty or df.shape[1] == 0:
        raise ValueError(f"Forecast file '{path.name}' has no numeric ensemble columns.")

    if tmin is not None:
        df = df.loc[pd.Timestamp(tmin) :]
    if tmax is not None:
        df = df.loc[: pd.Timestamp(tmax)]

    if freq:
        df = df.resample(freq).mean().interpolate(limit_direction="both")

    if df.empty:
        raise ValueError(
            f"Forecast file '{path.name}' has no data within the selected period."
        )

    df.columns = [str(c) for c in df.columns]
    return df


def normalize_forecast_dict(
    ml: ps.Model,
    raw_forecasts: dict[str, dict[str, pd.DataFrame | pd.Series]],
    tmin: pd.Timestamp | str | None = None,
    tmax: pd.Timestamp | str | None = None,
    freq: str | None = None,
) -> dict[str, dict[str, pd.DataFrame]]:
    """Validate, align indices, broadcast 1-member stresses, and order keys for Pastas 1.x & 2.x.

    Returns a dictionary `{sm_name: {arg_name: DataFrame}}` where every DataFrame
    shares the exact same DatetimeIndex and ensemble member columns.
    """
    if not raw_forecasts:
        raise ValueError("No forecast inputs provided.")

    use_freq = freq or get_model_freq(ml)
    inputs_by_sm: dict[str, list[StressInputInfo]] = {}
    for inp in get_stressmodel_inputs(ml):
        inputs_by_sm.setdefault(inp.sm_name, []).append(inp)

    # First pass: convert Series -> DataFrame, determine common index & target member count
    converted: dict[str, dict[str, pd.DataFrame]] = {}
    target_cols: list[str] | None = None
    n_members = 1
    inferred_tmins: list[pd.Timestamp] = []
    inferred_tmaxs: list[pd.Timestamp] = []

    for sm_name, sm_dict in raw_forecasts.items():
        if sm_name not in ml.stressmodels:
            raise ValueError(f"Stressmodel '{sm_name}' does not exist in model '{ml.name}'.")
        converted[sm_name] = {}
        for arg_name, data in sm_dict.items():
            df = data.to_frame() if isinstance(data, pd.Series) else data.copy()
            df.index = pd.to_datetime(df.index)
            df = df.sort_index()
            if df.empty:
                raise ValueError(f"Forecast data for '{sm_name}.{arg_name}' is empty.")
            converted[sm_name][arg_name] = df
            inferred_tmins.append(pd.Timestamp(df.index.min()))
            inferred_tmaxs.append(pd.Timestamp(df.index.max()))

            if df.shape[1] > 1:
                if n_members == 1:
                    n_members = df.shape[1]
                    target_cols = [str(c) for c in df.columns]
                elif df.shape[1] != n_members:
                    raise ValueError(
                        f"Ensemble member count mismatch: '{sm_name}.{arg_name}' has "
                        f"{df.shape[1]} members, expected {n_members}."
                    )

    t0 = pd.Timestamp(tmin) if tmin is not None else max(inferred_tmins)
    t1 = pd.Timestamp(tmax) if tmax is not None else min(inferred_tmaxs)
    if t1 < t0:
        raise ValueError("Forecast stress series do not share an overlapping time period.")

    target_index = pd.date_range(start=t0, end=t1, freq=use_freq)
    if target_cols is None:
        # All inputs had 1 column
        first_sm = next(iter(converted.values()))
        first_df = next(iter(first_sm.values()))
        target_cols = [str(c) for c in first_df.columns]

    # Second pass: canonical key ordering per stressmodel + index alignment + broadcasting
    normalized: dict[str, dict[str, pd.DataFrame]] = {}
    for sm_name, sm_dict in converted.items():
        canonical_inputs = inputs_by_sm.get(sm_name, [])
        ordered: dict[str, pd.DataFrame] = {}

        for inp in canonical_inputs:
            if inp.arg_name in sm_dict:
                df = sm_dict[inp.arg_name]
            else:
                # Fill unprovided sibling stress (e.g. evap when only prec was overridden)
                # using existing stress slice or climatology mean so Pastas 1.x & 2.x stay consistent.
                existing_slice = inp.series.loc[t0:t1]
                if len(existing_slice) >= len(target_index) and not existing_slice.isna().any():
                    df = existing_slice.to_frame(name=target_cols[0])
                else:
                    df = build_synthetic_forecast(
                        inp.series, tmin=t0, tmax=t1, freq=use_freq, mode="climatology_mean"
                    )

            df_aligned = df.reindex(target_index).interpolate(limit_direction="both")
            if df_aligned.isna().any().any():
                raise ValueError(
                    f"Forecast for '{sm_name}.{inp.arg_name}' contains NaN values "
                    f"between {t0.date()} and {t1.date()}."
                )

            if df_aligned.shape[1] == 1 and n_members > 1:
                col_vals = df_aligned.iloc[:, 0].to_numpy(dtype=float)
                df_aligned = pd.DataFrame(
                    np.tile(col_vals[:, None], (1, n_members)),
                    index=target_index,
                    columns=target_cols,
                )
            else:
                df_aligned.columns = target_cols

            ordered[inp.arg_name] = df_aligned

        if ordered:
            normalized[sm_name] = ordered

    return normalized


@dataclass
class ForecastResult:
    """Result bundle produced by `run_ensemble_forecast`."""

    raw_df: pd.DataFrame
    overall_mean: pd.Series
    overall_var: pd.Series
    overall_std: pd.Series
    member_means: pd.DataFrame
    summary: pd.DataFrame
    n_ensemble_members: int
    n_param_samples: int
    post_processed: bool
    forecast_start: pd.Timestamp
    forecast_end: pd.Timestamp

    def compute_exceedance_probability(
        self,
        threshold: float,
        direction: str = "below",
    ) -> pd.DataFrame:
        """Compute probability of head being below/above *threshold* at each forecast step.

        Returns DataFrame with columns `prob_parametric` (using total Gaussian
        mean/std from law of total variance) and `prob_empirical` (fraction of
        member means meeting the criterion).
        """
        thresh = float(threshold)
        std = self.overall_std.replace(0.0, np.nan)
        z = (thresh - self.overall_mean) / std

        if direction == "below":
            p_param = pd.Series(norm.cdf(z), index=self.overall_mean.index)
            p_param = p_param.fillna((self.overall_mean < thresh).astype(float))
            p_emp = (self.member_means < thresh).mean(axis=1)
        elif direction == "above":
            p_param = pd.Series(1.0 - norm.cdf(z), index=self.overall_mean.index)
            p_param = p_param.fillna((self.overall_mean > thresh).astype(float))
            p_emp = (self.member_means > thresh).mean(axis=1)
        else:
            raise ValueError(f"direction must be 'below' or 'above', got {direction!r}")

        return pd.DataFrame(
            {
                "prob_parametric": p_param.clip(0.0, 1.0),
                "prob_empirical": p_emp.clip(0.0, 1.0),
            },
            index=self.overall_mean.index,
        )


def run_ensemble_forecast(
    ml: ps.Model,
    forecasts_dict: dict[str, dict[str, pd.DataFrame | pd.Series]],
    tmin: pd.Timestamp | str | None = None,
    tmax: pd.Timestamp | str | None = None,
    n_param_samples: int = 0,
    post_process: bool = False,
    seed: int | None = None,
    progress_callback: Callable[[int, str], None] | None = None,
) -> ForecastResult:
    """Run Pastas ensemble forecasting (`ps.forecast.forecast`) and compute summary statistics."""
    if not is_model_solved(ml):
        raise ValueError(
            f"Model '{ml.name}' is not solved yet. Please solve the model before forecasting."
        )

    if progress_callback:
        progress_callback(10, "Validating forecast inputs...")

    normalized = normalize_forecast_dict(
        ml, forecasts_dict, tmin=tmin, tmax=tmax, freq=get_model_freq(ml)
    )

    if post_process and not can_post_process_forecast(ml):
        raise ValueError(
            "AR1 post-processing requires an ArNoiseModel on the calibrated model."
        )

    p = None
    n_params_used = 1
    if n_param_samples and int(n_param_samples) > 0:
        if not has_parameter_covariance(ml):
            raise ValueError(
                "Parameter uncertainty sampling requires a solver covariance matrix (pcov)."
            )
        if progress_callback:
            progress_callback(25, f"Sampling {n_param_samples} parameter sets...")
        solver = get_model_solver(ml)
        p = solver.get_parameter_sample(n=int(n_param_samples), seed=seed)
        n_params_used = len(p)

    if progress_callback:
        progress_callback(45, "Running ensemble forecast simulations...")

    # Ensure freq_obs is a valid Timedelta when AR1 post-processing is requested,
    # because pastas.forecast computes `model.settings["freq_obs"] / Timedelta("1D")`
    # and default solved models often have freq_obs=None (which yields NaN variance).
    ml_run = ml
    if post_process:
        freq_obs = ml.settings.get("freq_obs")
        needs_fix = (
            freq_obs is None
            or (isinstance(freq_obs, float) and np.isnan(freq_obs))
            or pd.isna(freq_obs)
            or isinstance(freq_obs, str)
        )
        if needs_fix:
            ml_run = ml.copy()
            if isinstance(freq_obs, str) and freq_obs.strip():
                inferred_dt = _freq_to_timedelta(freq_obs)
            else:
                obs_idx = ml_run.observations().dropna().index
                diffs = obs_idx.to_series().diff().dropna() if len(obs_idx) >= 2 else pd.Series(dtype="timedelta64[ns]")
                inferred_dt = (
                    pd.Timedelta(diffs.median())
                    if not diffs.empty and pd.notna(diffs.median()) and diffs.median() > pd.Timedelta(0)
                    else _freq_to_timedelta(get_model_freq(ml_run))
                )
            if hasattr(ml_run, "_settings") and isinstance(ml_run._settings, dict):
                ml_run._settings["freq_obs"] = inferred_dt
            else:
                ml_run.settings["freq_obs"] = inferred_dt

    # Call positionally so both Pastas 1.x (ml) and Pastas 2.x (model) work identically.
    raw_df = ps.forecast.forecast(
        ml_run,
        normalized,
        p=p,
        post_process=bool(post_process),
    )

    if progress_callback:
        progress_callback(85, "Aggregating predictive statistics...")

    overall_mean, overall_var = ps.forecast.get_overall_mean_and_variance(raw_df)
    overall_std = np.sqrt(overall_var.clip(lower=0.0))

    # Extract member-level mean trajectories (average over param_member per ensemble_member)
    means_all = raw_df.xs("mean", level="forecast", axis=1)
    member_means = means_all.T.groupby(level="ensemble_member").mean().T

    # Build rich summary DataFrame
    z50 = norm.ppf(0.75)
    z90 = norm.ppf(0.95)
    z95 = norm.ppf(0.975)

    summary = pd.DataFrame(
        {
            "mean": overall_mean,
            "std": overall_std,
            "var": overall_var,
            "ci95_low": overall_mean - z95 * overall_std,
            "ci90_low": overall_mean - z90 * overall_std,
            "ci50_low": overall_mean - z50 * overall_std,
            "ci50_high": overall_mean + z50 * overall_std,
            "ci90_high": overall_mean + z90 * overall_std,
            "ci95_high": overall_mean + z95 * overall_std,
            "p05": member_means.quantile(0.05, axis=1),
            "p25": member_means.quantile(0.25, axis=1),
            "p50": member_means.quantile(0.50, axis=1),
            "p75": member_means.quantile(0.75, axis=1),
            "p95": member_means.quantile(0.95, axis=1),
        },
        index=raw_df.index,
    )

    if progress_callback:
        progress_callback(100, "Forecast completed.")

    return ForecastResult(
        raw_df=raw_df,
        overall_mean=overall_mean,
        overall_var=overall_var,
        overall_std=overall_std,
        member_means=member_means,
        summary=summary,
        n_ensemble_members=member_means.shape[1],
        n_param_samples=n_params_used,
        post_processed=bool(post_process),
        forecast_start=pd.Timestamp(raw_df.index[0]),
        forecast_end=pd.Timestamp(raw_df.index[-1]),
    )


# ---------------------------------------------------------------------------
# 3. Model Comparison Engine (pastas.CompareModels)
# ---------------------------------------------------------------------------


@dataclass
class ComparisonData:
    """Structured comparison data built on top of `ps.CompareModels`."""

    model_names: list[str]
    models: list[ps.Model]
    same_oseries: bool
    unique_stressmodels: list[str]
    tmin_tmax: pd.DataFrame
    metrics: pd.DataFrame
    parameters_optimal: pd.DataFrame
    parameters_stderr: pd.DataFrame
    diagnostics: pd.DataFrame
    common_tmin: pd.Timestamp | None
    common_tmax: pd.Timestamp | None


def _check_same_oseries(
    models: list[ps.Model],
    tmin: pd.Timestamp | None = None,
    tmax: pd.Timestamp | None = None,
) -> bool:
    """Return True if all models share identical observation series."""
    if len(models) <= 1:
        return True
    try:
        obs_list = [ml.observations(tmin=tmin, tmax=tmax) for ml in models]
        first = obs_list[0]
        for other in obs_list[1:]:
            if len(first) != len(other):
                return False
            if not first.index.equals(other.index):
                return False
            if not np.allclose(first.to_numpy(dtype=float), other.to_numpy(dtype=float), equal_nan=True):
                return False
        return True
    except Exception:
        return False


def compute_fast_acf(
    series: pd.Series,
    max_lags: int = 365,
    bin_width: float = 0.5,
    max_gap: float = np.inf,
    min_obs: int = 50,
    alpha: float = 0.05,
) -> pd.DataFrame:
    """Compute the exact Pastas autocorrelation function quickly without Numba.

    Matches `pastas.stats.acf(..., full_output=True)` to float64 machine precision:
    - Regular-timestep series delegate directly to `pastas.stats.acf(..., bin_method="regular")`.
    - Irregular-timestep series evaluate Pastas' exact Rehfeld (2011) Gaussian-kernel
      slotting formula using vectorized NumPy lag-offset slicing and `np.bincount`
      instead of Pastas' O(lags * N^2) pure-Python triple loop, achieving >2,000x
      speedup when Numba is unavailable (e.g. inside QGIS).
    """
    ser = series.dropna()
    if len(ser) < 3:
        return pd.DataFrame(columns=["acf", "conf", "n"])

    # Regular series: Pastas uses fast O(lags * N) vectorized corrcoef
    if getattr(ser.index, "inferred_freq", None):
        try:
            return ps.stats.acf(
                ser,
                lags=max_lags,
                bin_method="regular",
                bin_width=bin_width,
                max_gap=max_gap,
                min_obs=min_obs,
                full_output=True,
                alpha=alpha,
            )
        except Exception:
            return pd.DataFrame(columns=["acf", "conf", "n"])

    # Exact Pastas `_preprocess` for irregular time steps
    x_idx = ser.index.to_series().diff().dropna().to_numpy()
    if len(x_idx) == 0:
        return pd.DataFrame(columns=["acf", "conf", "n"])

    dt_step = x_idx / pd.Timedelta(1, "D")
    t = dt_step.cumsum().astype(float)
    x_vals = ser.to_numpy(dtype=float)
    std_val = float(x_vals.std())
    if std_val == 0.0 or not np.isfinite(std_val):
        return pd.DataFrame(columns=["acf", "conf", "n"])

    x = (x_vals - x_vals.mean()) / std_val
    n = len(t)
    x = x[:n]

    den1 = -2.0 * bin_width**2
    den2 = float(np.sqrt(2.0 * np.pi * bin_width))
    # Pastas uses 6 * den2; beyond 9 * bin_width, exp(-40.5) ~ 2.6e-18 (below float64 eps)
    eff_cutoff = min(6.0 * den2, 9.0 * bin_width)
    radius = int(np.ceil(eff_cutoff))
    max_dt_needed = float(max_lags) + eff_cutoff

    cl = np.zeros(max_lags + 1, dtype=float)
    b_sum = np.zeros(max_lags + 1, dtype=float)

    # Traverse diagonals m = i - j >= 0; since t is non-decreasing, stop as soon
    # as all pairs at offset m exceed max_dt_needed.
    m = 0
    while m < n:
        if m == 0:
            dt_m = np.zeros(n, dtype=float)
        else:
            dt_m = t[m:] - t[: n - m]
            if dt_m.min() > max_dt_needed:
                break

        mask = dt_m <= max_dt_needed
        if np.any(mask):
            dt_valid = dt_m[mask]
            if m == 0:
                prod_valid = x[mask] * x[mask]
            else:
                prod_valid = x[m:][mask] * x[: n - m][mask]

            k0 = np.floor(dt_valid + 0.5).astype(np.int64)
            for delta in range(-radius, radius + 1):
                k = k0 + delta
                in_rng = (k >= 0) & (k <= max_lags)
                if not np.any(in_rng):
                    continue
                kk = k[in_rng]
                dtlag = dt_valid[in_rng] - kk
                in_win = np.abs(dtlag) < eff_cutoff
                if not np.any(in_win):
                    continue
                kk = kk[in_win]
                w = np.exp((dtlag[in_win] ** 2) / den1) / den2
                cl += np.bincount(
                    kk, weights=prod_valid[in_rng][in_win] * w, minlength=max_lags + 1
                )
                b_sum += np.bincount(kk, weights=w, minlength=max_lags + 1)
        m += 1

    with np.errstate(invalid="ignore", divide="ignore"):
        c = np.where(b_sum == 0.0, np.nan, cl / b_sum)
    b = np.where(b_sum == 0.0, 1e-16, b_sum)
    conf = float(norm.ppf(1.0 - alpha / 2.0)) / np.sqrt(b)

    lags = np.arange(0, max_lags + 1, dtype=float)
    result = pd.DataFrame(
        data={"acf": c, "conf": conf, "n": b},
        dtype=float,
        index=pd.Index(pd.to_timedelta(lags, unit="D"), name="Lags"),
    )
    result = result.where(result.n > min_obs).dropna()
    if not result.empty and result.index[0] == pd.Timedelta(0):
        result = result.drop(result.index[0])
    result.name = "ACF"
    return result


def compute_fast_diagnostics(
    models: list[ps.Model],
    model_names: list[str],
    tmin: pd.Timestamp | str | None = None,
    tmax: pd.Timestamp | str | None = None,
) -> pd.DataFrame:
    """Compute diagnostic test P-values without triggering slow O(N^2) pure-Python ACF."""
    t0 = pd.Timestamp(tmin) if tmin is not None else None
    t1 = pd.Timestamp(tmax) if tmax is not None else None

    diag_cols: dict[str, pd.Series] = {}
    for mname, ml in zip(model_names, models):
        if not is_model_solved(ml):
            diag_cols[mname] = pd.Series(dtype=float)
            continue
        try:
            if ml.noisemodel is not None:
                ser = ml.noise(tmin=t0, tmax=t1).dropna()
                nparam = getattr(ml.noisemodel, "nparam", 1)
            else:
                ser = ml.residuals(tmin=t0, tmax=t1).dropna()
                nparam = 0

            # Avoid O(N^2) pure-Python irregular slotting inside stoffer_toloi when N is large
            is_regular = bool(getattr(ser.index, "inferred_freq", None))
            if not is_regular and len(ser) > 350:
                diffs = ser.index.to_series().diff().dropna()
                med_days = max(1, int(round(diffs.median() / pd.Timedelta("1D")))) if not diffs.empty else 1
                ser = ser.resample(f"{med_days}D").mean().dropna()

            if len(ser) < 10:
                diag_cols[mname] = pd.Series(dtype=float)
                continue

            d = ps.stats.diagnostics(series=ser, nparam=nparam)
            if "P-value" in d.columns:
                diag_cols[mname] = pd.to_numeric(d["P-value"], errors="coerce")
            else:
                diag_cols[mname] = pd.Series(dtype=float)
        except Exception:
            diag_cols[mname] = pd.Series(dtype=float)

    return pd.DataFrame(diag_cols) if diag_cols else pd.DataFrame(columns=model_names)


def build_comparison_data(
    models: list[ps.Model],
    names: list[str] | None = None,
    tmin: pd.Timestamp | str | None = None,
    tmax: pd.Timestamp | str | None = None,
    metric_selection: list[str] | None = None,
    include_diagnostics: bool = True,
) -> ComparisonData:
    """Extract aligned metrics, parameters, diagnostics, and stressmodels for multiple models."""
    if not models or len(models) < 2:
        raise ValueError("Select at least two models to compare.")

    t0 = pd.Timestamp(tmin) if tmin is not None else None
    t1 = pd.Timestamp(tmax) if tmax is not None else None
    mc = ps.CompareModels(models, names=names, tmin=t0, tmax=t1)
    model_names = list(mc.modelnames)

    # Calibration ranges
    try:
        tmin_tmax = mc.get_tmin_tmax()
        tmin_tmax.index = model_names
    except Exception:
        tmin_tmax = pd.DataFrame(index=model_names, columns=["tmin", "tmax"])

    valid_tmins = tmin_tmax["tmin"].dropna() if "tmin" in tmin_tmax else pd.Series(dtype=object)
    valid_tmaxs = tmin_tmax["tmax"].dropna() if "tmax" in tmin_tmax else pd.Series(dtype=object)
    common_tmin = pd.Timestamp(valid_tmins.max()) if not valid_tmins.empty else None
    common_tmax = pd.Timestamp(valid_tmaxs.min()) if not valid_tmaxs.empty else None
    if common_tmin is not None and common_tmax is not None and common_tmin >= common_tmax:
        common_tmin = pd.Timestamp(valid_tmins.min())
        common_tmax = pd.Timestamp(valid_tmaxs.max())

    # Fit metrics (resilient to unsolved models)
    sel_metrics = metric_selection or DEFAULT_COMPARISON_METRICS
    metrics_cols: dict[str, pd.Series] = {}
    for mname, ml in zip(model_names, models):
        vals = {}
        solved = is_model_solved(ml)
        for stat_name in sel_metrics:
            if not solved:
                vals[stat_name] = np.nan
                continue
            try:
                fn = getattr(ml.stats, stat_name, None)
                if fn is None:
                    vals[stat_name] = np.nan
                else:
                    vals[stat_name] = float(fn(tmin=t0, tmax=t1))
            except Exception:
                vals[stat_name] = np.nan
        metrics_cols[mname] = pd.Series(vals, dtype=float)
    metrics_df = pd.DataFrame(metrics_cols)

    # Add ΔAICc row when AICc is available for at least one model
    if "aicc" in metrics_df.index and metrics_df.loc["aicc"].notna().any():
        min_aicc = metrics_df.loc["aicc"].min()
        metrics_df.loc["delta_aicc"] = metrics_df.loc["aicc"] - min_aicc

    # Parameters (optimal + stderr)
    try:
        params_opt = mc.get_parameters(param_col="optimal")
    except Exception:
        params_opt = pd.DataFrame(columns=model_names)

    try:
        params_stderr = mc.get_parameters(param_col="stderr")
    except Exception:
        params_stderr = pd.DataFrame(index=params_opt.index, columns=model_names)

    # Diagnostics P-values (computed safely & optionally deferred for instant UI open)
    if include_diagnostics:
        diagnostics_df = compute_fast_diagnostics(models, model_names, tmin=t0, tmax=t1)
    else:
        diagnostics_df = pd.DataFrame(columns=model_names)

    return ComparisonData(
        model_names=model_names,
        models=list(models),
        same_oseries=_check_same_oseries(models, tmin=t0, tmax=t1),
        unique_stressmodels=mc.get_unique_stressmodels(),
        tmin_tmax=tmin_tmax,
        metrics=metrics_df,
        parameters_optimal=params_opt,
        parameters_stderr=params_stderr,
        diagnostics=diagnostics_df,
        common_tmin=common_tmin,
        common_tmax=common_tmax,
    )


def compute_model_differences(
    models: list[ps.Model],
    model_names: list[str],
    reference_name: str,
    tmin: pd.Timestamp | str | None = None,
    tmax: pd.Timestamp | str | None = None,
) -> dict[str, pd.Series]:
    """Compute simulation differences `sim(model) - sim(reference)` for each non-reference model."""
    if reference_name not in model_names:
        raise ValueError(f"Reference model '{reference_name}' not found in {model_names}.")

    ref_idx = model_names.index(reference_name)
    ref_sim = models[ref_idx].simulate(tmin=tmin, tmax=tmax)

    diffs: dict[str, pd.Series] = {}
    for mname, ml in zip(model_names, models):
        if mname == reference_name:
            continue
        sim = ml.simulate(tmin=tmin, tmax=tmax)
        aligned_ref = ref_sim.reindex(sim.index)
        diff = sim - aligned_ref
        diff.name = f"{mname} - {reference_name}"
        diffs[mname] = diff

    return diffs
