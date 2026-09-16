# Reviews and evidence

This area contains dated assessments and the receipts used to support them.
They preserve project history and should be read as snapshots, not as current
implementation instructions.

- `design-review-2026-09-10.md` records the earlier architecture and product
  review.
- `data-plugin-comparative-review-2026-09-14.md` compares this project with
  the installed Data plugin.
- `data-plugin-standalone-review-2026-09-14.md` is the detailed review.
- `review-packet.html` is the combined, self-contained reading packet.
- `data-plugin-review-evidence/` contains test logs, screenshots, source
  hashes, and validation receipts for the standalone review.

The standalone review HTML is generated from its Markdown source with:

```sh
node doc/reviews/data-plugin-review-evidence/build-report.mjs
```

The combined packet is generated with:

```sh
python3 scripts/build_review_packet.py
```
