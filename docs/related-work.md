# Related work

The full BibTeX is in [`references.bib`](references.bib). Each entry's `note` says how far it was checked. For the 2024–2026 papers, **the arXiv abstract pages were read, not the full texts**, so the summaries below say only what the abstracts support. Entries marked *TODO verify* still need author lists, venues or pages checked against the publisher. Two papers (cotomi Act, Tacit Fragments) could not be fetched and are **not** relied on.

## Framing: tacit knowledge

- **Polanyi (1966), *The Tacit Dimension*** and **Nonaka and Takeuchi (1995), *The Knowledge-Creating Company*** give the framing: expertise people cannot fully state, and its conversion into explicit knowledge. The observability classes in [tacit-knowledge.md](tacit-knowledge.md#observability-classes) are a heuristic sorting along that line, not a measurement.
- **Zuin et al. (2025)** and **Brennig (2025)** use LLM-driven interviews to draw out tacit knowledge and add it to organisational records. The `elicit` and `pilot elicit` interviews do the same at the scale of one person's decisions, and ask only about the cases a fitted rule cannot explain. With `--llm` a local model writes the questions, reads free-text answers into conditions and decides when to stop (`playbook/interview.py`), adapted from the two papers' abstracts: Brennig's targeted queries whose answers are incorporated into the record, and Zuin et al.'s iterative questioning with self-critique. Differences: the gap here is a specific choice a fitted rule cannot explain, the interviewer is a 4B local model, and an answer counts only if it becomes a feature that improves prediction. Their interview mechanics beyond the abstracts are unknown, so this is an adaptation, not a replication.
- **Ng and Russell (2000), inverse reinforcement learning** frame recovering the rule behind observed behaviour. The decision tree is a deliberately simple, readable stand-in: the person has to be able to dispute it.

## Recordings to written procedures

- **Wornow et al. (2024), WONDERBREAD** is a benchmark of business-process documentation, knowledge-transfer and improvement tasks. They report that models document workflows with good step recall but judge poorly whether a workflow was completed correctly. The scoring in `evaluate.py` (step recall, and flag precision/recall/F1 for judgment) borrows that split between listing and judging.
- **Xu et al. (2024)** apply in-context ensembling of pseudo labels to low-level workflow understanding in video-language models.

## Recordings to reusable agent skills

- **Huang et al. (2026), Work2Skill** induce skills from synchronised screen, input and accessibility-tree demonstrations, capturing workflow rules, step dependencies and completion checks. The recorder collects the same three signals; the skill export carries placeholders, dependencies, completion checks and human gates.
- **Jiang et al. (2026)** induce task models, a hierarchical objective model plus a procedure model, from computer-use traces, separating interleaved tasks. Not implemented here ([ROADMAP.md](ROADMAP.md)).
- **Zhang et al. (2026), ShowUI-Aloha** and **Oyamada et al. (2026), cotomi Act** also learn from human recordings; the second was not read.

## Agent memory and screen activity

- **Wang et al. (2025), Agent Workflow Memory** induce reusable workflows from experience and supply them to later tasks. Cross-session memory is on the roadmap but not built; pooling decisions already supplies the cross-session context the experiments needed.
- **Iyamu (2026), Activity Frames** compile captured screen activity into typed, evidence-linked episodes without a model. The frames, the decision log and the consistency check follow the same idea: deterministic, with pointers back to the evidence.
- **Shahid et al. (2026), Tacit Fragments** treat tacit knowledge as a governed memory layer for agents; not read.

## Long-horizon and web-scale data

**Lu et al. (2025), VideoAgentTrek**, **Song et al. (2025), Watch and Learn** and **Baker et al. (2022), VPT** learn to act from unlabelled video; **Hayati et al. (2026), Kolab** and **Meng et al. (2026), ClawMark** provide long-horizon, naturalistic benchmarks. These train models and are outside this project's scope; they inform the evaluation design and what real-expert data would eventually need.

## Tools this builds on

[Screenpipe](https://screenpipe.com/) (continuous screen capture) and [GodHands](https://godhands.ai/) (recordings to SOPs) inspired the capture and playbook layers. The agent skill follows the [Agent Skills](https://agentskills.io) format. The vision model is [Qwen3-VL](https://ollama.com/library/qwen3-vl), served by [Ollama](https://ollama.com) or llama.cpp; OCR is RapidOCR on ONNX Runtime.

## What this repository adds

The techniques above are starting points, adapted rather than replicated. The contribution is the combination for *decisions*: logging what was on screen at each pause including non-actions, pooling across sessions, fitting a readable rule, interviewing the person about the misfits, and handing the result to an agent with an explicit "ask a human first" boundary, together with a pre-registered evaluation of how far each step works. What it does not yet do: any test with a real expert, persistent cross-session memory, task models.
