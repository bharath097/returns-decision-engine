"""Simulator for a returns / overstock auction marketplace WITH KNOWN TRUTH.

Everything produced here is FICTIONAL and labeled as such.  The point of the
simulator is that every latent quantity (true market value, true probability of
selling, true hazard of a fixed-price sale, true photo effect, true source
quality) is stored in ``truth_*`` tables, so each estimator in the project can
be scored against the correct answer.

Mechanisms (all adjustable in ``config/simulation.yaml``)
---------------------------------------------------------
* Sources -> lots -> items.  Lots are bought by the truckload; the buyer only
  estimates lot value with noise and pays ``estimate * (1 - margin_source)``.
* Item market value  M = retail_true * mu_true, where mu_true depends on
  category, condition, brand tier, product age, season, source quality, a lot
  shock and the number of listing photos.
* Retail value is *recorded* via a catalog match that is sometimes wrong, so the
  denominator of recovery rate carries measurement error.
* Auctions: Poisson bidders, log-normal valuations, second-price rule with an
  opening bid.  Zero bidders / highest valuation below the opening bid gives a
  FINAL zero (the item then takes a liquidation fallback value).
* Fixed price: daily hazard falls with the ratio of list price to a *decaying*
  market value, and with listing age; unobserved item frailty.  Unsold items
  roll into an auction after ``rollover_days``.  Items not finished by the data
  cutoff are OPEN (right-censored).
* Costs: handling minutes (photos add minutes), fees, shipping subsidy,
  refunds, holding and inbound freight.
* Drift: after ``expansion_start`` new source types and category mixes appear.
* Experiments: a randomized fixed-price pilot (channel x premium) and a
  randomized extra-photo experiment, embedded in otherwise confounded history.
* Data defects: exact-duplicate rows and late lot-price revisions are injected
  into the raw tables so the data layer has something real to catch.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from ..config import Config

WEIGHT_NAMES = ["tiny", "small", "medium", "large", "bulky"]

BRAND_WORDS = {
    "premium": ["Aurelia", "Vantor", "Kestrel", "Lumera", "Orbis", "Halden"],
    "mid": ["Norvik", "Brightway", "Tessra", "Kovel", "Marlow", "Pinecrest", "Solace", "Dunmore"],
    "generic": ["Valu", "Everyday", "Basix", "Simplex", "Nova", "Zenia", "Plaino"],
}
CATEGORY_NOUN = {
    "Smartphones": "Smartphone", "Laptops_current": "Laptop", "Laptops_older": "Laptop", "TVs": "Television",
    "Audio_wearables": "Headphones", "Small_appliances": "Appliance", "Large_appliances": "Appliance",
    "Tools": "Tool Set", "Toys_games": "Toy", "Apparel_shoes": "Apparel", "Home_decor": "Decor",
    "Furniture": "Furniture", "Beauty_health": "Care Kit", "Gaming": "Console Accessory",
    "Low_value_bundles": "Plush Bundle",
}
DESCRIPTORS = ["Pro", "Max", "Lite", "Plus", "Mini", "Ultra", "Classic", "Elite", "Air", "Core"]
COLORS = ["black", "white", "silver", "blue", "red", "grey", "green", "gold"]
RETURN_REASONS = ["changed_mind", "defective", "wrong_item", "no_longer_needed", "damaged_in_shipping", "overstock_excess"]


def _lognormal(rng, mu, sigma, size=None):
    return np.exp(rng.normal(mu, sigma, size))


EXTRA_WORDS = ["NEW", "open box", "w/ cord", "tested", "see photos", "bundle", "LOT", "used once"]


def _noisy_titles(clean: list, colors: list, rng) -> list:
    """Listing titles are typed by warehouse staff: tokens get dropped, abbreviated, mistyped or reordered."""
    out = []
    for t, c in zip(clean, colors):
        tok = t.split()
        if len(tok) >= 3 and rng.random() < 0.30:
            tok.pop(1)                                    # drop the product-line token
        if len(tok) >= 3 and rng.random() < 0.22:
            j = int(rng.integers(1, len(tok)))
            w = tok[j]
            if len(w) > 2:
                k = int(rng.integers(0, len(w) - 1)); w = w[:k] + w[k + 1] + w[k] + w[k + 2:]   # transposed letters
            tok[j] = w
        if rng.random() < 0.10:
            tok[0] = tok[0][:3]                           # abbreviated brand
        if rng.random() < 0.18:
            rng.shuffle(tok)
        if rng.random() < 0.30:
            tok.append(str(rng.choice(EXTRA_WORDS)))
        if rng.random() < 0.6:
            tok.append(c)
        out.append(" ".join(tok))
    return out


def auction_draw(M, start, lam, res_share, rng, sigma_v, reseller_disc, nmax):
    """One auction per row. Returns (n_bidders, sold, price).

    Second-price rule with an opening bid ``start``: the winner pays
    max(start, second-highest valuation); no sale if nobody bids or the highest
    valuation is below the opening bid.  A zero is FINAL.
    """
    N = len(M)
    n = np.minimum(rng.poisson(lam), nmax)
    z = rng.standard_normal((N, nmax))
    resell = rng.random((N, nmax)) < res_share[:, None]
    v = M[:, None] * np.exp(sigma_v * z) * np.where(resell, reseller_disc, 1.0)
    mask = np.arange(nmax)[None, :] < n[:, None]
    v = np.where(mask, v, -np.inf)
    part = np.partition(v, nmax - 2, axis=1)
    top1, top2 = part[:, -1], part[:, -2]
    sold = (n >= 1) & (top1 >= start)
    second = np.where(np.isfinite(top2), top2, start)
    price = np.where(sold, np.maximum(start, second), 0.0)
    return n, sold, price


@dataclass
class SimResult:
    tables: dict          # name -> DataFrame (raw + truth)

    def __getitem__(self, k):
        return self.tables[k]


def simulate(cfg: Config) -> SimResult:
    S = cfg.simulation
    E = cfg.settings["economics"]
    rng = np.random.default_rng(S["seed"])
    tl = S["timeline"]
    t0 = pd.Timestamp(tl["start_date"])
    t_end = pd.Timestamp(tl["end_date"])
    pilot_start = pd.Timestamp(tl["pilot_start"])
    photo_start = pd.Timestamp(tl["photo_experiment_start"])
    expansion = pd.Timestamp(tl["expansion_start"])
    cats = S["categories"]
    cat_names = list(cats.keys())
    C = len(cat_names)
    cat_idx = {c: i for i, c in enumerate(cat_names)}
    cp = {k: np.array([cats[c][k] for c in cat_names], dtype=float) for k in
          ["share", "retail_logmu", "retail_sigma", "base_mu", "dep_per_year", "lam0", "h0", "elast", "kappa",
           "decay_d", "handling_min", "refund_base", "weight_class", "reseller_share", "liq_rate", "photo_beta"]}
    cond_names = S["conditions"]["names"]
    cond_mu = np.array(S["conditions"]["mu_mult"])
    cond_hand = np.array(S["conditions"]["handling_mult"])
    cond_ref = np.array(S["conditions"]["refund_mult"])
    brand_names = S["brand_tiers"]["names"]
    brand_probs = np.array(S["brand_tiers"]["probs"])
    brand_retail = np.array(S["brand_tiers"]["retail_mult"])
    brand_mu = np.array(S["brand_tiers"]["mu_adj"])
    brand_match = np.array(S["brand_tiers"]["match_correct_prob"])
    season = {int(k): v for k, v in S["season"].items()}
    A = S["auction"]
    FP = S["fixed_price"]
    P = S["photos"]
    CST = S["costs"]
    R = int(FP["rollover_days"])

    # ------------------------------------------------------------------ sources
    sources = []
    sid = 0
    type_names = list(S["source_types"].keys())
    base_share = cp["share"] / cp["share"].sum()
    for tname, tp in S["source_types"].items():
        bias = np.array([tp["category_bias"].get(c, 1.0) for c in cat_names])
        for _ in range(tp["n_sources"]):
            w = base_share * bias
            w = w / w.sum()
            mix = rng.dirichlet(w * 25 + 0.3)
            cond_base = np.array(S["base_condition_probs"][tname])
            cond_mix = rng.dirichlet(cond_base * 30 + 0.5)
            sid += 1
            sources.append({
                "source_id": f"S{sid:03d}", "source_name": f"Source {sid:03d}", "source_type": tname,
                "region": "PNW" if tp["active_from"] == "start" else "National",
                "active_from": t0 if tp["active_from"] == "start" else expansion,
                "manifest_prob": tp["manifest_prob"],
                "quality_effect": float(np.clip(rng.normal(1.0, tp["quality_sd"]), 0.80, 1.20)),
                "target_margin": float(rng.normal(tp["margin_mean"], tp["margin_sd"])),
                "est_noise": float(tp["est_noise"] * rng.uniform(0.8, 1.2)),
                "reliability_sd": float(tp["reliability_sd"] * rng.uniform(0.8, 1.25)),
                "volume_weight": float(_lognormal(rng, 0, 0.6)),
                "mix": mix, "cond_mix": cond_mix,
            })
    src = pd.DataFrame(sources)

    # ------------------------------------------------------------------ catalog
    cat_entries = {}
    pm = S["catalog"]["models_per_category"]
    for c in cat_names:
        ci = cat_idx[c]
        entries = []
        for j in range(pm):
            tier = rng.choice(len(brand_names), p=brand_probs)
            brand = rng.choice(BRAND_WORDS[brand_names[tier]])
            model = f"{rng.choice(DESCRIPTORS)} {rng.integers(1, 99)}{rng.choice(list('ABCDEFGHK'))}"
            price = float(max(3.0, _lognormal(rng, cp["retail_logmu"][ci], cp["retail_sigma"][ci]) * brand_retail[tier]))
            entries.append({"cat": c, "brand": brand, "tier": tier, "model": model,
                            "title": f"{brand} {model} {CATEGORY_NOUN[c]}", "price": price})
        cat_entries[c] = entries
    all_entries = [e for c in cat_names for e in cat_entries[c]]

    # --------------------------------------------------------------------- lots
    n_lots = S["scale"]["n_lots"]
    day_span = (t_end - t0).days - 4           # lots keep arriving until just before the cutoff (so some items are still OPEN)
    lot_rows = []
    for k in range(n_lots):
        d = t0 + pd.Timedelta(days=int(rng.integers(0, day_span)))
        active = src[src["active_from"] <= d]
        w = active["volume_weight"].to_numpy()
        # after expansion, new regional sources receive a bigger share
        if d >= expansion:
            w = w * np.where(active["source_type"].to_numpy() == "regional_marketplace", 2.5, 1.0)
        srow = active.iloc[rng.choice(len(active), p=w / w.sum())]
        n_items = int(np.clip(_lognormal(rng, math.log(S["scale"]["items_per_lot_median"]), S["scale"]["items_per_lot_sigma"]),
                              S["scale"]["items_per_lot_min"], S["scale"]["items_per_lot_max"]))
        lot_rows.append({"lot_id": f"L{k+1:05d}", "source_id": srow["source_id"], "receipt_date": d, "n_items": n_items,
                         "manifest_flag": bool(rng.random() < srow["manifest_prob"]),
                         "lot_shock": float(np.clip(rng.normal(0, srow["reliability_sd"]), -0.35, 0.35))})
    lots = pd.DataFrame(lot_rows).sort_values("receipt_date").reset_index(drop=True)
    lots["lot_id"] = [f"L{i+1:05d}" for i in range(len(lots))]
    src_idx = {s: i for i, s in enumerate(src["source_id"])}

    # -------------------------------------------------------------------- items
    recs = []
    for _, lot in lots.iterrows():
        s = src.iloc[src_idx[lot["source_id"]]]
        n = lot["n_items"]
        cat_choice = rng.choice(C, size=n, p=s["mix"])
        cond_choice = rng.choice(len(cond_names), size=n, p=s["cond_mix"])
        blind = not lot["manifest_flag"]
        for ci, ki in zip(cat_choice, cond_choice):
            recs.append((lot["lot_id"], lot["source_id"], lot["receipt_date"], lot["lot_shock"], ci, ki, blind))
    it = pd.DataFrame(recs, columns=["lot_id", "source_id", "receipt_date", "lot_shock", "ci", "ki", "blind"])
    N = len(it)
    it["item_id"] = [f"I{i+1:07d}" for i in range(N)]
    ci = it["ci"].to_numpy()
    ki = it["ki"].to_numpy()
    it["category"] = [cat_names[i] for i in ci]
    it["condition"] = [cond_names[i] for i in ki]
    tier = rng.choice(len(brand_names), size=N, p=brand_probs)
    it["brand_tier"] = [brand_names[i] for i in tier]

    # catalog assignment (true product) and the (possibly wrong) recorded match
    true_entry = np.empty(N, dtype=object)
    rec_entry = np.empty(N, dtype=object)
    match_ok = np.zeros(N, dtype=bool)
    p_ok = brand_match[tier] - S["listing"]["p_blind_lot_wrong_match_extra"] * it["blind"].to_numpy()
    cat_entry_lists = {c: cat_entries[c] for c in cat_names}
    for j in range(N):
        c = cat_names[ci[j]]
        cands = [e for e in cat_entry_lists[c] if e["tier"] == tier[j]] or cat_entry_lists[c]
        e = cands[rng.integers(len(cands))]
        true_entry[j] = e
        if rng.random() < p_ok[j]:
            rec_entry[j] = e
            match_ok[j] = True
        else:
            if rng.random() < S["catalog"].get("wrong_match_near_miss_prob", 0.55):
                # near miss: same brand, same category, a neighbouring model
                brand = e["title"].split()[0]
                pool = [x for x in cat_entry_lists[c] if x["title"].split()[0] == brand and x is not e] or cat_entry_lists[c]
            elif rng.random() < S["catalog"]["wrong_match_same_category_prob"]:
                pool = cat_entry_lists[c]
            else:
                pool = all_entries
            rec_entry[j] = pool[rng.integers(len(pool))]
            match_ok[j] = rec_entry[j] is e
    pn = S["catalog"]["price_noise"]
    retail_true = np.array([e["price"] for e in true_entry]) * np.exp(rng.normal(0, pn, N))
    retail_rec = np.array([e["price"] for e in rec_entry]) * np.exp(rng.normal(0, pn, N))
    # a wrong catalog match is a *similar* product, not an arbitrary one: bound the price ratio
    _lim = S["catalog"].get("wrong_match_price_ratio", [0.3, 3.5])
    retail_rec = np.where(match_ok, retail_rec, retail_true * np.clip(retail_rec / retail_true, _lim[0], _lim[1]))
    retail_true = np.round(np.maximum(retail_true, 3.0), 2)
    retail_rec = np.round(np.maximum(retail_rec, 3.0), 2)
    it["retail_value"] = retail_rec
    color = rng.choice(COLORS, size=N)
    it["title"] = _noisy_titles([e["title"] for e in true_entry], list(color), np.random.default_rng(cfg.simulation["seed"] + 7))
    it["matched_title"] = [e["title"] for e in rec_entry]
    it["match_confidence"] = np.where(match_ok, rng.beta(6, 2, N), rng.beta(4.5, 2.5, N)).round(4)
    elec = np.isin(it["category"], ["Smartphones", "Laptops_current", "Laptops_older", "TVs", "Audio_wearables", "Gaming"])
    age = np.where(elec, rng.gamma(1.6, 1.0, N), rng.gamma(1.0, 1.0, N)).clip(0, 8)
    it["product_age_years"] = age.round(2)
    wc = cp["weight_class"][ci].astype(int)
    bump = (rng.random(N) < 0.08).astype(int)
    wc = np.clip(wc + bump, 0, 4)
    it["weight_class"] = wc
    it["return_reason"] = rng.choice(RETURN_REASONS, size=N, p=[0.30, 0.22, 0.08, 0.18, 0.10, 0.12])

    # listing date
    shape = S["listing"]["receipt_to_listing_shape"]
    scale = S["listing"]["receipt_to_listing_mean_days"] / shape
    rtl = np.maximum(1, np.round(rng.gamma(shape, scale, N) * (1 + 0.15 * wc))).astype(int)
    it["receipt_to_listing_days"] = rtl
    it["listed_date"] = pd.to_datetime(it["receipt_date"]) + pd.to_timedelta(rtl, unit="D")
    keep = it["listed_date"] <= t_end
    it = it[keep].reset_index(drop=True)
    sel = np.where(keep.to_numpy() if hasattr(keep, "to_numpy") else keep)[0]
    true_entry, rec_entry = true_entry[sel], rec_entry[sel]
    match_ok, retail_true, retail_rec = match_ok[sel], retail_true[sel], retail_rec[sel]
    age, wc, tier = age[sel], wc[sel], tier[sel]
    ci, ki = ci[sel], ki[sel]
    N = len(it)

    # photos (confounded history) and randomized extra-photo experiment
    thr = P["per_value_threshold"]
    base_ph = P["baseline_base"] + (retail_rec > thr[0]).astype(int) + (retail_rec > thr[1]).astype(int) + \
        (retail_rec > thr[2]).astype(int) + rng.poisson(0.5, N)
    in_exp_window = (it["listed_date"] >= photo_start).to_numpy()
    in_exp = in_exp_window & (rng.random(N) < P["experiment_share"])
    treat_photo = in_exp & (rng.random(N) < P["experiment_p_treat"])
    photos = base_ph + treat_photo * P["extra_photos_in_experiment"]
    it["photo_count"] = photos
    it["photo_arm"] = np.where(~in_exp, "none", np.where(treat_photo, "extra", "control"))

    # ----------------------------------------------------------- true market value
    cs = {k: cp[k][ci] for k in cp}
    lot_shock = it["lot_shock"].to_numpy()
    src_q = it["source_id"].map(src.set_index("source_id")["quality_effect"]).to_numpy()
    mon = it["listed_date"].dt.month.to_numpy()
    seas = np.array([season[int(m)] for m in mon])
    dep = np.exp(-cs["dep_per_year"] * age)
    photo_uplift = cs["photo_beta"] * (1 - np.exp(-P["decay_rate"] * photos))
    mu_true = (cs["base_mu"] * cond_mu[ki] * (1 + brand_mu[tier]) * dep * seas * src_q * np.exp(lot_shock)
               * np.exp(rng.normal(0, 0.10, N)) * np.exp(photo_uplift))
    mu_true = np.clip(mu_true, 0.02, 1.0)
    M = mu_true * retail_true                                     # market value in dollars

    # simultaneous listings (supply glut) = same category listed in the same ISO week
    wk = it["listed_date"].dt.isocalendar()
    it["list_week"] = (wk["year"].astype(int) * 100 + wk["week"].astype(int)).to_numpy()
    sim_list = it.groupby(["category", "list_week"])["item_id"].transform("count").to_numpy()
    med_sim = np.median(sim_list)
    glut = (sim_list / med_sim) ** A["glut_elasticity"]
    it["simultaneous_listings"] = sim_list

    # auction mechanics
    start_pct = rng.choice(A["start_bid_pct"], size=N, p=A["start_bid_probs"])
    dur = rng.choice(A["duration_days"], size=N, p=A["duration_probs"])
    it["start_bid_pct"] = start_pct
    it["auction_duration_days"] = dur
    start_dollar = start_pct * retail_rec
    lam = (cs["lam0"] * (retail_true / np.exp(cs["retail_logmu"])) ** 0.12 * seas * glut
           * (mu_true / cs["base_mu"]) ** 0.6 * np.clip(1 - A["start_bid_lambda_penalty"] * start_pct, 0.2, 1.0))
    lam = np.clip(lam, 0.05, 12.0)
    res_share = cs["reseller_share"]

    # ------------------------------------------------------------- TRUTH by Monte Carlo
    K = S["scale"]["mc_draws_truth"]
    sold_sum = np.zeros(N)
    price_sum = np.zeros(N)
    rng_mc = np.random.default_rng(S["seed"] + 1)
    for _ in range(K):
        _, sold_k, price_k = auction_draw(M, start_dollar, lam, res_share, rng_mc, A["sigma_valuation"],
                                          A["reseller_discount"], A["max_bidders"])
        sold_sum += sold_k
        price_sum += price_k
    p_sell_true = sold_sum / K
    e_price_sold_true = np.where(sold_sum > 0, price_sum / np.maximum(sold_sum, 1), 0.0)
    x_true = price_sum / K / retail_rec                       # expected recovery incl. zeros (vs recorded retail)
    e_rec_sold_true = np.where(sold_sum > 0, e_price_sold_true / retail_rec, 0.0)

    # ---------------------------------------------------- listing channel (pilot)
    pl = S["pilot"]
    eligible = (it["listed_date"] >= pilot_start).to_numpy() & (retail_rec >= pl["eligible_min_retail"])
    arm_fixed = eligible & (rng.random(N) < pl["p_fixed"])
    premium = np.where(arm_fixed, rng.choice(pl["premium_grid"], size=N), 0.0)
    pm_cfg = S["production_model"]
    # The incumbent model is a stale category x condition lookup of historical recovery-given-sold
    # (no item-level signal), with small noise. It must NOT see item-level truth.
    _tmp = pd.DataFrame({"c": ci, "k": ki, "e": np.where(e_rec_sold_true > 0, e_rec_sold_true, np.nan)})
    _tbl = _tmp.groupby(["c", "k"])["e"].transform("mean").fillna(_tmp["e"].mean()).to_numpy()
    prod_pred_e_rec_sold = np.clip(_tbl * np.exp(rng.normal(pm_cfg["bias_log"], pm_cfg["noise_log"], N)), 0.02, 1.2)
    list_price = np.round(np.where(arm_fixed, prod_pred_e_rec_sold * retail_rec * (1 + premium), 0.0), 2)
    it["pilot_arm"] = np.where(~eligible, "not_eligible", np.where(arm_fixed, "fixed", "auction"))
    it["channel"] = np.where(arm_fixed, "fixed_price", "auction")
    it["premium_pct"] = premium
    it["list_price"] = list_price
    it["prod_pred_expected_auction_recovery"] = prod_pred_e_rec_sold.round(4)

    # ------------------------------------------------------------- realized outcomes
    # (a) auction-channel items
    out_n, out_sold, out_price = auction_draw(M, start_dollar, lam, res_share, rng, A["sigma_valuation"],
                                              A["reseller_discount"], A["max_bidders"])
    watchers = np.round(out_n * rng.uniform(2.0, 6.0, N)).astype(int)
    sale_channel = np.where(out_sold, "auction", "none").astype(object)
    sale_price = np.where(out_sold, out_price, 0.0)
    days_to_close = dur.astype(float).copy()
    days_to_sale_fixed = np.full(N, np.nan)
    rolled = np.zeros(N, dtype=bool)

    # (b) fixed-price items: daily hazard process with market value decay
    F = np.where(arm_fixed)[0]
    close_day = dur.astype(float).copy()                 # days from listing to FINAL disposition
    sale_day_fixed = np.full(N, np.nan)
    rolled = np.zeros(N, dtype=bool)
    if len(F):
        t = np.arange(1, R + 1)[None, :].astype(float)
        Mf = M[F][:, None] * np.exp(-cs["decay_d"][F][:, None] * t)
        ratio = np.clip(list_price[F][:, None] / Mf, 0.3, 4.0)
        frailty = np.exp(rng.normal(0, FP["frailty_sigma"], len(F)))[:, None]
        hz = (cs["h0"][F][:, None] * ratio ** (-cs["elast"][F][:, None]) * np.exp(-cs["kappa"][F][:, None] * t)
              * seas[F][:, None] * frailty)
        hz = np.clip(hz, 0.0, FP["max_daily_hazard"])
        hit = rng.random(hz.shape) < (1 - np.exp(-hz))
        sold_fx = hit.any(axis=1)
        day_fx = np.where(sold_fx, hit.argmax(axis=1) + 1, 0)
        sale_channel[F] = np.where(sold_fx, "fixed", "none")
        sale_price[F] = np.where(sold_fx, list_price[F], 0.0)
        sale_day_fixed[F] = np.where(sold_fx, day_fx, np.nan)
        close_day[F] = np.where(sold_fx, day_fx, R + dur[F])
        out_n[F] = 0
        U = F[~sold_fx]                                   # unsold after the fixed window -> roll into an auction
        if len(U):
            MR = M[U] * np.exp(-cs["decay_d"][U] * R)
            n2, s2, p2 = auction_draw(MR, start_dollar[U], lam[U] * FP["rollover_lambda_factor"], res_share[U], rng,
                                      A["sigma_valuation"], A["reseller_discount"], A["max_bidders"])
            rolled[U] = True
            sale_channel[U] = np.where(s2, "rollover_auction", "none")
            sale_price[U] = np.where(s2, p2, 0.0)
            out_n[U] = n2
            watchers[U] = np.round(n2 * rng.uniform(2.0, 6.0, len(U))).astype(int)
    sold = sale_price > 0

    # status against the data cutoff: an item is CLOSED only if its final disposition happened by the cutoff
    listed_ts = pd.to_datetime(it["listed_date"])
    close_ts = listed_ts + pd.to_timedelta(np.round(close_day).astype(int), unit="D")
    is_open = (close_ts > t_end).to_numpy()
    days_so_far = np.maximum(0, (t_end - listed_ts).dt.days.to_numpy()).astype(float)
    status = np.where(is_open, "open", "closed")
    closed = ~is_open

    # fallback (liquidation) value for items that end unsold or are refunded; refunds; costs
    liq = cp["liq_rate"][ci] * retail_rec * rng.uniform(0.8, 1.25, N)
    refund_p = (cs["refund_base"] * cond_ref[ki] * np.exp(P["refund_photo_effect"] * (photos - P["baseline_base"]))
                * np.where(match_ok, 1.0, 1.6))
    refund_p = np.clip(refund_p, 0, 0.6)
    refund = sold & (rng.random(N) < refund_p)
    hand_min = (cs["handling_min"] * cond_hand[ki] * _lognormal(rng, 0, CST["handling_noise_sigma"], N)
                + P["minutes_per_photo"] * photos)
    ship_tbl = np.array(E["shipping_cost_by_weight_class"])
    ship = ship_tbl[wc] * _lognormal(rng, 0, CST["shipping_noise_sigma"], N)
    fees = np.where(sold, E["fee_pct"] * sale_price + E["fee_fixed"], 0.0)
    shipping_cost = np.where(sold, ship, 0.0) + np.where(refund, ship, 0.0)     # return shipping on refunds
    fallback_realized = np.where((~sold) | refund, liq * (1 - E["liquidation_cost_pct"]), 0.0)
    rtl_sel = it["receipt_to_listing_days"].to_numpy().astype(float)
    holding_days = np.where(closed, close_day, days_so_far) + rtl_sel

    # observable outcomes: blank everything that is not yet final for OPEN items
    sold_final = closed & sold
    outcomes = pd.DataFrame({
        "item_id": it["item_id"], "status": status, "sold": sold_final,
        "sale_channel": np.where(closed, sale_channel, "open"),
        "sale_price": np.where(closed, sale_price, 0.0).round(2),
        "days_listed": np.where(closed, close_day, days_so_far).astype(float),
        "days_to_sale_fixed": np.where(closed & (sale_channel == "fixed"), sale_day_fixed, np.nan),
        "rolled_to_auction": closed & rolled,
        "bidders": np.where(closed & (out_n >= 0) & (sale_channel != "fixed"), out_n, np.nan).astype(float),
        "watchers": np.where(closed & (sale_channel != "fixed"), watchers, np.nan).astype(float),
        "refund_flag": closed & refund,
        "fallback_value": np.where(closed, fallback_realized, 0.0).round(2),
        "fees": np.where(closed, fees, 0.0).round(2),
        "shipping_cost": np.where(closed, shipping_cost, 0.0).round(2),
        "handling_minutes": hand_min.round(2),
        "holding_days": holding_days.astype(float),
        "close_date": close_ts.where(closed, pd.NaT),
    })
    it["close_date"] = close_ts

    # --------------------------------------------------------------- truth tables
    truth_items = pd.DataFrame({
        "item_id": it["item_id"], "retail_true": retail_true, "market_value": M.round(4), "mu_true": mu_true.round(5),
        "p_sell_true": p_sell_true.round(4), "e_rec_sold_true": e_rec_sold_true.round(5), "x_true": x_true.round(5),
        "lambda_true": lam.round(4), "match_correct": match_ok, "h0": cs["h0"], "elast": cs["elast"],
        "kappa": cs["kappa"], "decay_d": cs["decay_d"], "photo_beta": cs["photo_beta"],
        "liq_value_expected": (cp["liq_rate"][ci] * retail_rec * (1 - E["liquidation_cost_pct"])).round(4),
    })
    # expected net value per item (before holding), used to price lots
    ship_exp = ship_tbl[wc]
    hand_exp = (cs["handling_min"] * cond_hand[ki] * math.exp(CST["handling_noise_sigma"] ** 2 / 2)
                + P["minutes_per_photo"] * photos)
    liq_exp = truth_items["liq_value_expected"].to_numpy()
    exp_net = (x_true * retail_rec * (1 - refund_p)
               - (E["fee_pct"] * x_true * retail_rec + E["fee_fixed"] * p_sell_true)
               - ship_exp * p_sell_true * (1 + refund_p)
               + ((1 - p_sell_true) + p_sell_true * refund_p) * liq_exp
               - hand_exp * E["labor_cost_per_minute"])
    truth_items["expected_net_value"] = exp_net.round(4)

    # ------------------------------------------------------------------ lot costs
    lots_f = lots.copy()
    lots_f["true_expected_value"] = lots_f["lot_id"].map(truth_items.assign(lot_id=it["lot_id"]).groupby("lot_id")["expected_net_value"].sum())
    lot_items = it.groupby("lot_id").size()
    lot_ret = it.groupby("lot_id")["retail_value"].sum()
    lots_f["n_items_listed"] = lots_f["lot_id"].map(lot_items).fillna(0).astype(int)
    lots_f["lot_retail_recorded"] = lots_f["lot_id"].map(lot_ret).fillna(0.0)
    lots_f = lots_f[lots_f["n_items_listed"] > 0].reset_index(drop=True)
    srcm = src.set_index("source_id")
    est_noise = srcm.loc[lots_f["source_id"], "est_noise"].to_numpy() * np.where(lots_f["manifest_flag"], S["lot_pricing"]["manifest_noise_scale"], 1.0)
    est = lots_f["true_expected_value"].to_numpy() * np.exp(rng.normal(0, est_noise))
    margin = srcm.loc[lots_f["source_id"], "target_margin"].to_numpy() + rng.normal(0, S["lot_pricing"]["margin_sd_within_source"], len(lots_f))
    lots_f["lot_price"] = np.round(np.maximum(est * (1 - margin), 25.0), 2)
    fr = np.array(CST["inbound_freight_per_item_by_weight"])
    wc_lot = it.groupby("lot_id")["weight_class"].apply(lambda s: fr[s.to_numpy()].sum())
    lots_f["inbound_freight"] = lots_f["lot_id"].map(wc_lot).round(2)
    lots_f["n_items_manifest"] = np.where(lots_f["manifest_flag"],
                                          np.round(lots_f["n_items_listed"] * rng.uniform(0.97, 1.03, len(lots_f))), np.nan)
    lots_f["manifest_retail_total"] = np.where(lots_f["manifest_flag"],
                                               lots_f["lot_retail_recorded"] * rng.uniform(0.93, 1.07, len(lots_f)), np.nan).round(2)
    lots_f["acquisition_basis"] = np.where(lots_f["manifest_flag"], "manifest", "blind")
    lots_f["loaded_at"] = pd.to_datetime(lots_f["receipt_date"]) + pd.Timedelta(days=1)

    raw_lots = lots_f[["lot_id", "source_id", "receipt_date", "manifest_flag", "n_items_manifest", "manifest_retail_total",
                       "lot_price", "inbound_freight", "acquisition_basis", "loaded_at"]].copy()
    # inject data defects: exact duplicates and late lot price revisions
    dup = raw_lots.sample(frac=0.04, random_state=S["seed"])
    rev = raw_lots.sample(frac=0.005, random_state=S["seed"] + 2).copy()
    rev["lot_price"] = (rev["lot_price"] * 1.02).round(2)         # later row = corrected price
    rev["loaded_at"] = rev["loaded_at"] + pd.Timedelta(days=20)
    raw_lots = pd.concat([raw_lots, dup, rev], ignore_index=True).sample(frac=1.0, random_state=1).reset_index(drop=True)

    raw_items = it[["item_id", "lot_id", "source_id", "category", "brand_tier", "condition", "retail_value", "match_confidence",
                    "product_age_years", "title", "matched_title", "photo_count", "photo_arm", "weight_class", "return_reason",
                    "receipt_date", "receipt_to_listing_days", "listed_date", "channel", "pilot_arm", "premium_pct",
                    "list_price", "prod_pred_expected_auction_recovery", "start_bid_pct", "auction_duration_days",
                    "simultaneous_listings"]].copy()
    raw_items = raw_items[raw_items["lot_id"].isin(lots_f["lot_id"])]
    raw_items["end_dow"] = (raw_items["listed_date"] + pd.to_timedelta(raw_items["auction_duration_days"], unit="D")).dt.dayofweek
    raw_items["end_hour"] = rng.choice([18, 19, 20, 21, 22], size=len(raw_items))
    raw_items["loaded_at"] = pd.to_datetime(raw_items["listed_date"])
    dup_i = raw_items.sample(frac=0.015, random_state=S["seed"] + 3)
    raw_items = pd.concat([raw_items, dup_i], ignore_index=True).sample(frac=1.0, random_state=2).reset_index(drop=True)

    audit_ids = it["item_id"].sample(frac=S["catalog"]["audit_share"], random_state=S["seed"] + 4)
    audit = pd.DataFrame({"item_id": audit_ids})
    audit["match_correct"] = audit["item_id"].map(dict(zip(it["item_id"], match_ok))).astype(bool)

    truth_lots = lots_f[["lot_id", "source_id", "true_expected_value", "lot_price", "inbound_freight"]].copy()
    truth_sources = src[["source_id", "source_type", "quality_effect", "target_margin", "est_noise", "reliability_sd"]].copy()
    raw_sources = src[["source_id", "source_name", "source_type", "region", "active_from"]].copy()
    truth_items["lot_id"] = it["lot_id"].to_numpy()
    truth_items = truth_items[truth_items["lot_id"].isin(lots_f["lot_id"])]

    # the five-item story, reproduced as an illustrative table
    story = pd.DataFrame({
        "item": [1, 2, 3, 4, 5],
        "expected_auction_price": [120.0, 85.0, 240.0, 60.0, 310.0],
    })
    story["list_price"] = (story["expected_auction_price"] * 1.20).round(2)
    story["status_today"] = ["sold", "sold", "sold", "open", "open"]
    story["sale_price"] = [144.0, 102.0, 288.0, 0.0, 0.0]
    story["note"] = "ILLUSTRATIVE numbers for a five-item pilot; two items still listed, not failed"

    return SimResult({
        "raw_sources": raw_sources, "raw_lots": raw_lots, "raw_items": raw_items, "raw_outcomes": outcomes[outcomes["item_id"].isin(raw_items["item_id"])],
        "raw_item_audit": audit, "truth_items": truth_items, "truth_lots": truth_lots, "truth_sources": truth_sources,
        "story_five_items": story,
    })


def write_raw(cfg: Config, result: SimResult | None = None) -> SimResult:
    result = result or simulate(cfg)
    out = cfg.raw_dir
    out.mkdir(parents=True, exist_ok=True)
    for name, df in result.tables.items():
        df.to_parquet(out / f"{name}.parquet", index=False)
    (out / "README.txt").write_text(cfg.settings["project"]["data_banner"] + "\n")
    return result
