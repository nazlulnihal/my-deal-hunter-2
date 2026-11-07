"""
Natural-Language Interest Parser (`services/interest_parser.py`) &
180-Day Price History + Australian Sale Calendar Buy/Wait Engine (`services/price_history.py`).
"""

import json
import re
import statistics
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from .product_matcher import UNIVERSAL_CATEGORIES


AUSTRALIAN_SHOPPING_EVENTS = [
    {"name": "Click Frenzy Main Event", "month": 11, "day": 12, "avg_drop_pct": 20},
    {"name": "Black Friday Australia", "month": 11, "day": 27, "avg_drop_pct": 30},
    {"name": "Cyber Monday Australia", "month": 11, "day": 30, "avg_drop_pct": 28},
    {"name": "Boxing Day National Sales", "month": 12, "day": 26, "avg_drop_pct": 32},
    {"name": "EOFY (End of Financial Year) Sale", "month": 6, "day": 15, "avg_drop_pct": 30},
    {"name": "Amazon Prime Day Australia", "month": 7, "day": 14, "avg_drop_pct": 26},
]


class InterestAndHistoryService:
    """
    Parses natural-language shopping requirements (Exact, Multiple Acceptable, Broad)
    with Refurbished/Open-Box toggle support, and computes 7d/30d/90d/180d price history
    statistics and Buy/Consider/Wait guidance.
    """

    CATEGORY_MAP = {
        "Smartphones, Smartwatches & Tablets": ["phone", "android", "iphone", "galaxy", "s25", "s26", "pixel", "watch", "smartwatch", "ipad", "tablet"],
        "TVs, Audio & Gaming": ["headphone", "earbud", "wh-1000", "sony", "bose", "tv", "oled", "ps5", "speaker", "soundbar"],
        "Home Appliances & Coffee Machines": ["coffee machine", "espresso", "breville", "delonghi", "vacuum", "dyson", "roborock", "air fryer", "fridge"],
        "Groceries, Chocolates & Beverages": ["chocolate", "lindt", "ferrero", "haigh", "coffee beans", "lavazza", "grocery", "snack", "pantry", "beverage", "protein"],
        "Personal Care, Skincare & Cosmetics": ["shampoo", "skincare", "cerave", "perfume", "cosmetic", "toothpaste", "grooming"],
        "Household Consumables & Cleaning": ["detergent", "laundry", "omo", "dishwashing", "finish", "fairy", "cleaning", "toilet paper"],
        "Tools, Hardware & Gardening": ["drill", "makita", "ryobi", "bunnings", "tool", "mower"],
    }

    KNOWN_BRANDS = [
        "Samsung", "Apple", "Sony", "Google", "Motorola", "Garmin", "Bose", "Sennheiser",
        "LG", "Breville", "De'Longhi", "Dyson", "Roborock", "Lindt", "Ferrero", "Lavazza",
        "Musashi", "Omo", "Head & Shoulders", "CeraVe", "Makita", "Ryobi"
    ]

    def parse_interest(
        self,
        raw_input: str,
        catalog_products: List[Dict[str, Any]],
        include_refurbished: bool = False,
        added_method: str = "natural_language",
        scanned_barcode: Optional[str] = None
    ) -> Dict[str, Any]:
        q = raw_input.strip()
        ql = q.lower()

        # Budget extraction
        b_match = re.search(r"(?:under|around|below|max|<|\$)\s*(?:aud\s*)?\$?\s*(\d+(?:\.\d{1,2})?)", ql)
        if not b_match:
            b_match = re.search(r"aud\s*\$?\s*(\d+(?:\.\d{1,2})?)", ql)
        max_budget = float(b_match.group(1)) if b_match else None
        target_price = round(max_budget * 0.85, 2) if max_budget else None

        # Category detection
        category = "Computers & Electronics"
        for cat, kws in self.CATEGORY_MAP.items():
            if any(kw in ql for kw in kws):
                category = cat
                break

        brands = [b for b in self.KNOWN_BRANDS if b.lower() in ql]

        # Classify Exact vs Multiple vs Broad
        has_or = bool(re.search(r"\bor\b", ql))
        has_broad_words = any(w in ql for w in ["any good", "a good", "reliable", "decent", "good chocolates", "under", "around", "wireless headphones"])
        has_exact_model = bool(re.search(r"(watch\s*\d+|s2\d\s*ultra|wh-1000xm\d|bes\d{3}|pixel\s*\d+|333g|1kg)", ql))

        if added_method == "barcode_scan" or (has_exact_model and not has_or):
            interest_type = "exact"
        elif has_or:
            interest_type = "multiple"
        elif has_broad_words or not has_exact_model:
            interest_type = "broad"
        else:
            interest_type = "exact"

        # Generate product shortlist from catalog
        shortlist = []
        for p in catalog_products:
            score = 0
            if p["category"] == category:
                score += 40
            if scanned_barcode and str(p.get("barcode_ean_upc")) == str(scanned_barcode):
                score += 100
            tokens = [t for t in re.findall(r"[a-z0-9]+", ql) if len(t) > 2]
            hits = [t for t in tokens if t in p["canonical_name"].lower() or t in p.get("specs_json", "").lower()]
            score += len(hits) * 15
            if brands and p["brand"] in brands:
                score += 25
            if max_budget and float(p["normal_market_price_aud"]) <= max_budget * 1.3:
                score += 15

            if score >= 45:
                shortlist.append({
                    "product_id": p["id"],
                    "canonical_name": p["canonical_name"],
                    "brand": p["brand"],
                    "normal_market_price_aud": p["normal_market_price_aud"],
                    "suitability_score": min(99, score),
                    "exact_product_url": p["exact_product_url"]
                })

        shortlist.sort(key=lambda x: x["suitability_score"], reverse=True)
        conditions = ["New", "Refurbished", "Open-Box"] if include_refurbished else ["New"]

        return {
            "name": q[:68],
            "natural_query": q,
            "interest_type": interest_type,
            "added_method": added_method,
            "scanned_barcode": scanned_barcode,
            "category": category,
            "preferred_brands": brands,
            "max_budget_aud": max_budget,
            "target_price_aud": target_price,
            "include_refurbished": int(include_refurbished),
            "acceptable_conditions": conditions,
            "shortlist": shortlist[:5],
            "priority": "critical" if interest_type == "exact" else "high",
            "monitoring_frequency_mins": 15
        }

    def compute_history_and_buy_wait(
        self,
        product: Dict[str, Any],
        observations: List[Dict[str, Any]],
        reference_now: Optional[datetime] = None
    ) -> Dict[str, Any]:
        now = reference_now or datetime(2026, 11, 8, tzinfo=timezone.utc)
        pts = []
        for o in observations:
            try:
                dt = datetime.fromisoformat(o["observed_at"].replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                pts.append((dt, float(o["listed_price_aud"]), o))
            except Exception:
                continue
        pts.sort(key=lambda x: x[0])

        def win(days: int) -> List[float]:
            cutoff = now - timedelta(days=days)
            return [p for d, p, _ in pts if d >= cutoff]

        p7, p30, p90, p180 = win(7), win(30), win(90), win(180)
        all_p = [p for _, p, _ in pts] or [float(product["normal_market_price_aud"])]
        pool_90 = p90 if p90 else all_p

        low_90 = round(min(pool_90), 2)
        high_180 = round(max(p180 if p180 else all_p), 2)
        avg_90 = round(statistics.mean(pool_90), 2)
        med_90 = round(statistics.median(pool_90), 2)
        curr_p = all_p[-1]

        disc_vs_med = ((med_90 - curr_p) / med_90) * 100.0 if med_90 > 0 else 0.0
        if curr_p <= low_90 * 1.03 and disc_vs_med >= 20.0:
            verdict = "Buy"
            reasoning = (
                f"BUY NOW: Current price (AUD {curr_p:.2f}) is at the 90-day observed floor (AUD {low_90:.2f}) "
                f"and {disc_vs_med:.0f}% below the 90-day median (AUD {med_90:.2f}). Even with Click Frenzy & Black Friday "
                f"in November, historical records indicate this price tier is an immediate buy. (Historical analysis is probabilistic, not guaranteed.)"
            )
        elif disc_vs_med >= 10.0:
            verdict = "Consider"
            reasoning = (
                f"CONSIDER: Priced {disc_vs_med:.0f}% below the 90-day median (AUD {med_90:.2f}), though above the "
                f"90-day floor of AUD {low_90:.2f}. Buy if needed now, or hold for Black Friday / Boxing Day."
            )
        else:
            verdict = "Wait"
            reasoning = (
                f"WAIT: Current price (AUD {curr_p:.2f}) is near or above the 90-day median (AUD {med_90:.2f}). "
                f"Wait for upcoming Australian promotional cycles (Click Frenzy, Black Friday, EOFY)."
            )

        return {
            "observation_count": len(pts),
            "is_observed_data": len(pts) >= 2,
            "lowest_7d_aud": round(min(p7), 2) if p7 else low_90,
            "lowest_30d_aud": round(min(p30), 2) if p30 else low_90,
            "lowest_90d_aud": low_90,
            "lowest_180d_aud": round(min(p180 if p180 else all_p), 2),
            "highest_180d_aud": high_180,
            "average_90d_aud": avg_90,
            "median_90d_aud": med_90,
            "current_price_aud": curr_p,
            "buy_wait_verdict": verdict,
            "buy_wait_reasoning": reasoning,
            "series": [
                {
                    "date": dt.strftime("%Y-%m-%d"),
                    "price_aud": round(p, 2),
                    "retailer": o["retailer"],
                    "condition": o.get("condition", "New"),
                    "is_sample_data": bool(o.get("is_sample_data", 0))
                }
                for dt, p, o in pts
            ]
        }
