# Open questions and known problems

## Decisions still to make

1. **Consent and ethics** for recording anyone other than the researcher. Until decided, the pilot guide assumes the participant is the researcher or someone who agrees in writing, and nothing leaves the computer.
2. **Scope of the first paper:** the benchmark, the ask-the-expert loop, or both. The results so far (the loop helps little; compound rules need about 100 visits) read as a paper with negative and mixed findings unless the pilot goes well.
3. **A human-labelled set for H7** (which steps a reviewer calls "reason not visible"). Until it exists, E6 (the classifier against planted ground truth) is the only check, and it is a proxy.
4. **Think-aloud audio** (roadmap B8, the cheapest route to class O6) needs a local speech-to-text dependency and microphone capture. Not built; the pilot's typed reasons and interview cover the same ground at small scale.
5. **Theme and participant for the pilot** ([pilot-guide.md](pilot-guide.md)). Someone with real experience in the theme gives a real rule; otherwise the rule is improvised.

## Not done

- **The four scripted scenarios were not re-scored** with the step-recall and flag-F1 metrics in `evaluate.py`. That needs a model run or cached answers; the metrics themselves are implemented and tested. Run `python -m playbook.evaluate` with a provider configured.
- **A model larger than the 4B** for H5 (an 8B does not fit comfortably in 15 GB), and any cloud model.
- **A browser test of the pilot page.** Its JavaScript is exercised under node with a stub DOM only.

## Known problems (not fixed)

- Local OCR can read `9,871` as `9.871`. The pool now repairs it when the label's other readings show thousands (comma-grouped, or 1,000 or more); if every reading of a label is misread there is no evidence and it stays wrong.
- OCR can drop the space in a label (`Batchsize`). Names that differ only by underscores are merged (`decisions.unify_names`); other variants, two spellings on one screen, and category labels are not.
- The decision log needs readouts as `Label: value` text; charts and unlabelled numbers are not read.
- A long recording of many checks needs `--dwell` and `--navigation`; nothing infers which controls only move to the next item (experiment E7).
- `decisions.add_ratios` is switched on per call site (`--ratios`), not stored with the log.
