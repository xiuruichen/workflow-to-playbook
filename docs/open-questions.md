# Open questions for the user

Each has the conservative default I took during the autonomous block (2026-11-07 night).

## Decisions only you can make
1. **Consent and ethics route** for recording anyone other than yourself (roadmap open item). *Default:* the pilot guide assumes the researcher is the participant, or someone who agrees in writing; nothing leaves the computer.
2. **What the first paper is about:** the benchmark, the ask-the-expert loop, or both. The confirmatory results lean toward "the loop is weak and the method fails on compound rules with few visits", which reads as a negative-result paper unless the pilot with a real person goes well. *Default:* report everything, claim nothing about experts.
3. **H7 needs a human-labelled set** (which steps a reviewer calls "reason not visible"). I cannot supply that. *Default:* E6 (classifier vs. planted ground truth) is the only classifier check, and it is a proxy.
4. **Think-aloud audio** (roadmap B8, the cheapest way into class O6) needs a local speech-to-text model and microphone capture. *Default:* not built; the pilot's typed reasons and interview cover the same ground at small scale.
5. **Which theme and which person for the pilot** (`docs/pilot-guide.md`). The best pilot is someone with real experience in the theme.

## Things I could not do
- **Re-score the four scripted scenarios** with the new step-recall and flag-F1 metrics. That needs the cached model answers or a model run (the cloud provider is configured in `.env`, but you asked for no cloud calls). The metrics are implemented and unit-tested; run `python -m playbook.evaluate` when a provider is available.
- **A bigger model than the 4B** for H5 (the 8B does not fit comfortably in 15 GB with the rest of the system).
- **Cloud comparison** for H5.

## Known problems found on the way (not fixed)
- OCR can read `9,871` as `9.871`, which silently turns thousands into decimals (found by comparing the fast harness with real OCR). The triage screen shows amounts without separators to avoid it; a real screen with separators would be misread.
- OCR can drop the space in a label (`Batchsize`); fixed for names that differ only by underscores (`decisions.unify_names`), but not for other variants.
- The decision log needs readouts as `Label: value` text; charts and unlabelled numbers are not read.
- The classifier `knowledge.classify_decision` calls every decision O5 once the fitted rule uses any cross-session feature (see E6).
