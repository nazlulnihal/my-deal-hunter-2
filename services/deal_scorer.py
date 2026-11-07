"""
Deal Sniper Concrete Scoring Rubric & Mandatory Second-Source Error-Price Verification
(`services/deal_scorer.py`).

Implements the exact concrete 100-point rubric required:
- 40% weight (0–40 pts): Discount vs 90-Day Observed Median Price
- 20% weight (0–20 pts): Cross-Retailer Price Gap (vs next cheapest Australian retailer)
- 15% weight (0–15 pts): Data Confidence & Verification Stage (checkout_verified vs retailer_listed vs search_result)
- 15% weight (0–15 pts): Seller & Retailer Trust (Tier-1 AU store vs marketplace/grey import)
- 10% weight (0–10 pts): Live Stock & Local Postcode Availability ("In Stock Online", "Available Locally for Click & Collect", or "Out of Stock" = 0 actionable)

Also enforces the Mandatory Error-Price Second-Source Rule:
Whenever a listing is discounted by >= 70% below the 90-day median (such as an "AUD 20 Galaxy Watch 7"),
the engine requires a Second-Source Check (verifying exact GTIN/MPN, confirming it is not an accessory/band,
and cross-checking checkout stock status) before dispatching an urgent Telegram alert.
Out-of-stock items are strictly marked `is_actionable = 0` and never recommended as actionable deals.
"""

import json
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional


TIER_1_AUSTRALIAN_RETAILERS = {
    "Officeworks": 98,
    "JB Hi-Fi": 98,
    "The Good Guys": 96,
    "Appliances Online": 96,
    "Woolworths": 98,
    "Coles": 98,
    "Bunnings": 98,
    "Chemist Warehouse": 95,
    "Myer": 95,
    "David Jones": 95,
    "Big W": 94,
    "Target": 94,
    "Harvey Norman": 93,
    "Bing Lee": 94,
    "Priceline": 94,
    "Amazon Australia": 94,
    "Kogan": 80,
    "eBay Australia": 78,
}


@dataclass
class RubricBreakdown:
    discount_vs_90d_median_pts: float       # Max 40.0
    cross_retailer_gap_pts: float           # Max 20.0
    data_confidence_pts: float              # Max 15.0
    seller_trust_pts: float                 # Max 15.0
    stock_availability_pts: float           # Max 10.0
    total_deal_score: int                   # 0 - 100
    formula_summary: str


class DealSniperScoringService:
    """
    Calculates explainable 0–100 Deal Scores using the 40/20/15/15/10 concrete rubric
    and runs mandatory second-source verification on extreme (>70% off) pricing anomalies.
    """

    def score_and_verify_listing(
        self,
        product: Dict[str, Any],
        observation: Dict[str, Any],
        median_90d_aud: float,
        lowest_90d_aud: float,
        next_cheapest_competitor_aud: float,
        match_evaluation: Dict[str, Any],
        matched_interest: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        listed_price = float(observation["listed_price_aud"])
        shipping = float(observation.get("shipping_cost_aud", 0.0))
        coupon_disc = float(observation.get("coupon_discount_aud", 0.0))
        final_checkout = max(0.0, round(listed_price - coupon_disc + shipping, 2))

        stock_badge = observation.get("stock_badge", "In Stock Online")
        is_out_of_stock = (stock_badge == "Out of Stock")
        is_accessory_trap = bool(match_evaluation.get("is_accessory_trap", False))
        is_variant_mismatch = bool(match_evaluation.get("is_variant_mismatch", False))

        # 1. Discount vs 90-Day Median (Max 40 pts; full 40 pts at >= 50% below 90-day median)
        effective_median = max(median_90d_aud, float(product["normal_market_price_aud"]) * 0.85, 0.01)
        discount_vs_median_pct = round(((effective_median - final_checkout) / effective_median) * 100.0, 1)
        if is_accessory_trap or is_variant_mismatch:
            pts_median = 0.0
        else:
            pts_median = min(40.0, max(0.0, (discount_vs_median_pct / 50.0) * 40.0))

        # 2. Cross-Retailer Gap vs Next Cheapest Competitor (Max 20 pts; full 20 pts at >= 25% cheaper than next store)
        eff_comp = max(next_cheapest_competitor_aud, final_checkout, 0.01)
        cross_gap_pct = round(((eff_comp - final_checkout) / eff_comp) * 100.0, 1) if eff_comp > final_checkout else 0.0
        if is_accessory_trap or is_variant_mismatch:
            pts_cross = 0.0
        else:
            pts_cross = min(20.0, max(0.0, (cross_gap_pct / 25.0) * 20.0))

        # 3. Data Confidence & Price Stage (Max 15 pts)
        raw_conf = float(observation.get("data_confidence", 0.95))
        price_stage = observation.get("price_stage", "retailer_listed")
        stage_multiplier = 1.0 if price_stage == "checkout_verified" else (0.90 if price_stage == "retailer_listed" else 0.72)
        data_confidence_100 = int(round(min(100.0, raw_conf * stage_multiplier * 100.0)))
        pts_confidence = round((data_confidence_100 / 100.0) * 15.0, 2)

        # 4. Seller & Retailer Trust (Max 15 pts)
        retailer = observation["retailer"]
        is_marketplace = bool(observation.get("is_marketplace", 0))
        base_trust = TIER_1_AUSTRALIAN_RETAILERS.get(retailer, 75)
        risk_warnings: List[str] = []

        if is_marketplace:
            base_trust -= 15
            risk_warnings.append(f"Marketplace third-party seller ({observation.get('seller_name', 'Marketplace')}) — verify Australian warranty.")

        if shipping > 20.0:
            base_trust -= 10
            risk_warnings.append(f"High delivery charge (AUD {shipping:.2f}) reduces net value.")

        if observation.get("condition", "New") != "New":
            risk_warnings.append(f"Condition is Certified '{observation['condition']}' (enabled via Refurbished/Open-Box toggle).")

        if is_accessory_trap:
            base_trust = 15
            risk_warnings.append(match_evaluation.get("reason", "Accessory trap detected."))
        elif is_variant_mismatch:
            base_trust = 35
            risk_warnings.append(match_evaluation.get("reason", "Variant mismatch detected."))

        seller_trust_100 = max(10, min(100, base_trust))
        pts_trust = round((seller_trust_100 / 100.0) * 15.0, 2)

        # 5. Live Stock & Local Postcode Availability (Max 10 pts)
        if is_out_of_stock:
            availability_100 = 0
            pts_availability = 0.0
            risk_warnings.append("Currently Out of Stock — recorded for historical tracking only; not recommended as an actionable deal.")
        elif stock_badge == "Available Locally for Click & Collect":
            availability_100 = 100
            pts_availability = 10.0
        elif stock_badge == "In Stock Online":
            availability_100 = 90
            pts_availability = 9.0
        else:  # Low Stock
            availability_100 = 80
            pts_availability = 8.0

        # Mandatory Error-Price Rule (>= 70% below 90-day median requires Second-Source Check)
        is_error_price_anomaly = (discount_vs_median_pct >= 70.0 and not is_accessory_trap and not is_variant_mismatch)
        second_source_verified = bool(observation.get("second_source_verified", 0))

        if is_error_price_anomaly:
            if second_source_verified and price_stage == "checkout_verified":
                second_source_status = "Passed Second-Source Check (GTIN/MPN + Checkout Price Confirmed)"
                risk_warnings.append(
                    f"Extreme Error-Price / Clearance Anomaly (-{discount_vs_median_pct:.0f}% vs 90d median at {retailer}): "
                    f"Second-source check confirmed exact hardware variant ({product.get('model_number')}). High cancellation risk — choose Click & Collect."
                )
            else:
                second_source_status = "Pending Second-Source Check (Hold Unsolicited Alert)"
                pts_confidence = min(pts_confidence, 8.0)
                risk_warnings.append(
                    f"Unverified >70% Error-Price Anomaly (-{discount_vs_median_pct:.0f}%): Held pending second-source GTIN/checkout verification."
                )
        else:
            second_source_status = "Standard Verification Passed"

        # Total Composite Score
        raw_total = pts_median + pts_cross + pts_confidence + pts_trust + pts_availability
        if is_out_of_stock or is_accessory_trap or is_variant_mismatch:
            total_score = min(35, int(round(raw_total * 0.4)))
        elif is_error_price_anomaly and not second_source_verified:
            # Cap unverified error-price anomalies at 76 so they do not trigger >=90 unsolicited alerts until verified
            total_score = min(76, int(round(raw_total)))
        else:
            total_score = max(1, min(100, int(round(raw_total))))

        if total_score >= 90:
            classification = "Exceptional"
        elif total_score >= 78:
            classification = "Excellent"
        elif total_score >= 62:
            classification = "Good"
        else:
            classification = "Ordinary"

        attractiveness_100 = max(5, min(100, int(round(((pts_median + pts_cross) / 60.0) * 100.0))))
        suitability_100 = 15 if (is_accessory_trap or is_variant_mismatch) else (96 if matched_interest else 88)

        rubric = RubricBreakdown(
            discount_vs_90d_median_pts=round(pts_median, 1),
            cross_retailer_gap_pts=round(pts_cross, 1),
            data_confidence_pts=round(pts_confidence, 1),
            seller_trust_pts=round(pts_trust, 1),
            stock_availability_pts=round(pts_availability, 1),
            total_deal_score=total_score,
            formula_summary=(
                f"40% Median Disc ({pts_median:.1f}/40) + 20% Retailer Gap ({pts_cross:.1f}/20) + "
                f"15% Confidence ({pts_confidence:.1f}/15) + 15% Trust ({pts_trust:.1f}/15) + "
                f"10% Stock ({pts_availability:.1f}/10) = {total_score}/100"
            )
        )

        is_actionable = int(
            not is_out_of_stock
            and not is_accessory_trap
            and not is_variant_mismatch
            and not (is_error_price_anomaly and not second_source_verified)
        )

        return {
            "deal_score": total_score,
            "classification": classification,
            "rubric_breakdown": asdict(rubric),
            "attractiveness_score": attractiveness_100,
            "suitability_score": suitability_100,
            "seller_trust_score": seller_trust_100,
            "data_confidence_score": data_confidence_100,
            "availability_score": availability_100,
            "final_checkout_cost_aud": final_checkout,
            "discount_vs_median_pct": discount_vs_median_pct,
            "cross_retailer_gap_pct": cross_gap_pct,
            "is_actionable": is_actionable,
            "is_error_price_anomaly": int(is_error_price_anomaly),
            "second_source_status": second_source_status,
            "verification_status": f"{price_stage.replace('_', ' ').title()} • {second_source_status}",
            "risk_warnings": risk_warnings
        }
