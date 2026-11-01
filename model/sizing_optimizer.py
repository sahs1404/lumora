"""
Lumora - stochastic sizing optimizer for a solar + battery + diesel mini-grid.

What it does
------------
Picks PV (kW), battery (kWh) and diesel (kW) ONCE, then dispatches every sampled
demand scenario hour by hour. Minimises annualised cost of power subject to a
chance constraint:

    unmet demand <= (1 - reliability) of daily demand
    in at least `prob` of the demand scenarios

This is a two-stage stochastic MILP (sample average approximation):
  stage 1 (here-and-now): system size
  stage 2 (wait-and-see): hourly dispatch per scenario
A binary z_s per scenario lets up to (1 - prob) of scenarios violate the
reliability target (big-M chance constraint).

Why it matters for the pitch
----------------------------
Tools like HOMER size for ONE assumed demand. Lumora sizes for the whole
forecast range. `compare_designs()` shows the difference out of sample:
a design sized for the P50 forecast vs. a design sized across scenarios,
both tested on 1,000 fresh scenarios.

Inputs it expects from the rest of Lumora
-----------------------------------------
- Demand model (Sahasra): P10/P50/P90 kWh per customer per month, number of
  customers, share of daytime business load.
- Energy params (Manas): solar yield, costs, battery and diesel parameters.
  ALL COST NUMBERS BELOW ARE ILLUSTRATIVE PLACEHOLDERS. Replace them with
  ESMAP / AMDA benchmark values before quoting any result.

Simplifications (say so in the pitch if asked)
----------------------------------------------
- Each scenario is one representative day (24 h) with a cyclic battery.
  Extend to multi-day / seasonal blocks if time allows.
- Sizes are continuous; round up to real component sizes afterwards.

Monte Carlo is used twice:
  1. Sample average approximation: the chance-constrained problem
       min E[cost]  s.t.  Pr(unmet <= (1-alpha) * demand) >= 1 - eps
     is replaced by its sampled version over N Monte Carlo scenarios.
  2. Out-of-sample validation: the chosen design is simulated on N' = 1,000
     fresh scenarios; we report reliability with a 95% confidence interval
     and the P10/P50/P90 of the daily cost of power.
The full formulation is in the Lumora concept note.

Run:  pip install "pulp>=2.8,<3" highspy numpy   (PuLP 3+ changed its API)
      python sizing_optimizer.py
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

import numpy as np
import pulp

HOURS = 24


# ----------------------------------------------------------------------------
# Parameters
# ----------------------------------------------------------------------------
@dataclass
class Costs:
    """ILLUSTRATIVE PLACEHOLDERS - replace with ESMAP / AMDA benchmarks (Manas)."""
    pv_capex_per_kw: float = 900.0         # USD per kWp installed
    batt_capex_per_kwh: float = 350.0      # USD per kWh usable
    diesel_capex_per_kw: float = 450.0     # USD per kW
    fuel_price_per_l: float = 1.20         # USD per litre
    diesel_l_per_kwh: float = 0.30         # litres per kWh generated
    fixed_om_frac: float = 0.02            # yearly O&M as share of capex
    pv_life_yr: int = 20
    batt_life_yr: int = 10
    diesel_life_yr: int = 10
    discount_rate: float = 0.10
    unmet_penalty_per_kwh: float = 0.50    # small, steers solver away from unmet load


@dataclass
class Tech:
    batt_eff_charge: float = 0.95
    batt_eff_discharge: float = 0.95
    batt_min_soc: float = 0.20             # share of capacity
    batt_c_rate: float = 0.5               # max kW per kWh of capacity
    solar_yield_kwh_per_kwp_day: float = 5.0  # typical East African value; check per site


@dataclass
class Scenario:
    demand_kw: np.ndarray                  # shape (24,)
    solar_kw_per_kwp: np.ndarray           # shape (24,)

    @property
    def daily_kwh(self) -> float:
        return float(self.demand_kw.sum())


@dataclass
class Design:
    pv_kw: float
    batt_kwh: float
    diesel_kw: float
    label: str = ""


# ----------------------------------------------------------------------------
# Profiles and scenarios
# ----------------------------------------------------------------------------
def solar_shape() -> np.ndarray:
    """Normalised PV output shape, sums to 1 over the day (06:00-18:00 half-sine)."""
    h = np.arange(HOURS) + 0.5
    s = np.clip(np.sin(np.pi * (h - 6) / 12), 0, None)
    return s / s.sum()


def load_shape(business_share: float) -> np.ndarray:
    """Normalised daily load shape mixing household (evening peak) and business (daytime)."""
    h = np.arange(HOURS)
    household = 0.2 + 0.3 * np.exp(-((h - 7) ** 2) / 4) + 1.0 * np.exp(-((h - 20) ** 2) / 5)
    business = np.where((h >= 8) & (h <= 17), 1.0, 0.05)
    household, business = household / household.sum(), business / business.sum()
    return (1 - business_share) * household + business_share * business


def lognormal_from_quantiles(p10: float, p50: float, p90: float):
    """Lognormal (mu, sigma) matching the median and the P10-P90 spread."""
    z90 = 1.2815515655446004
    mu = np.log(p50)
    sigma = (np.log(p90) - np.log(p10)) / (2 * z90)
    return mu, max(sigma, 1e-6)


def sample_scenarios(
    n_customers: int,
    kwh_per_customer_month: tuple[float, float, float],
    business_share: float,
    n: int,
    tech: Tech,
    seed: int = 0,
    extra_load_kw: np.ndarray | None = None,
) -> list[Scenario]:
    """Sample `n` one-day scenarios: uncertain demand level x day-to-day solar variation."""
    rng = np.random.default_rng(seed)
    mu, sigma = lognormal_from_quantiles(*kwh_per_customer_month)
    shape_l, shape_s = load_shape(business_share), solar_shape()
    out = []
    for _ in range(n):
        monthly = rng.lognormal(mu, sigma)
        day_noise = rng.normal(1.0, 0.08)                      # day-to-day demand wobble
        daily_kwh = n_customers * monthly / 30.0 * max(day_noise, 0.5)
        demand = daily_kwh * shape_l
        if extra_load_kw is not None:
            demand = demand + extra_load_kw
        sun = tech.solar_yield_kwh_per_kwp_day * float(np.clip(rng.normal(1.0, 0.15), 0.4, 1.3))
        out.append(Scenario(demand_kw=demand, solar_kw_per_kwp=sun * shape_s))
    return out


def median_scenario(scenarios: list[Scenario]) -> Scenario:
    """Single 'P50' scenario, the way a deterministic tool would size."""
    d = np.median([s.demand_kw for s in scenarios], axis=0)
    sol = np.median([s.solar_kw_per_kwp for s in scenarios], axis=0)
    return Scenario(demand_kw=d, solar_kw_per_kwp=sol)


# ----------------------------------------------------------------------------
# Economics helpers
# ----------------------------------------------------------------------------
def crf(rate: float, years: int) -> float:
    """Capital recovery factor: turns capex into an equal yearly payment."""
    return rate * (1 + rate) ** years / ((1 + rate) ** years - 1)


def annual_capex(d: Design, c: Costs) -> float:
    pv = d.pv_kw * c.pv_capex_per_kw
    bt = d.batt_kwh * c.batt_capex_per_kwh
    dg = d.diesel_kw * c.diesel_capex_per_kw
    return (pv * (crf(c.discount_rate, c.pv_life_yr) + c.fixed_om_frac)
            + bt * (crf(c.discount_rate, c.batt_life_yr) + c.fixed_om_frac)
            + dg * (crf(c.discount_rate, c.diesel_life_yr) + c.fixed_om_frac))


# ----------------------------------------------------------------------------
# The optimizer
# ----------------------------------------------------------------------------
def optimize_sizing(
    scenarios: list[Scenario],
    costs: Costs = Costs(),
    tech: Tech = Tech(),
    reliability: float = 0.95,
    prob: float = 0.90,
    time_limit_s: int = 120,
    label: str = "stochastic",
) -> Design:
    """Two-stage stochastic MILP with a chance constraint on unmet demand."""
    S, T = range(len(scenarios)), range(HOURS)
    m = pulp.LpProblem("lumora_sizing", pulp.LpMinimize)

    pv = pulp.LpVariable("pv_kw", lowBound=0)
    bt = pulp.LpVariable("batt_kwh", lowBound=0)
    dg = pulp.LpVariable("diesel_kw", lowBound=0)

    V = lambda name: pulp.LpVariable.dicts(name, (S, T), lowBound=0)
    curt, ch, dis, gen, unmet = V("curt"), V("ch"), V("dis"), V("gen"), V("unmet")
    soc = pulp.LpVariable.dicts("soc", (S, range(HOURS + 1)), lowBound=0)
    z = pulp.LpVariable.dicts("violate", S, cat="Binary")

    for s in S:
        sc = scenarios[s]
        for t in T:
            # energy balance
            m += (pv * float(sc.solar_kw_per_kwp[t]) - curt[s][t] - ch[s][t]
                  + dis[s][t] + gen[s][t] + unmet[s][t] == float(sc.demand_kw[t]))
            m += curt[s][t] <= pv * float(sc.solar_kw_per_kwp[t])
            # battery
            m += soc[s][t + 1] == (soc[s][t] + tech.batt_eff_charge * ch[s][t]
                                   - dis[s][t] * (1.0 / tech.batt_eff_discharge))
            m += soc[s][t + 1] <= bt
            m += soc[s][t + 1] >= tech.batt_min_soc * bt
            m += ch[s][t] <= tech.batt_c_rate * bt
            m += dis[s][t] <= tech.batt_c_rate * bt
            # diesel
            m += gen[s][t] <= dg
        m += soc[s][0] == soc[s][HOURS]                       # cyclic day
        m += soc[s][0] >= tech.batt_min_soc * bt
        # chance constraint (big-M = full daily demand)
        D = sc.daily_kwh
        m += pulp.lpSum(unmet[s][t] for t in T) <= (1 - reliability) * D + D * z[s]
    m += pulp.lpSum(z[s] for s in S) <= int(np.floor((1 - prob) * len(scenarios)))

    n = len(scenarios)
    fuel = costs.fuel_price_per_l * costs.diesel_l_per_kwh
    expected_daily_opex = pulp.lpSum(
        fuel * gen[s][t] + costs.unmet_penalty_per_kwh * unmet[s][t] for s in S for t in T
    ) * (1.0 / n)
    capex = (pv * costs.pv_capex_per_kw * (crf(costs.discount_rate, costs.pv_life_yr) + costs.fixed_om_frac)
             + bt * costs.batt_capex_per_kwh * (crf(costs.discount_rate, costs.batt_life_yr) + costs.fixed_om_frac)
             + dg * costs.diesel_capex_per_kw * (crf(costs.discount_rate, costs.diesel_life_yr) + costs.fixed_om_frac))
    m += capex + 365 * expected_daily_opex

    status = m.solve(pulp.HiGHS(msg=False, timeLimit=time_limit_s))
    if pulp.LpStatus[status] not in ("Optimal", "Not Solved"):
        raise RuntimeError(f"Solver status: {pulp.LpStatus[status]}")
    return Design(pv.value(), bt.value(), dg.value(), label)


# ----------------------------------------------------------------------------
# Out-of-sample evaluation (fast rule-based dispatch, no solver)
# ----------------------------------------------------------------------------
def dispatch_day(d: Design, sc: Scenario, tech: Tech, warmup_days: int = 2):
    """Solar first, then battery, then diesel. Returns (unmet, diesel, served) kWh for the day."""
    soc_min, soc_max = tech.batt_min_soc * d.batt_kwh, d.batt_kwh
    p_max = tech.batt_c_rate * d.batt_kwh
    soc = soc_min + 0.5 * (soc_max - soc_min)
    for day in range(warmup_days + 1):                       # repeat the day so SOC settles
        unmet = diesel = served = 0.0
        for t in range(HOURS):
            load = sc.demand_kw[t]
            pv = d.pv_kw * sc.solar_kw_per_kwp[t]
            net = pv - load
            if net >= 0:
                c = min(net, p_max, (soc_max - soc) / tech.batt_eff_charge)
                soc += c * tech.batt_eff_charge
                served += load
            else:
                need = -net
                dch = min(need, p_max, (soc - soc_min) * tech.batt_eff_discharge)
                soc -= dch / tech.batt_eff_discharge
                need -= dch
                g = min(need, d.diesel_kw)
                diesel += g
                need -= g
                unmet += need
                served += load - need
    return unmet, diesel, served


def evaluate(d: Design, scenarios: list[Scenario], costs: Costs = Costs(),
             tech: Tech = Tech(), reliability: float = 0.95) -> dict:
    """Score a design on scenarios it was NOT sized on."""
    res = np.array([dispatch_day(d, s, tech) for s in scenarios])
    unmet, diesel, served = res[:, 0], res[:, 1], res[:, 2]
    demand = np.array([s.daily_kwh for s in scenarios])
    ok = unmet <= (1 - reliability) * demand
    fuel = costs.fuel_price_per_l * costs.diesel_l_per_kwh
    annual_cost = annual_capex(d, costs) + 365 * fuel * diesel.mean()
    annual_served = 365 * served.mean()
    # Monte Carlo statistics: 95% CI on reliability, spread of cost of power
    p_hat, n_test = float(ok.mean()), len(scenarios)
    half = 1.96 * np.sqrt(p_hat * (1 - p_hat) / n_test)
    per_day_cost = annual_capex(d, costs) / 365 + fuel * diesel
    cop = per_day_cost / np.maximum(served, 1e-9)
    cop_p10, cop_p50, cop_p90 = np.percentile(cop, [10, 50, 90])
    return {
        "design": d.label,
        "pv_kw": round(d.pv_kw, 1),
        "batt_kwh": round(d.batt_kwh, 1),
        "diesel_kw": round(d.diesel_kw, 1),
        "reliable_share": round(p_hat, 3),                     # share of scenarios meeting target
        "reliable_95ci": f"{max(p_hat - half, 0):.3f}-{min(p_hat + half, 1):.3f}",
        "mean_unmet_pct": round(float((unmet / demand).mean() * 100), 2),
        "diesel_share_pct": round(float(diesel.sum() / served.sum() * 100), 1),
        "cost_of_power_usd_kwh": round(float(annual_cost / annual_served), 3),  # = breakeven tariff
        "cop_p10_p50_p90": f"{cop_p10:.3f}/{cop_p50:.3f}/{cop_p90:.3f}",
        "annual_cost_usd": round(annual_cost),
    }


# ----------------------------------------------------------------------------
# Demo: deterministic (P50) sizing vs Lumora's stochastic sizing
# ----------------------------------------------------------------------------
def compare_designs(n_customers=250, kwh=(6.0, 12.0, 24.0), business_share=0.25,
                    n_train=150, n_test=1000, costs=Costs(), tech=Tech(),
                    reliability=0.95, prob=0.95, extra_load_kw=None, seed=1):
    """Size two ways on training scenarios, then test both on fresh scenarios.

    Out-of-sample testing uses a rule-based controller (no foresight), which is how
    real mini-grid controllers behave. The optimizer plans with perfect foresight
    inside each day, so we set the in-sample target (prob=0.95) a bit above the
    real-world goal (~0.90) to leave a margin.
    """
    train = sample_scenarios(n_customers, kwh, business_share, n_train, tech, seed, extra_load_kw)
    test = sample_scenarios(n_customers, kwh, business_share, n_test, tech, seed + 999, extra_load_kw)

    p50 = optimize_sizing([median_scenario(train)], costs, tech, reliability, prob=0.0,
                          label="sized for P50 (deterministic)")
    sto = optimize_sizing(train, costs, tech, reliability, prob, label="Lumora (stochastic)")
    return [evaluate(p50, test, costs, tech, reliability), evaluate(sto, test, costs, tech, reliability)]


def mill_load_kw(n_mills: int, kw_each: float = 7.5, hours=(9, 10, 11, 14, 15, 16)) -> np.ndarray:
    """What-if helper: daytime grain mills (illustrative 7.5 kW each, 6 h/day)."""
    extra = np.zeros(HOURS)
    for h in hours:
        extra[h] = n_mills * kw_each
    return extra


if __name__ == "__main__":
    import time

    def show(rows, title):
        print(f"\n{title}")
        keys = list(rows[0].keys())
        print(" | ".join(keys))
        for r in rows:
            print(" | ".join(str(r[k]) for k in keys))

    t0 = time.time()
    base = compare_designs()
    show(base, "Village: 250 customers, demand P10/P50/P90 = 6/12/24 kWh/customer/month")

    whatif = compare_designs(extra_load_kw=mill_load_kw(3))
    show(whatif, "What-if: finance 3 grain mills (daytime load)")
    print(f"\nSolved in {time.time() - t0:.0f}s. Cost inputs are placeholders - replace before quoting.")
