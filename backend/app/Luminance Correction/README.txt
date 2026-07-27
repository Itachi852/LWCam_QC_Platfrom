================================================================================
 LUMINANCE CORRECTION  (standalone, extracted from "All In One Workflow")
================================================================================

Brightness / contrast / luminance correction for scanned document images.
This is the SAME code the All In One Workflow ran as its luminance step, pulled
out to stand alone so the QC module (LWCAM Module 1) can integrate it as the
basis for its single-image and batch luminance correction. No algorithm was
changed; only the surrounding workflow was removed.

--------------------------------------------------------------------------------
 CONTENTS
--------------------------------------------------------------------------------
  luminance_process.py   The correction implementation (self-contained:
                         stdlib + numpy + Pillow only).
  config.txt             Production-tuned settings, extracted verbatim from the
                         All In One Workflow config.json "luminance" block
                         (reference profiles, brightness level, target
                         luminance, exposure/curve params).
  requirements.txt       numpy, Pillow.
  Run_Luminance_Correction.bat   Convenience runner (Windows).

--------------------------------------------------------------------------------
 WHAT IT DOES
--------------------------------------------------------------------------------
Per image: builds a document mask (optionally protecting a black photographed
background), measures document luminance statistics, matches against the
configured reference profiles (or falls back to a target-luminance + tone-curve
correction), optionally applies even-exposure / center-shadow correction, then
rescales luminance while preserving color. TIFF/JPEG/PNG in place; originals are
replaced only after a successful save (atomic temp-file + os.replace).
Preserves EXIF/ICC where present; preserves TIFF compression where technically
possible.

--------------------------------------------------------------------------------
 STANDALONE USE
--------------------------------------------------------------------------------
  pip install -r requirements.txt
  python luminance_process.py          (or double-click the .bat)

It prompts for an image folder, then corrects every supported image
(.jpg/.jpeg/.tif/.tiff/.png) in that folder IN PLACE, using config.txt next to
the script. Worker count derives from processor_usage x CPU cores.

--------------------------------------------------------------------------------
 PROGRAMMATIC USE (how the QC module should call it)
--------------------------------------------------------------------------------
Do NOT rebuild the algorithm. Call it directly, exactly like the original
orchestrator did:

    from luminance_process import process_image, read_config
    from pathlib import Path

    cfg = read_config(Path("config.txt"))   # -> dict[str, str]
    # (or build the same dict from your own settings store; all values are
    #  strings, matching the keys in config.txt)

    process_image(Path(r"...\page0007.tif"), cfg)   # corrects one image in place

For the QC screen's "apply to selected image" use one call; for "batch apply to
selected images" call it per selected page (optionally via a ProcessPool as the
standalone main() does). Wrap each call in the module's draft/commit + local
NVMe working-copy pattern (see MODULE_1_QC_REWORK_DESIGN.txt) so the official
image is replaced only on commit, not on preview.

--------------------------------------------------------------------------------
 CONFIG NOTES
--------------------------------------------------------------------------------
- The reference_profile_* lines are the important tuning: each is
  min_p72,target_p72,max_p72,max_p95,saturation,red_green,blue_green describing a
  class of document (warm/gray/light/cool/orange-archival/neutral). The image is
  matched to the nearest profile within profile_match_threshold; if none match,
  it falls back to target_luminance + the brightness_level tone curve.
- brightness_level (1-3) selects a curve preset + even-exposure strength.
- protect_black_background keeps correction from spilling into a black
  photographed border.
- These values came from the WWII-Medical-Files project; re-tune per project if
  document appearance differs.
