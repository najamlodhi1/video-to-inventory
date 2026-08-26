# Video → Inventory

Turning a phone walkthrough video of a home into a structured furniture inventory, using
multimodal vision models — with the accuracy and cost of every stage measured rather than
assumed.

Built to explore a specific question: **can a customer's own 3-minute video replace a
professional in-home survey?** Removal quotes are notoriously wrong on the day, and the
information asymmetry is the reason. This is the inference half of that problem.

---

## What this demonstrates

A personal research project, built end to end, on a real computer-vision problem with real
footage rather than a benchmark dataset.

**Computer vision** — frame extraction and sampling strategy · Laplacian-variance sharpness
scoring · perceptual hashing (pHash) for near-duplicate detection · resolution and
tokenisation trade-offs

**Multimodal / VLM engineering** — batched vision-language inference over image sequences ·
prompt and context design · structured JSON output under a strict schema · controlled-
vocabulary classification · confidence calibration · cross-frame entity resolution

**Evaluation** — measuring detection quality against source footage rather than asserting it ·
failure-mode analysis · quality flags that correlate with error · reporting distributions, not
averages

**Production concerns** — content-hash response caching · per-run token and cost accounting ·
rate-limit-aware backoff separated from validation retry · schema validation with loud
failure · staged, independently re-runnable architecture

Applied ML/AI engineering — inference pipelines, evaluation and cost control — rather than
model training. The models are off-the-shelf; the accuracy, the reliability and the economics
are the engineering.

---

## The interesting part isn't the model call

Sending frames to a vision model is easy. Three things make it hard:

**1. The same sofa appears in thirty frames.** Naive per-frame detection reports thirty
sofas. Deduplication has to happen across frames, using room boundaries inferred from the
frame sequence — which is why the detection stage is explicitly instructed *not* to
deduplicate. Repetition is signal.

**2. Vision models are bad at absolute dimensions.** Asking "how many cubic metres is this
sofa?" produces confident nonsense. The pipeline instead classifies into a fixed catalogue
of 78 items and looks the volume up. An unreliable regression problem becomes a reliable
classification problem.

**3. Half the volume is invisible.** A wardrobe isn't a wardrobe — it's a wardrobe plus
eight boxes of clothes you can't see. Storage furniture is detected separately, with a
fullness estimate, so hidden volume can be inferred rather than ignored.

And one that only shows up with real footage: **fitted furniture doesn't move.** A built-in
wardrobe stays with the property. The pipeline separates `fixtures` from `items` — on the
test property that was 10 built-in wardrobes and 5 fitted kitchen units that would otherwise
have been priced as movable.

---

## Architecture

Five stages. **Each reads from disk and writes to disk, and runs independently.**

```
01_extract     video.mp4        →  frames/            ffmpeg @ 6fps
02_filter      frames/          →  keyframes/         sharpness + perceptual hash
03_detect      keyframes/       →  detections.json    Gemini, batched, cached
04_reconcile   detections.json  →  inventory.json     cross-frame merge          [design only]
05_price       inventory.json   →  quote.json         deterministic, no model    [design only]
```

This is the decision the whole project rests on. Tuning a prompt means re-running one stage
against saved intermediate output — no ffmpeg, no API calls, instant feedback. Collapsing
these into a single script would have made iteration ten times slower and every experiment
expensive.

Prompts live in `prompts/*.md`, not in Python, and are loaded at runtime. The cache key is a
hash of the prompt content, so **editing a prompt busts the cache and nothing else does** —
re-running is free until the prompt changes.

---

## Measured results

Test property: 2-bed flat, 2m 45s handheld walkthrough, iPhone, portrait.

### Frame reduction

| Stage | Frames |
|---|---|
| Extracted @ 6fps | 987 |
| Sharpest-per-second window | 165 |
| Passing blur threshold | 70 |
| After perceptual-hash dedup | **66** |

**93.3% reduction**, with the survivors chosen for sharpness rather than sampled blindly.

### Why 6fps and not 1fps

Handheld walkthroughs are heavily motion-blurred. Sampling once per second accepts whatever
sharpness that instant happened to have. Sampling at 6fps and keeping the sharpest frame per
second costs nothing extra at the API — the frame count reaching the model is identical —
and local CPU is free:

| Method | Median Laplacian variance | Usable frames |
|---|---|---|
| Naive 1fps sample | 36 | 5 / 54 |
| **Sharpest-of-6 per second** | **64** | **12 / 54** |

### Cost

66 keyframes ≈ 17,000 image tokens. **~£0.15 per property**, with per-run token and cost
reporting built into the stage. Batched 8 frames per call, concurrent, with rate-limit-aware
backoff kept separate from the JSON-validation retry — a 429 isn't a malformed response and
shouldn't consume a repair attempt.

### Controlled vocabulary: 50% → 100% valid classifications

First run let the model propose catalogue IDs freely. Half were plausible inventions —
`bed_double` against the catalogue's `bed_double_frame`, `nightstand` against
`bedside_table`. It used `table_side` and `side_table` in the same run.

Injecting the catalogue into the prompt as a controlled vocabulary, with an instruction to
return `null` rather than invent, took valid classifications from 50% to 100% across 281
sightings.

**An honest `null` is more useful than a plausible invention** — nulls tell you what the
catalogue is missing; inventions silently corrupt the volume total.

### Spot-check against the source footage

One frame, checked by eye against the video:

- 5 items reported, **5 correct** — including identifying a *recliner* sofa, which is
  materially heavier than a standard one
- 2 items missed, both cut off at the frame edge
- The frame was already flagged `vertical_crop`

**The quality flag correlated with the misses.** That's the useful finding: failures cluster
where the capture is bad, and the pipeline knows when the capture is bad. That's the basis
for a capture-quality score gating how much confidence a quote deserves — rather than
pretending uniform accuracy.

---

## Things real footage taught me

**Portrait video lies about its dimensions.** `ffprobe` reports the stream as 1920×1080.
Extracted frames are 1080×1920 — iPhone stores a 90° rotation in metadata. Trusting the raw
stream dimensions silently breaks resize logic and crops wide furniture. The extract stage
reads rotation explicitly and records it.

**The expected hard problem wasn't the actual hard problem.** The design assumed
double-counting would dominate. On the first real walkthrough, perceptual-hash distance
between consecutive frames had a *median of 30* — no frame was a duplicate at any threshold.
The camera moved too fast to see anything twice. The real problem was coverage, not
duplication. The pipeline changed accordingly.

**People end up in frame.** The prompt sets a flag and refuses to describe them, rather than
producing a description of someone's family in a JSON file.

**Mirrors double-count furniture.** Reflections are captured in a separate field, never as
items.

---

## Status — honest

| Stage | State |
|---|---|
| 01 extract | Complete, tested on real footage |
| 02 filter | Complete, thresholds calibrated on real footage |
| 03 detect | Complete — batching, schema validation, caching, cost reporting, backoff |
| 04 reconcile | **Stub.** Designed in `schemas.md`, not implemented |
| 05 price | **Stub.** Designed, not implemented |

Stages 04 and 05 have defined schemas and a documented approach but no implementation. The
project was built to answer a question about feasibility and cost, and stages 01–03 answered
it. I'd rather leave the remaining stubs clearly labelled than ship something half-working
and call it finished.

`schemas.md` documents the full intended data flow including the unbuilt stages.

---

## Running it

```bash
brew install ffmpeg
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # add your Gemini API key
```

```bash
python pipeline/01_extract.py --home home-01
python pipeline/02_filter.py  --home home-01
python pipeline/03_detect.py  --home home-01
```

Place a video at `data/<home-id>/video.mp4`. Outputs land alongside it.

`data/` is gitignored — the test footage is the inside of my flat.

---

## Stack

Python · ffmpeg · OpenCV (Laplacian sharpness) · ImageHash (perceptual dedup) ·
Google Gemini (multimodal detection) · Pydantic (schema enforcement) · Typer · Rich

## Layout

```
pipeline/     01–05 stages + shared helpers, schemas
prompts/      detect.md — the detection prompt, versioned and cache-keyed
catalogue/    78 UK domestic items: volume, weight class, disassembly, storage flags
schemas.md    full data flow, including the unbuilt stages
```

## Note on the catalogue

Volumes are seed estimates intended to be calibrated against completed jobs, not measured
figures. They're honest placeholders, and labelled as such in `catalogue/items.json`.
