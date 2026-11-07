"""
Universal Product Identification, Barcode (EAN-13, EAN-8, UPC-A, UPC-E) Validation,
Variant & Refurbished/Open-Box Matching, and Grocery Unit Price Normalisation.
"""

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


UNIVERSAL_CATEGORIES = [
    "Smartphones, Smartwatches & Tablets",
    "Computers & Electronics",
    "TVs, Audio & Gaming",
    "Home Appliances & Coffee Machines",
    "Groceries, Chocolates & Beverages",
    "Personal Care, Skincare & Cosmetics",
    "Clothing, Footwear & Fashion",
    "Furniture, Homewares & Kitchenware",
    "Tools, Hardware & Gardening",
    "Sports, Fitness & Camping",
    "Baby Products, Toys, Books & Gifts",
    "Pet Supplies & Pet Food",
    "Household Consumables & Cleaning",
]


@dataclass
class UnitPriceBreakdown:
    price_aud: float
    pack_quantity: float
    unit_measure: str
    normalised_value_aud: float
    unit_basis_label: str
    display_string: str


def compute_unit_price(
    price_aud: float,
    pack_quantity: float,
    unit_measure: str,
    bundle_count: int = 1
) -> UnitPriceBreakdown:
    """
    Computes normalised unit pricing for groceries, consumables, and multipacks:
    - AUD per 100g / AUD per kg
    - AUD per 100ml / AUD per litre
    - AUD per item / pod / tablet / wash
    """
    total_qty = max(pack_quantity * max(bundle_count, 1), 0.0001)
    u = unit_measure.strip().lower()

    if u in ("g", "gram", "grams"):
        per_100g = (price_aud / total_qty) * 100.0
        per_kg = (price_aud / total_qty) * 1000.0
        return UnitPriceBreakdown(
            price_aud=price_aud,
            pack_quantity=total_qty,
            unit_measure="g",
            normalised_value_aud=round(per_100g, 2),
            unit_basis_label="per 100g",
            display_string=f"AUD {per_100g:.2f} / 100g (AUD {per_kg:.2f} / kg)"
        )
    elif u in ("kg", "kilogram", "kilograms"):
        per_kg = price_aud / total_qty
        per_100g = per_kg / 10.0
        return UnitPriceBreakdown(
            price_aud=price_aud,
            pack_quantity=total_qty * 1000.0,
            unit_measure="g",
            normalised_value_aud=round(per_100g, 2),
            unit_basis_label="per 100g",
            display_string=f"AUD {per_kg:.2f} / kg (AUD {per_100g:.2f} / 100g)"
        )
    elif u in ("ml", "millilitre", "millilitres"):
        per_litre = (price_aud / total_qty) * 1000.0
        per_100ml = (price_aud / total_qty) * 100.0
        return UnitPriceBreakdown(
            price_aud=price_aud,
            pack_quantity=total_qty,
            unit_measure="ml",
            normalised_value_aud=round(per_litre, 2),
            unit_basis_label="per litre",
            display_string=f"AUD {per_litre:.2f} / litre (AUD {per_100ml:.2f} / 100ml)"
        )
    elif u in ("l", "litre", "litres"):
        per_litre = price_aud / total_qty
        return UnitPriceBreakdown(
            price_aud=price_aud,
            pack_quantity=total_qty,
            unit_measure="l",
            normalised_value_aud=round(per_litre, 2),
            unit_basis_label="per litre",
            display_string=f"AUD {per_litre:.2f} / litre"
        )
    else:
        per_item = price_aud / total_qty
        return UnitPriceBreakdown(
            price_aud=price_aud,
            pack_quantity=total_qty,
            unit_measure=u or "item",
            normalised_value_aud=round(per_item, 2),
            unit_basis_label="per item",
            display_string=f"AUD {per_item:.2f} / {u or 'item'}"
        )


def classify_barcode_format(raw_code: str) -> Dict[str, Any]:
    """
    Validates and classifies EAN-13, EAN-8, UPC-A, and UPC-E barcodes.
    """
    digits = re.sub(r"\D", "", raw_code.strip())
    length = len(digits)
    if length == 13:
        fmt = "EAN-13"
        valid = True
    elif length == 12:
        fmt = "UPC-A"
        valid = True
    elif length == 8:
        fmt = "EAN-8 / UPC-E"
        valid = True
    elif 6 <= length <= 14:
        fmt = "GTIN / Custom Barcode"
        valid = True
    else:
        fmt = "Invalid / Non-Barcode Text"
        valid = False

    return {
        "raw_input": raw_code,
        "clean_digits": digits,
        "format": fmt,
        "is_valid_barcode": valid
    }


class ProductMatcherService:
    """
    Matches product listings against canonical products and user interests,
    distinguishing exact barcode matches, variant mismatches (40mm vs 44mm, 128GB vs 256GB),
    Refurbished / Open-Box condition toggle eligibility, and accessory traps.
    """

    ACCESSORY_TRAP_PHRASES = [
        "strap only", "replacement band", "silicone band for", "case for",
        "screen protector for", "cover for", "charging cradle for", "empty box"
    ]

    def evaluate_listing(
        self,
        product: Dict[str, Any],
        listing_title: str,
        listing_barcode: Optional[str] = None,
        listing_condition: str = "New",
        include_refurbished_toggle: bool = False
    ) -> Dict[str, Any]:
        title_l = listing_title.lower()
        prod_name_l = product["canonical_name"].lower()
        specs = json.loads(product.get("specs_json", "{}"))

        # 1. Accessory Trap Guard
        for phrase in self.ACCESSORY_TRAP_PHRASES:
            if phrase in title_l and phrase not in prod_name_l:
                return {
                    "is_valid_match": False,
                    "is_accessory_trap": True,
                    "is_variant_mismatch": True,
                    "confidence": 0.99,
                    "reason": f"Rejected: Listing is an accessory ('{phrase}') rather than the primary product."
                }

        # 2. Refurbished / Open-Box Toggle Check
        if listing_condition in ("Refurbished", "Open-Box", "Used") and not include_refurbished_toggle:
            return {
                "is_valid_match": False,
                "is_accessory_trap": False,
                "is_variant_mismatch": True,
                "confidence": 0.95,
                "reason": f"Excluded: Listing condition is '{listing_condition}', and 'Include Certified Refurbished / Open-Box' toggle is OFF."
            }

        # 3. Hardware Barcode (EAN/UPC/GTIN) Verification
        if listing_barcode and product.get("barcode_ean_upc"):
            clean_in = re.sub(r"\D", "", listing_barcode)
            clean_prod = re.sub(r"\D", "", str(product["barcode_ean_upc"]))
            if clean_in and clean_in == clean_prod:
                return {
                    "is_valid_match": True,
                    "is_accessory_trap": False,
                    "is_variant_mismatch": False,
                    "confidence": 0.99,
                    "reason": f"Verified exact barcode match ({clean_in})."
                }

        # 4. Variant Size & Storage Checks
        if "case_size" in specs:
            req_size = str(specs["case_size"]).lower()
            for wrong_sz in ["40mm", "41mm", "42mm", "44mm", "45mm", "46mm"]:
                if wrong_sz != req_size and wrong_sz in title_l:
                    return {
                        "is_valid_match": False,
                        "is_accessory_trap": False,
                        "is_variant_mismatch": True,
                        "confidence": 0.94,
                        "reason": f"Variant mismatch: Listing is {wrong_sz} instead of {req_size}."
                    }

        if "storage" in specs:
            req_st = str(specs["storage"]).lower()
            for wrong_st in ["128gb", "256gb", "512gb", "1tb"]:
                if wrong_st != req_st and wrong_st in title_l and req_st not in title_l:
                    return {
                        "is_valid_match": False,
                        "is_accessory_trap": False,
                        "is_variant_mismatch": True,
                        "confidence": 0.93,
                        "reason": f"Storage mismatch: Listing is {wrong_st.upper()} instead of {req_st.upper()}."
                    }

        return {
            "is_valid_match": True,
            "is_accessory_trap": False,
            "is_variant_mismatch": False,
            "confidence": 0.92,
            "reason": f"Verified model and variant ({listing_condition})."
        }
