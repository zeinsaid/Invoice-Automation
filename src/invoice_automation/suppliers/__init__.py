"""Supplier profiles (D-005). Each module knows one supplier's invoice layout.

A profile provides:
- SUPPLIER: the supplier's name in PowerSoft
- matches(page_text) -> bool: is this page from this supplier?
- parse(layout_result, source, page_index) -> Invoice
Table-style invoices share their parsing in base.py.
"""

from . import (agrotis, agrotis_pos, andrikian, athenites, cassandra, cocacola, cosmos, example, fereos, jumbo, pambos,
               partyice, rainbow, vassos)

# agrotis_pos before agrotis: both are Agrotis, and only the shop-counter printout has an 'S02 - ' number.
PROFILES = [athenites, cassandra, cosmos, fereos, andrikian, vassos, agrotis_pos, agrotis, rainbow, pambos, partyice, jumbo,
            cocacola, example]  # example: the made-up demo supplier

# Suppliers the tool recognises but deliberately skips (D-013), with the message for the report.
SKIPPED = {
    "ARISTIDOU": "Aristidou (water): please enter by hand.",
    "ED SPORT": "ED Sport: handwritten, please enter by hand.",
    "ZHENG DONISCHAL": "Asian Food Market: please enter by hand (not automated yet).",
}


def identify(page_text: str):
    """Return the profile module for this page, or None if no profile recognises it."""
    for profile in PROFILES:
        if profile.matches(page_text):
            return profile
    return None


def skipped_reason(page_text: str) -> str | None:
    text = page_text.upper()
    return next((msg for marker, msg in SKIPPED.items() if marker in text), None)
