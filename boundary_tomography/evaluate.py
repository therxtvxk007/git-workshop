"""Metrics and the decisive tests: held-out tracer, placebo, type classification."""

from __future__ import annotations

import numpy as np

from . import core, inverse
from .scenarios import PROFILES, TRACERS


def boundary_error(ctrl_est, ctrl_true, ny):
    """Row-wise horizontal distance between two curves, in cells."""
    a = core.curve_from_controls(ctrl_est, ny)[0]
    b = core.curve_from_controls(ctrl_true, ny)[0]
    d = np.abs(a - b)
    return dict(mae=float(d.mean()), p90=float(np.percentile(d, 90)),
                max=float(d.max()))


def tau_error(tau_est, tau_true):
    """Absolute error, and the rank agreement that drives type classification."""
    a, b = np.asarray(tau_est, float), np.asarray(tau_true, float)
    ra = np.argsort(np.argsort(a)).astype(float)
    rb = np.argsort(np.argsort(b)).astype(float)
    rho = (np.corrcoef(ra, rb)[0, 1] if a.std() > 1e-9 and b.std() > 1e-9
           else np.nan)
    return dict(mae=float(np.abs(a - b).mean()), spearman=float(rho))


def timing_error(res, truth, cfg):
    """Compare the *activity schedule*, not the raw endpoints.

    An always-on interface has no identifiable t_on or t_off -- any pair outside
    the observation window fits equally well -- so scoring endpoints directly
    would punish a correct answer.  The schedule is what the data constrain.
    """
    est = (np.ones(cfg.n_epochs) if not res["fit_timing"]
           else core.activity(cfg.epochs, res["t_on"], res["t_off"]))
    return dict(schedule_mae=float(np.abs(est - truth["acts"]).mean()),
                est=est.tolist(), true=truth["acts"].tolist())


# --------------------------------------------------------------------------
# what kind of boundary was it?
# --------------------------------------------------------------------------
def type_features(tau, acts):
    """Permeability profile plus how the interface behaves at the endpoints.

    The profile is centred, so what is compared is the *shape* -- which processes
    the interface stopped relative to the others -- not its overall strength.
    """
    tau = np.asarray(tau, float)
    return np.concatenate([tau - tau.mean(), [acts[0], acts[-1]]])


def classify_type(tau, acts):
    """Nearest interface-type template in profile-shape space."""
    f = type_features(tau, acts)
    out = {}
    for name, spec in PROFILES.items():
        if name == "null":
            continue
        n_ep = len(acts)
        a = (np.ones(n_ep) if spec["window"] is None
             else core.activity(np.arange(n_ep, dtype=float), *spec["window"]))
        out[name] = float(np.linalg.norm(f - type_features(spec["tau"], a)))
    best = min(out, key=out.get)
    return best, out


# --------------------------------------------------------------------------
# decisive test: predict a tracer that was never used to fit the boundary
# --------------------------------------------------------------------------
def heldout_tracer(data, res, held):
    """Freeze the recovered geometry and chronology, fit only tau for a tracer
    that took no part in the fit, and ask what the interface buys on it.

    The comparison is against the same tracer's best *no-interface* model, so
    the number reported is the variance explained by the recovered boundary
    alone.
    """
    cfg, obs = data["cfg"], data["obs"][:, held: held + 1]
    K = np.ones(1)

    def f(z):
        sse, tss = inverse.evaluate(cfg, obs, res["ctrl"], [inverse._to_tau(z[0])],
                                    K, res["t_on"], res["t_off"])
        return inverse._obj(sse, tss)

    from scipy.optimize import minimize
    r = minimize(f, [0.0], method="Nelder-Mead",
                 options=dict(maxfev=35, xatol=1e-2, fatol=1e-8,
                              initial_simplex=np.array([[-1.2], [1.2]])))
    tau_h = float(inverse._to_tau(r.x[0]))
    sse, tss = inverse.evaluate(cfg, obs, res["ctrl"], [tau_h], K,
                                res["t_on"], res["t_off"])
    sse0, tss0 = inverse.evaluate(cfg, obs, None, None, K)
    r2, r2_0 = 1 - sse[0] / tss[0], 1 - sse0[0] / tss0[0]
    return dict(tracer=TRACERS[held], tau_hat=tau_h,
                tau_true=float(data["truth"]["tau"][held]),
                r2=float(r2), r2_no_interface=float(r2_0),
                delta_r2=float(r2 - r2_0))


def summarise(data, res, label):
    """Score one fit against the truth, over whichever tracers it actually used.

    Interface type can only be called when every tracer is present: the
    classifier compares the *shape* of the permeability profile across tracers,
    which a single-tracer or held-out fit does not have.
    """
    cfg, truth = data["cfg"], data["truth"]
    idx = list(res.get("tracers", range(cfg.M)))
    tau_true = np.asarray(truth["tau"], float)[idx]
    acts = (np.ones(cfg.n_epochs) if not res["fit_timing"]
            else core.activity(cfg.epochs, res["t_on"], res["t_off"]))
    complete = len(idx) == cfg.M
    kind, dists = classify_type(res["tau"], acts) if complete else (None, {})
    return dict(
        label=label, scenario=data["scenario"], seed=data["seed"],
        tracers=[TRACERS[i] for i in idx],
        boundary=boundary_error(res["ctrl"], truth["ctrl"], cfg.ny),
        tau=tau_error(res["tau"], tau_true),
        timing=timing_error(res, truth, cfg),
        tau_est=np.asarray(res["tau"], float).tolist(),
        tau_true=tau_true.tolist(),
        gain=float(res["gain"]), objective=float(res["objective"]),
        r2=np.asarray(res["r2"], float).tolist(),
        predicted_type=kind, type_distances=dists,
        correct_type=(kind == data["scenario"]) if complete else None,
    )
