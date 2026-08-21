"""
Helper script to test the two-stage Schematic Crop Review API.
Usage:
  python scripts/test_crop_review.py path/to/schematic_crop.png
"""

import sys
import os
import requests

SERVER_URL = "http://127.0.0.1:8000"


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/test_crop_review.py <path_to_crop_image>")
        print("Example: python scripts/test_crop_review.py data/schematic_crops/vddp_decoupling_01.png")
        sys.exit(1)

    image_path = sys.argv[1]
    if not os.path.exists(image_path):
        print(f"Error: File not found at {image_path}")
        sys.exit(1)

    print(f"--- Stage 1: Parsing Crop Image '{image_path}' ---")
    with open(image_path, "rb") as f:
        files = {"image": (os.path.basename(image_path), f, "image/png")}
        data = {"device_hint": "TLE987x"}
        res1 = requests.post(f"{SERVER_URL}/schematic/parse/crop", files=files, data=data)

    if res1.status_code != 200:
        print(f"Stage 1 Error ({res1.status_code}): {res1.text}")
        sys.exit(1)

    parse_data = res1.json()
    review_id = parse_data["review_id"]
    print(f"✅ Stage 1 Success!")
    print(f"Review ID: {review_id}")
    print(f"Needs Confirmation: {parse_data['needs_confirmation']}")
    print(f"Suggested Section: {parse_data['suggested_section']}")
    print("\nSection Candidates:")
    for cand in parse_data["section_candidates"]:
        print(f" - [{cand['section_id']}] {cand['name']} (Confidence: {cand['confidence']})")
        print(f"   Matched Evidence: {cand['matched_evidence']}")

    selected_section = parse_data['suggested_section'] or "VDDP_DECOUPLING"
    print(f"\n--- Stage 2: Reviewing Selected Section '{selected_section}' ---")
    res2 = requests.post(
        f"{SERVER_URL}/schematic/review/crop/{review_id}",
        json={"selected_section": selected_section}
    )

    if res2.status_code != 200:
        print(f"Stage 2 Error ({res2.status_code}): {res2.text}")
        sys.exit(1)

    review_data = res2.json()
    print(f"✅ Stage 2 Success!")
    print(f"Summary Status: {review_data['summary_status']}")
    print("\nFindings:")
    for finding in review_data["findings"]:
        print(f"\n[{finding['check_id']}] {finding['check_name']} — Status: {finding['status']}")
        print(f"Reason: {finding['decision_reasoning']}")
        if finding.get("reference_evidence"):
            ref = finding["reference_evidence"]
            print(f"Reference Citation: Page {ref.get('page')}, Sec {ref.get('section')}")


if __name__ == "__main__":
    main()
