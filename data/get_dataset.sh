#!/usr/bin/env bash
# Download the AI4I 2020 Predictive Maintenance dataset (UCI, CC BY 4.0).
#   S. Matzka (2020). AI4I 2020 Predictive Maintenance Dataset. UCI Machine
#   Learning Repository. https://doi.org/10.24432/C5HS5C
# The CSV is not committed to the repository; this script fetches it.
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

URL="https://archive.ics.uci.edu/static/public/601/ai4i+2020+predictive+maintenance+dataset.zip"
OUT="ai4i2020.csv"

if [ -s "$OUT" ]; then
  echo "Dataset already present: data/$OUT ($(($(wc -l < "$OUT") - 1)) rows)"
  exit 0
fi

echo "Downloading AI4I 2020 from UCI ..."
if curl -fsSL --max-time 60 -o ai4i.zip "$URL" && unzip -o -q ai4i.zip "$OUT"; then
  rm -f ai4i.zip
  echo "Saved data/$OUT ($(($(wc -l < "$OUT") - 1)) rows)"
  exit 0
fi
rm -f ai4i.zip

cat <<EOF
Could not download the dataset automatically.
  1. Open https://archive.ics.uci.edu/dataset/601/ai4i+2020+predictive+maintenance+dataset
  2. Download the zip and copy ai4i2020.csv into the data/ folder.
Until then the importer falls back to data/make_synthetic.py (records are
labelled source=synthetic-generator so they are never mistaken for the dataset).
EOF
exit 1
