"""Prompt template for extracting structured data from grocery receipt emails."""

RECEIPT_SCHEMA = """{
  "store": "HEB",
  "date": "YYYY-MM-DD",
  "order_type": "in_store or curbside",
  "total": 45.23,
  "items": [
    {
      "raw_name": "exact item text from the receipt",
      "canonical_name": "plain english name, lowercase (e.g. 'chicken breast')",
      "quantity": 1,
      "unit": "lb, oz, gal, ct, ...",
      "unit_price": 5.49,
      "line_total": 11.53,
      "category": "produce|dairy|meat|seafood|pantry|frozen|bakery|beverages|household|fee|other"
    }
  ]
}"""


def build_receipt_prompt(text: str) -> str:
    return f"""You are a grocery receipt parser. Below is the plain text of an
email from HEB — either an in-store e-receipt or a curbside/delivery order
confirmation. Extract every line item.

Rules:
- Output ONLY valid JSON matching this schema:
{RECEIPT_SCHEMA}
- raw_name must be copied verbatim from the receipt line.
- canonical_name is your best plain-english name for the product, lowercase,
  no brand names (e.g. "HCF BNLS SKNLS BRST" -> "chicken breast").
- Tax, delivery fees, tips, bag fees, bottle deposits: include them as items
  with category "fee" and a sensible canonical_name ("sales tax", "delivery fee").
- Discounts/coupons: include as category "fee" with a NEGATIVE line_total.
- quantity defaults to 1; weight-priced items use the weight as quantity and
  the per-unit price as unit_price.
- date is the purchase/delivery date in the email, formatted YYYY-MM-DD.
- total is the receipt grand total in dollars.
- If you cannot find a value, use null. Do not invent items.

RECEIPT TEXT:
{text[:8000]}
"""
