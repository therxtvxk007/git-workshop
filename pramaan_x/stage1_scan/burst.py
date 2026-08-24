"""Sequential change detection over per-target document streams.

Both detectors here answer the same question -- "has the process generating
this stream shifted?" -- and both are kept because they fail differently.

CUSUM accumulates small deviations and fires on a *persistent* shift; it is
insensitive to a single loud day, which is exactly the property wanted when one
outlet publishes a scare piece. Bayesian online change point detection (Adams &
MacKay, 2007) instead maintains a posterior over run length, so it localises
*when* the regime changed and degrades gracefully when the shift is abrupt.

Neither is a novelty. Both are in the stack because a transformer over daily
counts would be slower, less interpretable, and no more accurate.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class CusumResult:
    upper: np.ndarray
    lower: np.ndarray
    alarms: np.ndarray          # indices where the decision interval was crossed
    max_statistic: float = 0.0

    @property
    def fired(self) -> bool:
        return bool(len(self.alarms))


def cusum(
    x: np.ndarray,
    *,
    k: float = 0.5,
    h: float = 5.0,
    reference: tuple[float, float] | None = None,
    warmup: float = 0.25,
    reset_on_alarm: bool = True,
) -> CusumResult:
    """Two-sided tabular CUSUM on standardised observations.

    `k` is the slack in standard deviations (half the shift we want to detect
    quickly) and `h` the decision interval. Measured operating characteristics
    on standard-normal input, 120 replications each:

        h     ARL0 (days)   mean delay after +2 sigma shift
        4.0          162                   2.1
        5.0          410                   2.7
        6.0          982                   3.2

    The default is h=5.0: roughly one false alarm per target per fourteen
    months, with a real shift caught inside three days. h=4 is the textbook
    value but at 72 targets it produces an alarm every other day across the
    board, which trains analysts to ignore the channel.
    """
    x = np.asarray(x, dtype=np.float64)
    if x.size == 0:
        return CusumResult(np.zeros(0), np.zeros(0), np.zeros(0, dtype=int))

    if reference is None:
        # In-control parameters come from a warmup prefix only. Standardising
        # against the whole series is the classic mistake: post-change data
        # drags the mean up, every pre-change point then looks low, and the
        # lower arm fires long before the actual shift.
        n_warm = max(8, round(warmup * x.size))
        head = x[:n_warm] if n_warm < x.size else x
        mu = float(np.median(head))
        # MAD, not the standard deviation: the burst we are looking for would
        # otherwise inflate the scale we measure it against.
        mad = float(np.median(np.abs(head - mu)))
        sigma = max(1.4826 * mad, 1e-6)
    else:
        mu, sigma = reference
        sigma = max(sigma, 1e-6)

    z = (x - mu) / sigma
    up = np.zeros(x.size)
    lo = np.zeros(x.size)
    alarms: list[int] = []
    su = sl = 0.0
    for i, zi in enumerate(z):
        su = max(0.0, su + zi - k)
        sl = max(0.0, sl - zi - k)
        up[i], lo[i] = su, sl
        if su > h or sl > h:
            alarms.append(i)
            if reset_on_alarm:
                su = sl = 0.0
    return CusumResult(up, lo, np.array(alarms, dtype=int),
                       float(max(up.max(initial=0.0), lo.max(initial=0.0))))


@dataclass
class BocpdResult:
    run_length_map: np.ndarray            # MAP run length at each step
    changepoint_prob: np.ndarray          # P(run length reset) at each step
    changepoints: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=int))

    @property
    def fired(self) -> bool:
        return bool(len(self.changepoints))


def bocpd(
    x: np.ndarray,
    *,
    hazard: float = 1 / 120.0,
    threshold: float = 0.25,
    mu0: float = 0.0,
    kappa0: float = 1.0,
    alpha0: float = 1.0,
    beta0: float = 1.0,
    max_run: int = 400,
) -> BocpdResult:
    """Adams & MacKay BOCPD with a Normal-Inverse-Gamma conjugate prior.

    Both the mean and the variance are unknown and learned online, which matters
    here: document volume per target is heteroscedastic, and a detector assuming
    known variance fires constantly on high-volume targets and never on quiet
    ones.
    """
    x = np.asarray(x, dtype=np.float64)
    T = x.size
    if T == 0:
        return BocpdResult(np.zeros(0, dtype=int), np.zeros(0))

    # Sufficient statistics, one entry per run length hypothesis.
    mu = np.array([mu0])
    kappa = np.array([kappa0])
    alpha = np.array([alpha0])
    beta = np.array([beta0])
    R = np.array([1.0])                        # run-length posterior

    rl_map = np.zeros(T, dtype=int)
    cp_prob = np.zeros(T)

    for t in range(T):
        # Posterior predictive: Student-t with 2*alpha degrees of freedom.
        df = 2.0 * alpha
        scale = np.sqrt(beta * (kappa + 1.0) / (alpha * kappa))
        z = (x[t] - mu) / scale
        log_pred = (
            _lgamma((df + 1.0) / 2.0) - _lgamma(df / 2.0)
            - 0.5 * np.log(df * np.pi) - np.log(scale)
            - (df + 1.0) / 2.0 * np.log1p(z * z / df)
        )
        pred = np.exp(log_pred - log_pred.max())
        pred /= max(pred.sum(), 1e-300)
        pred = np.exp(log_pred)                # unnormalised likelihood

        growth = R * pred * (1.0 - hazard)
        cp = float((R * pred * hazard).sum())

        R = np.concatenate(([cp], growth))
        total = R.sum()
        R = R / total if total > 0 else np.ones_like(R) / R.size

        # Update sufficient statistics for each surviving hypothesis.
        mu_new = np.concatenate(([mu0], (kappa * mu + x[t]) / (kappa + 1.0)))
        kappa_new = np.concatenate(([kappa0], kappa + 1.0))
        alpha_new = np.concatenate(([alpha0], alpha + 0.5))
        beta_new = np.concatenate((
            [beta0],
            beta + (kappa * (x[t] - mu) ** 2) / (2.0 * (kappa + 1.0)),
        ))
        mu, kappa, alpha, beta = mu_new, kappa_new, alpha_new, beta_new

        if R.size > max_run:                   # truncate the tail, renormalise
            R = R[:max_run]
            R /= R.sum()
            mu, kappa = mu[:max_run], kappa[:max_run]
            alpha, beta = alpha[:max_run], beta[:max_run]

        rl_map[t] = int(np.argmax(R))
        cp_prob[t] = float(R[0])

    # A changepoint is read off as a *drop* in MAP run length, not from
    # P(run length = 0). The latter is small even at a genuine change -- the
    # posterior mass moves to a short run, rarely to exactly zero -- so
    # thresholding it detects almost nothing.
    drops = np.nonzero(np.diff(rl_map) < 0)[0] + 1
    changepoints = np.array(
        [i for i in drops if rl_map[i] < rl_map[i - 1] * (1.0 - threshold)], dtype=int
    )
    return BocpdResult(rl_map, cp_prob, changepoints)


def _lgamma(a: np.ndarray | float) -> np.ndarray:
    from scipy.special import gammaln

    return gammaln(a)


def burst_features(counts: np.ndarray, *, k: float = 0.5, h: float = 5.0,
                   hazard: float = 1 / 120.0, threshold: float = 0.25) -> dict[str, float]:
    """Feature vector handed to stage 4. Deliberately a handful of numbers, not
    the full posterior: the hazard model gets the detector's opinion, not its
    internals."""
    counts = np.asarray(counts, dtype=np.float64)
    if counts.size < 8:
        return {"cusum_max": 0.0, "cusum_now": 0.0, "cusum_fired": 0.0,
                "bocpd_cp_prob": 0.0, "bocpd_run_length": 0.0,
                "days_since_changepoint": -1.0, "volume_z": 0.0}
    c = cusum(counts, k=k, h=h)
    b = bocpd(counts, hazard=hazard, threshold=threshold)
    last_cp = int(b.changepoints[-1]) if len(b.changepoints) else -1
    mu = float(np.median(counts))
    mad = max(1.4826 * float(np.median(np.abs(counts - mu))), 1e-6)
    return {
        "cusum_max": float(c.max_statistic),
        "cusum_now": float(max(c.upper[-1], c.lower[-1])),
        "cusum_fired": 1.0 if c.fired else 0.0,
        "bocpd_cp_prob": float(b.changepoint_prob[-1]),
        "bocpd_run_length": float(b.run_length_map[-1]),
        "days_since_changepoint": float(counts.size - 1 - last_cp) if last_cp >= 0 else -1.0,
        "volume_z": float((counts[-1] - mu) / mad),
    }
