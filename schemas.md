# JSON Schemas — detections, inventory, quote, ground truth

These field names carry through to the Postgres schema later, so keep them stable.

---

## `detections.json` — output of stage 03

One entry per keyframe. The model sees a batch of 8; results are merged into one file.

**This shape is defined by `prompts/detect.md`, not by this document** — the prompt is the
source of truth for stage 03 and evolves independently. `pipeline/schemas.py` implements it
in pydantic (`FrameDetection`, `BatchDetectionResponse`, `DetectionsFile`). If the two ever
disagree, trust the prompt and update this file and `schemas.py` to match, not the other way
round.

```json
{
  "prompt_version": "detect-v1-a1b2c3d4e5",
  "frames": [
    {
      "frame_index": 18,
      "room_guess": "living_room",
      "room_transition": false,
      "people_present": false,
      "items": [
        {
          "label": "3-seat fabric sofa",
          "catalogue_hint": "sofa_3seat",
          "position": "centre-left, against wall",
          "confidence": 0.9,
          "notes": ""
        }
      ],
      "storage_units": [
        {
          "label": "display cabinet, glazed upper",
          "catalogue_hint": "display_cabinet",
          "doors_open": false,
          "fullness": "part_full"
        }
      ],
      "fixtures": [
        { "label": "fitted kitchen units, lower run", "catalogue_hint": null, "notes": "built in, not quoted" }
      ],
      "reflections": [
        { "label": "wardrobe visible in mirror", "catalogue_hint": "wardrobe_2door", "confidence": 0.4, "notes": "unsure if real or reflected" }
      ],
      "access_features": [
        { "type": "doorway", "detail": "standard width, leads to hallway" }
      ],
      "quality_issues": ["overexposed"]
    }
  ]
}
```

**Notes**

- `prompt_version` is derived automatically by stage 03 from a hash of `prompts/detect.md`'s
  contents (`detect-v1-<10 hex chars>`) — it changes whenever the prompt changes, without any
  manual bookkeeping, and is also the thing that busts the `.cache/` key.
- `catalogue_hint` is the model's *guess* at a catalogue ID, on `items`, `storage_units`, and
  `reflections`. Stage 04 does the authoritative mapping — never trust this field directly.
- `room_transition: true` marks a frame where the camera moves into a new room. Stage 04
  uses these to segment rooms; getting this right is most of the deduplication fix.
- `people_present` replaces any description of people or pets in a frame — privacy
  requirement, not a stylistic one. No other field may describe a person.
- `storage_units` is separate from `items` on purpose — wardrobes and units feed the
  hidden-volume proxy as well as counting as furniture themselves. Each records `fullness`
  (`empty` / `part_full` / `full` / `unknown`) and whether `doors_open`.
- `fixtures` are built-in/fitted items that stay with the property and must never be quoted —
  kept separate from `items` so a human can confirm exclusions were correct.
- `reflections` holds anything seen only as a mirror/glass reflection — kept out of `items` to
  avoid double-counting real furniture.
- `quality_issues` allowed values: `dark`, `motion_blur`, `obstructed`, `too_close`,
  `vertical_crop`, `mirror_reflection`, `overexposed`.
- `room_guess` allowed values: `living_room`, `bedroom`, `kitchen`, `dining_room`, `bathroom`,
  `hallway`, `landing`, `stairs`, `office`, `garage`, `loft`, `garden`, `exterior`, `communal`,
  `unknown`.

---

## `inventory.json` — output of stage 04

```json
{
  "home_id": "home-01",
  "prompt_version": "reconcile-v1",
  "rooms": [
    { "room_id": "r1", "type": "living_room", "frame_range": [8, 22] }
  ],
  "items": [
    {
      "catalogue_id": "sofa_3seat",
      "qty": 1,
      "room_id": "r1",
      "confidence": 0.92,
      "source_frames": [10, 12, 15],
      "volume_m3": 1.3,
      "weight_class": "two_person",
      "disassembly": false,
      "fragile": false
    }
  ],
  "unknown_items": [
    {
      "label": "large ceramic planter",
      "room_id": "r3",
      "est_volume_m3": 0.2,
      "source_frames": [41],
      "confidence": 0.55
    }
  ],
  "access": {
    "floors": 2,
    "stairs_internal": true,
    "stairs_to_entrance": 3,
    "lift": false,
    "parking_distance_m": null,
    "narrow_doorway": false,
    "captured_from_video": true
  },
  "hidden_volume_proxy": {
    "storage_units": [
      { "catalogue_id": "wardrobe_3door", "qty": 1, "box_equivalents": 9 }
    ],
    "total_box_equivalents": 22,
    "customer_stated_boxes": null,
    "discrepancy_flag": false
  },
  "totals": {
    "visible_volume_m3": 14.2,
    "hidden_volume_m3": 1.32,
    "total_volume_m3": 15.52
  },
  "job_confidence": 0.78,
  "review_flags": [
    "3 unknown items",
    "parking distance not captured in video",
    "bedroom 2 only visible in 2 frames"
  ]
}
```

**Notes**

- `source_frames` is non-negotiable. When volume is wrong you need to see which frames
  produced the item — it's how you diagnose double-counting and how you defend the
  approach under questioning.
- `qty` handles the genuine multiples case: six dining chairs are one entry with `qty: 6`.
- `parking_distance_m` stays `null` until guided capture ships. A null here should raise a
  `review_flag` — a missing carry distance is a common cause of a blown quote.
- `customer_stated_boxes` is filled from the Q&A step later. When it and
  `total_box_equivalents` diverge past a threshold, set `discrepancy_flag` and route to review.
- `job_confidence` drives both the pricing buffer and the review triage.

---

## `quote.json` — output of stage 05

```json
{
  "home_id": "home-01",
  "volume_m3": 15.52,
  "van_size": "luton",
  "crew_size": 2,
  "estimated_hours": 5.5,
  "hours_breakdown": {
    "base_from_volume": 3.8,
    "access_multiplier": 1.25,
    "carry_distance_add": 0.4,
    "disassembly_add": 0.5
  },
  "distance_miles": 8,
  "price_before_buffer": 462.0,
  "buffer_pct": 0.12,
  "price": 517.0,
  "driver_payout": 439.45,
  "platform_margin": 77.55,
  "job_confidence": 0.78,
  "requires_review": true
}
```

**Notes**

- `hours_breakdown` must be exposed, not just the total. Crew hours are what the price is
  actually made of, and you'll be calibrating each coefficient against real completed jobs.
- `buffer_pct` scales inversely with `job_confidence`. Lower confidence, bigger buffer.
  Improving accuracy shrinks the buffer — that's the economic point of the accuracy work,
  and it's worth stating that way in the business plan.
- `driver_payout` at 85% of `price`. Keep it visible in the output from day one — it's the
  claim the whole supply-side thesis rests on, and seeing it on every test run keeps you
  honest about whether the margin actually works.

---

## `ground_truth/home-01.json`

Hand-counted. Deliberately minimal — you'll be filling these in with a clipboard.

```json
{
  "home_id": "home-01",
  "counted_by": "Najam",
  "counted_at": "2026-08-18",
  "property_type": "2-bed flat",
  "items": [
    { "catalogue_id": "sofa_3seat", "qty": 1, "room": "living_room" },
    { "catalogue_id": "dining_chair", "qty": 4, "room": "kitchen" }
  ],
  "actual_boxes": 24,
  "access": {
    "floors": 2,
    "stairs_internal": true,
    "stairs_to_entrance": 3,
    "lift": false,
    "parking_distance_m": 35
  },
  "notes": "Loft not filmed. Two items already boxed before recording."
}
```

The `notes` field earns its place — that's where you'll capture the failure modes worth
writing into the decision log.
