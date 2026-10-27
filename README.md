# ARC3 entry lifecycle supervisor

Source for the entry accepted as checkpoint **57586341**, notebook Version 2 /
scriptVersionId **361715082**, public score **27.05**. The gameplay policy is
Daniel Franzen's M2 solution. Project changes concern offline entry lifecycle,
input/source verification, bounded supervision and diagnostics handling.
Wrapper and verification work used AI assistance under the entrant's direction.

This release contains the exact accepted entry bytes. It claims no improvement
over that score and no prize-eligibility ruling. The existing Version 2 was
manually selected for final evaluation on 26 October 2026. Private leaderboard
results are not available here.

## Components and licence scope

Credits: Daniel Franzen M2, Tufa Duck/TAAF, Qwen target/draft models, Intel
AutoRound quantization, SGLang and FlashInfer. See `LICENSE`, `LICENSE-SCOPE.md`,
`THIRD-PARTY-NOTICES.md` and `entry/UPSTREAM-LICENSE.txt`. MIT-0 covers only the
original project contributions described in the scope document. Inherited
policy/source and external components keep their existing terms.

The source does not include model weights, wheels, game data, trajectories,
request logs or private planning. Obtain dependencies separately under their
applicable terms. Their use in a scored notebook does not establish compliance
with every prize/release requirement. Model/vendor eligibility questions remain
unresolved; this release does not claim an organizer exception or legal clearance.

## Verify and reproduce

1. Run `python -B verify_release.py`. It uses the standard library to verify
   manifest hashes, exact embedded payload bytes and Python syntax. It does not
   import the policy, load models, install dependencies or play games.
2. Obtain the exact model-v1 assets, datasets and competition attachment named
   in `entry/kernel-metadata.json`. Required hashes and model shard sizes are
   in `entry/input-pins.json`; source identities/adaptations are separately
   pinned in `source-manifest.json` and `diagnostics-manifest.json`.
3. The accepted platform used RTX Pro 6000 and the Docker digest in the metadata,
   with evaluation internet disabled. A compatible platform and all mounted
   assets are needed for a genuine competition rerun.
4. Copy the entry into your own operation directory and replace its notebook
   identity with an unused slug under your account before any save. The archived
   metadata names the original accepted notebook; do not use it to overwrite
   that entry. Source/pin changes require a separately verified candidate.

Ordinary execution of the accepted notebook writes a placeholder parquet; it
does not run the model. Only the actual Kaggle competition rerun flag enters
the supervised hidden path. Do not simulate that flag to claim platform scoring.
The original embedded manifest contains historical preparation/authorization
labels; the accepted checkpoint result above is the later outcome.

The entry uses 32,400 seconds total, stops work at 31,800 seconds, forces cleanup
at 32,390 seconds and leaves a final 10-second margin. Allocation/queue time and
physical platform teardown are not guarantees supplied by those timers.
Recovery means retaining exact bytes and returned operation IDs, reconciling
ambiguous network results before another request, and preserving the accepted
fallback when setup or evaluation fails.

## Verification and limitations

The separate P1 reliability candidate is **not adopted in this accepted entry**.
Its 73 CPU tests passed on 26 October. Its exact ordinary-mode preflight also
completed on a private CPU Kaggle notebook with all seven checks passing, pinned
source/input identity, private/offline settings and the exact placeholder.
That establishes mounted-input/Linux preflight acceptance, not GPU serving or
hidden-rerun acceptance. Resource-command success does not measure sufficient
RAM/shared-memory capacity. P1 source is outside this accepted-entry release.

E1 was rejected for a per-game regression; R1 v0 was not selected. XQA and H1
remain dormant leads with no accepted gameplay improvement. No model training
was performed. Fresh validation of an improved candidate has not occurred.

Original policy source: https://github.com/da-fr/arc-agi-3-solution at
`10882e332d883af3e61616df8c8a17d03a328a75`.
Accepted notebook:
https://www.kaggle.com/code/jayantsaxena11/arc3-baseline-entry-lifecycle?scriptVersionId=361715082

`MANIFEST.json` records this source distribution. Its hashes establish identity,
not ownership certainty, platform immunity or a future score.
