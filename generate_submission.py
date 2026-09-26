"""
Script to generate submission.jsonl for all 30 canonical challenge test pairs.
Reads dataset/expanded/test_pairs.json and invokes bot.compose().
"""

import json
from pathlib import Path
from bot import compose

DATASET_DIR = Path(__file__).parent / "dataset"
EXPANDED_DIR = DATASET_DIR / "expanded"
TEST_PAIRS_FILE = EXPANDED_DIR / "test_pairs.json"
SUBMISSION_FILE = Path(__file__).parent / "submission.jsonl"


def load_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def main():
    print(f"Loading test pairs from {TEST_PAIRS_FILE}...")
    test_pairs_data = load_json(TEST_PAIRS_FILE)
    pairs = test_pairs_data.get("pairs", [])
    print(f"Found {len(pairs)} test pairs.")

    # Load categories cache
    categories = {}
    for cat_file in (DATASET_DIR / "categories").glob("*.json"):
        cat_data = load_json(cat_file)
        categories[cat_data.get("slug", cat_file.stem)] = cat_data

    submissions = []

    for pair in pairs:
        test_id = pair["test_id"]
        trigger_id = pair["trigger_id"]
        merchant_id = pair["merchant_id"]
        customer_id = pair.get("customer_id")

        # Load trigger
        trig_path = EXPANDED_DIR / "triggers" / f"{trigger_id}.json"
        if not trig_path.exists():
            # Fallback to seeds
            trig_path = DATASET_DIR / "triggers_seed.json"
            seed_data = load_json(trig_path)
            trigger = next((t for t in seed_data.get("triggers", []) if t["id"] == trigger_id), None)
        else:
            trigger = load_json(trig_path)

        # Load merchant
        m_path = EXPANDED_DIR / "merchants" / f"{merchant_id}.json"
        if not m_path.exists():
            seed_data = load_json(DATASET_DIR / "merchants_seed.json")
            merchant = next((m for m in seed_data.get("merchants", []) if m["merchant_id"] == merchant_id), None)
        else:
            merchant = load_json(m_path)

        # Load category
        cat_slug = merchant.get("category_slug", "dentists")
        category = categories.get(cat_slug, {})

        # Load customer if present
        customer = None
        if customer_id:
            c_path = EXPANDED_DIR / "customers" / f"{customer_id}.json"
            if c_path.exists():
                customer = load_json(c_path)
            else:
                seed_data = load_json(DATASET_DIR / "customers_seed.json")
                customer = next((c for c in seed_data.get("customers", []) if c["customer_id"] == customer_id), None)

        composed = compose(
            category=category,
            merchant=merchant,
            trigger=trigger,
            customer=customer
        )

        entry = {
            "test_id": test_id,
            "body": composed["body"],
            "cta": composed["cta"],
            "send_as": composed["send_as"],
            "suppression_key": composed["suppression_key"],
            "rationale": composed["rationale"]
        }
        submissions.append(entry)

    print(f"Writing {len(submissions)} entries to {SUBMISSION_FILE}...")
    with open(SUBMISSION_FILE, "w", encoding="utf-8") as f:
        for entry in submissions:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    print(f"Successfully generated {SUBMISSION_FILE} with {len(submissions)} lines.")


if __name__ == "__main__":
    main()
