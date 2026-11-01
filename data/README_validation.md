# Validation sites

`validation_sites.csv` holds 12 mini-grid sites with measured (metered) demand, used for leave-one-site-out validation.

| Group | Sites | Location data | Notes |
|---|---|---|---|
| Kenya (Blodgett et al. 2017) | 8 | Village names only, no coordinates in the paper | Small systems (1.5-5.6 kW). Most per-customer values are derived from the paper's Table 4 totals divided by customers analysed. Survey predictions included, so we can beat the survey baseline directly. |
| Tanzania (Scott & Coley 2021) | 2 | Anonymised (Site A, Site D) | Usable only for checking the demand range, not for satellite features. |
| Ethiopia (Wassie & Ahlgren 2024) | 2 | Town names | Much larger town systems (375-550 kWp). Omorate is load-shed 13 h/day, so its measured demand understates true demand. Per-customer value = site daily total / customers (Dec 2021 count). |

## To do (Sahasra)
1. Geocode the 10 named sites from `geocode_query` (OSM Nominatim), check each on satellite imagery, and add `lat`,`lon` columns.
2. Pull features for each site.
3. Baselines to beat (Kenya sites): survey MAE 426 Wh/day/customer; proxy-village MAE 75 Wh/day (abstract; the paper's discussion section reports 60.6 Wh).

Mixing 8 small Kenyan villages with 2 Ethiopian towns makes the demand range very wide (1.3 to 72 kWh/customer/month). Use log demand in the model, and report the Kenya-only error separately.
