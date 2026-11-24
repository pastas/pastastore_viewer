# -*- coding: utf-8 -*-
"""Unit tests for model comparison, scenario simulation, ensemble forecasting, and Pro gating."""

from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pastas as ps
import pytest

from license_manager import FEATURE_PRO
from model_analysis import (
    ScenarioConfig,
    StressOverride,
    align_historical_ensembles,
    build_comparison_data,
    build_historical_analogue_ensemble,
    build_synthetic_forecast,
    can_post_process_forecast,
    compute_model_differences,
    get_model_common_stress_range,
    get_stressmodel_inputs,
    has_parameter_covariance,
    is_model_solved,
    load_ensemble_csv,
    normalize_forecast_dict,
    run_ensemble_forecast,
    run_scenario_simulation,
)


def _make_synthetic_recharge_model(
    name: str = "ml_test",
    rfunc=None,
    with_noise: bool = True,
    solve: bool = True,
    seed: int = 42,
):
    """Build a deterministic synthetic Pastas RechargeModel spanning 2015-2023."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2015-01-01", "2023-12-31", freq="D")
    n = len(idx)

    # Seasonal precipitation and evaporation
    doy = idx.dayofyear.to_numpy()
    prec = pd.Series(
        np.maximum(0.0, 2.2 + 0.8 * np.cos(2 * np.pi * doy / 365.25) + rng.normal(0, 1.5, n)),
        index=idx,
        name="prec_station",
    )
    evap = pd.Series(
        np.maximum(0.1, 1.5 - 1.2 * np.cos(2 * np.pi * doy / 365.25) + rng.normal(0, 0.2, n)),
        index=idx,
        name="evap_station",
    )

    # Synthetic groundwater head driven by smoothed net recharge over 2018-2021
    net = (prec - 0.8 * evap).rolling(30, min_periods=1).mean()
    obs_idx = pd.date_range("2018-01-01", "2021-12-31", freq="7D")
    head = pd.Series(
        10.0 + 0.35 * net.reindex(obs_idx).to_numpy() + rng.normal(0, 0.02, len(obs_idx)),
        index=obs_idx,
        name="obs_well",
    )

    ml = ps.Model(head, name=name)
    sm = ps.RechargeModel(
        prec,
        evap,
        rfunc=rfunc if rfunc is not None else ps.Exponential(),
        name="recharge",
    )
    ml.add_stressmodel(sm)
    if with_noise:
        ml.add_noisemodel(ps.ArNoiseModel())

    if solve:
        ml.solve(tmin="2018-01-01", tmax="2021-12-31", report=False)

    return ml, prec, evap, head


@pytest.mark.unit
class TestScenarioSimulation:
    """Tests for non-destructive period extension and stress-override simulations."""

    def test_simulate_longer_period_does_not_mutate_model(self):
        ml, _, _, _ = _make_synthetic_recharge_model()
        orig_tmin = ml.settings["tmin"]
        orig_tmax = ml.settings["tmax"]
        orig_sim = ml.simulate().copy()

        # Simulate beyond calibration range (2017 -> 2023)
        cfg = ScenarioConfig(
            name="Extended",
            tmin="2017-01-01",
            tmax="2023-06-30",
        )
        res = run_scenario_simulation(ml, cfg, baseline_sim=orig_sim)

        assert res.simulation.index.min() == pd.Timestamp("2017-01-01")
        assert res.simulation.index.max() == pd.Timestamp("2023-06-30")
        assert not res.simulation.isna().any()
        assert "recharge" in res.contributions
        # Original model must remain unchanged
        assert ml.settings["tmin"] == orig_tmin
        assert ml.settings["tmax"] == orig_tmax
        assert np.allclose(ml.simulate().values, orig_sim.values)

    def test_stress_override_scale_and_splice_date(self):
        ml, _, _, _ = _make_synthetic_recharge_model(with_noise=False)
        base_cfg = ScenarioConfig(name="Base", tmin="2019-01-01", tmax="2021-12-31")
        base_res = run_scenario_simulation(ml, base_cfg)

        # Double precipitation starting 2020-07-01
        scen_cfg = ScenarioConfig(
            name="WetFrom2020",
            tmin="2019-01-01",
            tmax="2021-12-31",
            overrides=[
                StressOverride(
                    sm_name="recharge",
                    arg_name="prec",
                    index=0,
                    mode="original",
                    scale=2.0,
                    apply_from="2020-07-01",
                )
            ],
        )
        scen_res = run_scenario_simulation(ml, scen_cfg, baseline_sim=base_res.simulation)

        # Before split date, scenario must match baseline exactly
        before = scen_res.difference.loc[:"2020-06-30"]
        after = scen_res.difference.loc["2020-07-15":]
        assert np.allclose(before.values, 0.0, atol=1e-9)
        assert np.abs(after.mean()) > 0.01

    def test_stress_override_from_store_and_constant(self):
        ml, prec, _, _ = _make_synthetic_recharge_model(with_noise=False)
        alt_prec = prec * 0.5
        alt_prec.name = "dry_prec"

        mock_store = MagicMock()
        mock_store.get_stresses.return_value = alt_prec

        base_sim = ml.simulate(tmin="2019-01-01", tmax="2021-12-31")
        cfg = ScenarioConfig(
            name="DryStoreStress",
            tmin="2019-01-01",
            tmax="2021-12-31",
            overrides=[
                StressOverride(
                    sm_name="recharge",
                    arg_name="prec",
                    index=0,
                    mode="store",
                    store_stress_name="dry_prec",
                ),
                StressOverride(
                    sm_name="recharge",
                    arg_name="evap",
                    index=1,
                    mode="constant",
                    constant_value=2.0,
                ),
            ],
        )
        res = run_scenario_simulation(ml, cfg, store=mock_store, baseline_sim=base_sim)
        mock_store.get_stresses.assert_called_once_with("dry_prec")
        assert res.difference is not None
        assert res.difference.mean() < 0.0  # Less rain + high evap -> lower head

    def test_disable_stressmodel_zeroes_contribution(self):
        ml, _, _, _ = _make_synthetic_recharge_model(with_noise=False)
        cfg = ScenarioConfig(
            name="NoRecharge",
            tmin="2019-01-01",
            tmax="2020-12-31",
            disabled_stressmodels=["recharge"],
        )
        res = run_scenario_simulation(ml, cfg)
        assert np.allclose(res.contributions["recharge"].values, 0.0, atol=1e-9)

    def test_common_stress_range_and_inputs_introspection(self):
        ml, _, _, _ = _make_synthetic_recharge_model(solve=False)
        inputs = get_stressmodel_inputs(ml)
        assert [(i.sm_name, i.arg_name) for i in inputs] == [
            ("recharge", "prec"),
            ("recharge", "evap"),
        ]
        tmin, tmax = get_model_common_stress_range(ml)
        assert tmin == pd.Timestamp("2015-01-01")
        assert tmax == pd.Timestamp("2023-12-31")

    def test_ci_simulation_when_pcov_available(self):
        ml, _, _, _ = _make_synthetic_recharge_model(with_noise=False)
        assert has_parameter_covariance(ml)
        cfg = ScenarioConfig(
            name="WithCI",
            tmin="2020-01-01",
            tmax="2020-06-30",
            compute_ci=True,
            ci_samples=20,
        )
        res = run_scenario_simulation(ml, cfg)
        assert res.ci is not None
        assert res.ci.shape[1] == 2
        assert (res.ci.iloc[:, 1] >= res.ci.iloc[:, 0]).all()


@pytest.mark.unit
class TestEnsembleForecasting:
    """Tests for historical analogue ensembles, CSV loading, and `ps.forecast.forecast`."""

    def test_historical_analogue_ensemble_preserves_common_years(self):
        ml, prec, evap, _ = _make_synthetic_recharge_model()
        aligned = align_historical_ensembles(
            {("recharge", "prec"): prec, ("recharge", "evap"): evap},
            tmin="2022-01-01",
            tmax="2022-01-30",
            freq="D",
        )
        df_p = aligned[("recharge", "prec")]
        df_e = aligned[("recharge", "evap")]
        assert list(df_p.columns) == list(df_e.columns)
        assert df_p.shape[0] == 30
        assert df_p.shape[1] >= 5  # Years 2015..2021
        assert df_p.index[0] == pd.Timestamp("2022-01-01")
        assert df_p.index[-1] == pd.Timestamp("2022-01-30")

    def test_run_ensemble_forecast_with_ar1_post_processing_and_param_uncertainty(self):
        ml, prec, evap, _ = _make_synthetic_recharge_model(with_noise=True, solve=True)
        assert can_post_process_forecast(ml)

        aligned = align_historical_ensembles(
            {("recharge", "prec"): prec, ("recharge", "evap"): evap},
            tmin="2022-01-01",
            tmax="2022-01-30",
            freq="D",
        )
        forecasts = {
            "recharge": {
                "prec": aligned[("recharge", "prec")],
                "evap": aligned[("recharge", "evap")],
            }
        }

        res = run_ensemble_forecast(
            ml,
            forecasts,
            tmin="2022-01-01",
            tmax="2022-01-30",
            n_param_samples=5,
            post_process=True,
            seed=123,
        )

        assert res.n_ensemble_members == aligned[("recharge", "prec")].shape[1]
        assert res.n_param_samples == 5
        assert res.post_processed is True
        assert len(res.overall_mean) == 30
        assert (res.overall_std >= 0.0).all()
        assert (res.summary["ci95_high"] >= res.summary["ci95_low"]).all()

        # Exceedance probability checks
        med = float(res.overall_mean.median())
        prob_below = res.compute_exceedance_probability(med, direction="below")
        prob_above = res.compute_exceedance_probability(med, direction="above")
        assert ((prob_below["prob_parametric"] >= 0.0) & (prob_below["prob_parametric"] <= 1.0)).all()
        assert np.allclose(
            prob_below["prob_parametric"] + prob_above["prob_parametric"], 1.0, atol=1e-6
        )

    def test_load_ensemble_csv_and_broadcast_deterministic_stress(self, temp_dir):
        ml, _, evap, _ = _make_synthetic_recharge_model(with_noise=False, solve=True)
        idx = pd.date_range("2022-01-01", periods=15, freq="D")
        df_ens = pd.DataFrame(
            {"m1": np.linspace(0, 5, 15), "m2": np.linspace(5, 0, 15), "m3": np.ones(15) * 2.0},
            index=idx,
        )
        csv_path = f"{temp_dir}/prec_ens.csv"
        df_ens.to_csv(csv_path)

        loaded = load_ensemble_csv(csv_path)
        assert loaded.shape == (15, 3)

        evap_const = build_synthetic_forecast(
            evap, tmin="2022-01-01", tmax="2022-01-15", mode="constant", constant_value=1.0
        )
        assert evap_const.shape == (15, 1)

        # Broadcast 1-member evap to match 3-member prec
        norm_dict = normalize_forecast_dict(
            ml,
            {"recharge": {"prec": loaded, "evap": evap_const}},
            tmin="2022-01-01",
            tmax="2022-01-15",
        )
        assert norm_dict["recharge"]["prec"].shape == (15, 3)
        assert norm_dict["recharge"]["evap"].shape == (15, 3)

        res = run_ensemble_forecast(
            ml,
            norm_dict,
            tmin="2022-01-01",
            tmax="2022-01-15",
            post_process=False,
        )
        assert res.n_ensemble_members == 3
        assert len(res.overall_mean) == 15

    def test_unsolved_model_and_missing_noisemodel_errors(self):
        ml_unsolved, prec, evap, _ = _make_synthetic_recharge_model(solve=False)
        assert not is_model_solved(ml_unsolved)
        fc = {
            "recharge": {
                "prec": build_synthetic_forecast(prec, "2022-01-01", "2022-01-10", mode="zero"),
                "evap": build_synthetic_forecast(evap, "2022-01-01", "2022-01-10", mode="zero"),
            }
        }
        with pytest.raises(ValueError, match="not solved"):
            run_ensemble_forecast(ml_unsolved, fc)

        ml_no_noise, prec2, evap2, _ = _make_synthetic_recharge_model(with_noise=False, solve=True)
        assert not can_post_process_forecast(ml_no_noise)
        with pytest.raises(ValueError, match="ArNoiseModel"):
            run_ensemble_forecast(ml_no_noise, fc, post_process=True)


@pytest.mark.unit
class TestModelComparison:
    """Tests for `build_comparison_data` and `compute_model_differences`."""

    def test_compare_two_models_metrics_params_and_diff(self):
        ml_exp, _, _, _ = _make_synthetic_recharge_model(
            name="model_exp", rfunc=ps.Exponential(), with_noise=False
        )
        ml_gam, _, _, _ = _make_synthetic_recharge_model(
            name="model_gam", rfunc=ps.Gamma(), with_noise=False
        )

        comp = build_comparison_data([ml_exp, ml_gam])
        assert comp.model_names == ["model_exp", "model_gam"]
        assert comp.same_oseries is True
        assert "recharge" in comp.unique_stressmodels
        assert "rsq" in comp.metrics.index
        assert "delta_aicc" in comp.metrics.index
        # Best model has delta_aicc == 0.0
        assert np.isclose(comp.metrics.loc["delta_aicc"].min(), 0.0)
        assert "recharge_A" in comp.parameters_optimal.index
        assert comp.parameters_stderr.shape == comp.parameters_optimal.shape

        diffs = compute_model_differences(
            [ml_exp, ml_gam], ["model_exp", "model_gam"], reference_name="model_exp"
        )
        assert list(diffs.keys()) == ["model_gam"]
        assert not diffs["model_gam"].empty

    def test_compare_handles_unsolved_model_gracefully(self):
        ml1, _, _, _ = _make_synthetic_recharge_model(name="solved_m", solve=True)
        ml2, _, _, _ = _make_synthetic_recharge_model(name="unsolved_m", solve=False)

        comp = build_comparison_data([ml1, ml2])
        assert pd.notna(comp.metrics.loc["rsq", "solved_m"])
        assert pd.isna(comp.metrics.loc["rsq", "unsolved_m"])

    def test_compare_requires_at_least_two_models(self):
        ml1, _, _, _ = _make_synthetic_recharge_model(name="only_one")
        with pytest.raises(ValueError, match="at least two"):
            build_comparison_data([ml1])

    def test_compute_fast_acf_matches_pastas_and_is_fast(self):
        import time

        from model_analysis import compute_fast_acf

        rng = np.random.default_rng(7)

        # 1. Machine-precision parity against pastas.stats.acf on irregular series
        idx_small = pd.Timestamp("2020-01-01") + pd.to_timedelta(
            np.cumsum(rng.integers(12, 60, size=220)), unit="h"
        )
        ser_small = pd.Series(np.cumsum(rng.normal(0, 1, size=220)), index=idx_small)

        r_pastas = ps.stats.acf(ser_small, lags=120, full_output=True)
        r_fast = compute_fast_acf(ser_small, max_lags=120)

        assert r_pastas.index.equals(r_fast.index)
        assert np.allclose(r_pastas["acf"].values, r_fast["acf"].values, atol=1e-12)
        assert np.allclose(r_pastas["conf"].values, r_fast["conf"].values, atol=1e-12)
        assert np.allclose(r_pastas["n"].values, r_fast["n"].values, atol=1e-10)

        # 2. Speed on 3,000 irregular timestamps spanning ~10 years
        base = pd.Timestamp("2014-01-01")
        offsets_hours = np.cumsum(rng.integers(12, 60, size=3000))
        idx = base + pd.to_timedelta(offsets_hours, unit="h")
        vals = np.cumsum(rng.normal(0, 1, size=3000))
        ser = pd.Series(vals, index=idx, name="irregular_res")

        t0 = time.perf_counter()
        acf_df = compute_fast_acf(ser, max_lags=365)
        elapsed = time.perf_counter() - t0

        assert elapsed < 2.0
        assert not acf_df.empty
        assert {"acf", "conf", "n"}.issubset(acf_df.columns)


@pytest.mark.unit
class TestProLicenseGating:
    """Ensure all three new model features require FEATURE_PRO."""

    def test_all_new_actions_require_pro_license(self):
        try:
            from pastastore_viewer.pastastore_viewer import PastastoreViewer
        except ImportError:
            from pastastore_viewer import PastastoreViewer

        viewer = PastastoreViewer.__new__(PastastoreViewer)
        viewer.store = MagicMock()
        viewer.iface = MagicMock()
        viewer._require_feature = MagicMock(return_value=False)

        viewer.open_simulation_dialog("m1")
        viewer.open_forecast_dialog("m1")
        viewer.open_compare_models_dialog(["m1", "m2"])
        viewer.open_mpl_compare_models_plot(["m1", "m2"])

        assert viewer._require_feature.call_count == 4
        for call in viewer._require_feature.call_args_list:
            assert call.args[0] == FEATURE_PRO
        viewer.store.get_models.assert_not_called()


@pytest.mark.unit
class TestFillBetweenHelper:
    """Regression tests for split-brain pyqtgraph FillBetweenItem curve class mismatch."""

    def test_uses_curve_class_from_fill_between_module(self):
        import sys
        import types

        from plot_toolbar import create_fill_between_item

        class SitePlotDataItem:
            def __init__(self, x, y):
                self.x = x
                self.y = y

        class BundledPlotDataItem:
            def __init__(self, x, y):
                self.x = x
                self.y = y

        class StrictFillBetweenItem:
            def __init__(self, c1, c2, brush=None):
                if not isinstance(c1, SitePlotDataItem) or not isinstance(c2, SitePlotDataItem):
                    raise TypeError("Curves must be PlotDataItem or PlotCurveItem.")
                self.c1 = c1
                self.c2 = c2
                self.brush = brush

        fake_mod_name = "_fake_site_pyqtgraph_fillbetween"
        fake_mod = types.ModuleType(fake_mod_name)
        fake_mod.PlotDataItem = SitePlotDataItem
        StrictFillBetweenItem.__module__ = fake_mod_name
        sys.modules[fake_mod_name] = fake_mod

        try:
            fake_pg = types.SimpleNamespace(
                FillBetweenItem=StrictFillBetweenItem,
                PlotDataItem=BundledPlotDataItem,
                mkPen=lambda *a, **kw: None,
            )
            item = create_fill_between_item(
                fake_pg, [1.0, 2.0, 3.0], [2.0, 3.0, 4.0], [0.0, 1.0, 2.0], brush="red"
            )
            assert isinstance(item, StrictFillBetweenItem)
            assert isinstance(item.c1, SitePlotDataItem)
            assert isinstance(item.c2, SitePlotDataItem)
        finally:
            sys.modules.pop(fake_mod_name, None)

    def test_fallback_when_fill_between_raises_typeerror(self):
        import types

        from plot_toolbar import create_fill_between_item

        class BrokenFill:
            def __init__(self, *args, **kwargs):
                raise TypeError("Curves must be PlotDataItem or PlotCurveItem.")

        fake_pg = types.SimpleNamespace(
            FillBetweenItem=BrokenFill,
            PlotDataItem=lambda x, y: (x, y),
            mkPen=lambda *a, **kw: None,
        )
        item = create_fill_between_item(
            fake_pg, [1.0, 2.0, 3.0], [2.0, 3.0, 4.0], [0.0, 1.0, 2.0], brush="blue"
        )
        assert item is not None
