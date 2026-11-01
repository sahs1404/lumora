"""
Leave-one-site-out validation on 8 metered Kenyan mini-grids (Blodgett et al. 2017).

For each site, Lumora's benchmark forecast is built from the OTHER 7 sites only
(lognormal fit of demand per customer), giving a P50 and a P10-P90 range.
We compare its error with the developers' own survey predictions for the same sites.

This is the forecast BEFORE satellite features; adding them is the next step.
Run from the repo root:  python model/validate_kenya.py
"""
import numpy as np
import pandas as pd

d = pd.read_csv("data/validation_sites.csv")
k = d[d.country == "Kenya"].reset_index(drop=True)
act = k.measured_wh_per_customer_day.to_numpy(float)
survey = k.survey_predicted_wh_per_customer_day.to_numpy(float)

rows = []
for i in range(len(k)):
    others = np.log(np.delete(act, i))
    mu, sd = others.mean(), others.std(ddof=1)
    p10, p50, p90 = np.exp(mu - 1.2816 * sd), np.exp(mu), np.exp(mu + 1.2816 * sd)
    rows.append(dict(site=k.site_name[i], actual=act[i], survey=survey[i], p10=p10, p50=p50, p90=p90,
                     inside=p10 <= act[i] <= p90))
r = pd.DataFrame(rows)
print(r.round(0).to_string(index=False))
print(f"\nMean absolute error, survey:          {np.abs(r.survey - r.actual).mean():.0f} Wh/day per customer")
print(f"Mean absolute error, Lumora (P50):    {np.abs(r.p50 - r.actual).mean():.0f} Wh/day per customer")
print(f"Sites inside Lumora's P10-P90 range:  {r.inside.sum()} of {len(r)}")
