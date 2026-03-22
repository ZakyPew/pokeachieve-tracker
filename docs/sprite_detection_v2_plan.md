# Sprite Detection V2 (Reset Plan)

## Why V1 keeps failing

Observed in logs:
- `sprite_roi` drifts to edge/invalid regions.
- `sprite_match_distance` remains high while `sprite_confidence_ok=false`.
- repeated unresolved starts (`species_id=0`) during active battle.
- occasional wrong lock after long delay (false positive species resolution).

Root issue: classification is being attempted without a stable tracked target box.

## V2 Goal

Split into two independent stages:
1. `BattleStateDetector` (are we in battle / same battle / battle ended?)
2. `TargetTracker+Classifier` (where is enemy sprite, then what species is it?)

Do not classify until target tracking is stable for N consecutive frames.

## Research basis (primary references)

- OpenCV template matching (`matchTemplate`) and score behavior:
  https://docs.opencv.org/4.x/de/da9/tutorial_template_matching.html
- ORB + BFMatcher (robust local descriptor matching):
  https://docs.opencv.org/4.x/dc/dc3/tutorial_py_matcher.html
- ORB descriptor details:
  https://docs.opencv.org/3.4/d1/d89/tutorial_py_orb.html
- Lucas-Kanade optical flow (short-term point tracking):
  https://docs.opencv.org/4.x/d4/dee/tutorial_optical_flow.html
- Kalman filter for temporal smoothing:
  https://docs.opencv.org/4.x/dd/d6a/classcv_1_1KalmanFilter.html
- SiamFC tracking concept (tracking by similarity):
  https://arxiv.org/abs/1606.09549
- DiMP tracker (discriminative online model prediction):
  https://arxiv.org/abs/1904.01888
- ByteTrack data-association principle (keep low-score candidates for continuity):
  https://arxiv.org/abs/2110.06864

## V2 architecture

### 1) BattleStateDetector (hard gate)
Inputs per frame:
- textbox ROI score
- HUD ROI score
- frame difference vs prior frame

Outputs:
- `state`: `out_of_battle | battle_entering | in_battle | battle_exiting`
- `battle_token`

Rules:
- Enter battle only after `enter_confirm_frames`.
- Exit only after `exit_confirm_frames` and cooldown.
- During `in_battle`, duplicate suppression is based on token, not repeated species events.

### 2) Target localizer (coarse-to-fine)
At battle entry:
- Start from configured manual ROI.
- Generate local window proposals around it (small translations/scales).
- Score proposals with normalized template response + edge/detail constraints.

During battle:
- Track by local search around previous box first.
- Use ORB keypoint matches as fallback if template score degrades.
- Smooth center/size with Kalman-style temporal update.

### 3) Species classifier (only after tracking lock)
- Build one crop stack across `k` tracked frames.
- Compute species score for each frame, aggregate by robust median.
- Require both:
  - `score_threshold`
  - `margin_threshold` (best vs 2nd)
- Resolve species only when lock conditions hold for `lock_frames`.

### 4) Re-validation loop
After first species resolve:
- Keep validating against tracked crop.
- If disagreement appears, do not switch species immediately.
- Open a `reacquire` state requiring stricter evidence before any change.

## Safety rules to prevent false locks

- Never run full-frame species search by default.
- Never allow species switch within same battle token unless explicit override gate passes.
- If tracking confidence drops below threshold, emit `tracking_lost` instead of guessing species.

## Required telemetry (must log every frame in battle)

- battle state + token
- tracked ROI + tracking confidence
- classifier best/second score + margin
- decision reason (`resolved`, `pending`, `reacquire`, `lost`)

## Evaluation protocol

Use deterministic replay of captured encounter clips.
Metrics:
- battle detection precision/recall
- species top-1 accuracy
- time-to-first-correct-resolve
- wrong-lock count per 100 encounters
- mid-battle species-switch count (target: 0)

## Rollout

1. Implement V2 behind `video_detection_v2_enabled`.
2. Keep V1 unchanged for fallback.
3. Run side-by-side on your logs.
4. Promote V2 only if wrong-lock and switch metrics beat V1 by defined margin.

## OCR replacement research (AI text path)

If we replace classic OCR for battle text/nameplate, use a detector+recognizer stack:
- CRAFT text detector (character-region awareness): https://arxiv.org/abs/1904.01941
- CRNN text recognizer: https://arxiv.org/abs/1507.05717
- TrOCR (transformer OCR): https://arxiv.org/abs/2109.10282

Recommended usage in this project:
- Keep Tesseract as fallback.
- Run AI text only on stable ROIs after battle state is `in_battle`.
- Require temporal agreement across consecutive frames before species override.