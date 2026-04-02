import csv
from collections import defaultdict

INPUT_FILE = "OCR_Olive.csv"
OUTPUT_FILE = "OCR_Olive_joined.csv"

# 1. Read all rows
with open(INPUT_FILE, "r", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    rows = list(reader)

print(f"Input: {len(rows)} rows, {len(set(r['goodsno'] for r in rows))} unique goodsno")

# 2. Group by goodsno
grouped = defaultdict(list)
for r in rows:
    grouped[r["goodsno"]].append(r)

# 3. Collect all gv_types across entire dataset (sorted)
all_gv_types = sorted(set(r["gv_type"] for r in rows))
print(f"gv_types: {all_gv_types}")

# 4. Build output rows: one per goodsno
output_rows = []
for goodsno, rlist in grouped.items():
    # Common fields: take from latest table_update_dt row
    rlist_sorted = sorted(rlist, key=lambda r: r["table_update_dt"] or "", reverse=True)
    latest = rlist_sorted[0]

    row = {
        "goodsno": goodsno,
        "reg_date": latest["reg_date"],
        "master_cd": latest["master_cd"],
        "table_update_dt": latest["table_update_dt"],
    }

    # Per gv_type: collect unique OCR results and image URLs
    gv_data = defaultdict(lambda: {"ocr": [], "images": []})
    for r in rlist:
        gv = r["gv_type"]
        ocr = r["ocr_result"].strip()
        img = r["image_url"].strip()
        if ocr and ocr not in gv_data[gv]["ocr"]:
            gv_data[gv]["ocr"].append(ocr)
        if img and img not in gv_data[gv]["images"]:
            gv_data[gv]["images"].append(img)

    for gv_type in all_gv_types:
        ocr_texts = gv_data[gv_type]["ocr"]
        images = gv_data[gv_type]["images"]
        # Concatenate multiple OCR results with separator
        row[f"ocr_{gv_type}"] = "\n---\n".join(ocr_texts)
        row[f"image_{gv_type}"] = " | ".join(images)

    output_rows.append(row)

# 5. Write output
fieldnames = ["goodsno", "reg_date", "master_cd", "table_update_dt"]
for gv_type in all_gv_types:
    fieldnames.append(f"ocr_{gv_type}")
    fieldnames.append(f"image_{gv_type}")

with open(OUTPUT_FILE, "w", encoding="utf-8", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(output_rows)

print(f"Output: {len(output_rows)} rows written to {OUTPUT_FILE}")
print(f"Columns: {len(fieldnames)}")
