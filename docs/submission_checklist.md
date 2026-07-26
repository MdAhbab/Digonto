# Submission checklist

Build With Gemma @ Bangladesh. **A submission missing any of the five required
components is not judged at all**, regardless of quality. Check this list before
pressing Submit, not on the last day.

## The three disqualification rules, and how Digonto answers each

| Rule | Our answer |
| --- | --- |
| Does not use Gemma as a core component | Gemma 4 E2B is the only generation model. It answers, classifies portal changes, scores eligibility and interview answers, extracts document fields with native vision, and drives all four agents with native tool calling. |
| An unmodified chatbot wrapper with no automation or insight layer | The conversational surface is one page of seven. The system crawls and diffs portals on a schedule, versions a knowledge store, re-plans student timelines from events, and improves the model from real corrections. |
| Missing any of the five components | Tracked in the table below. |

## The five required components

| # | Component | Where it lives | Status |
| --- | --- | --- | --- |
| 1 | Kaggle writeup | `paper/kaggle_writeup.md` | Written. 1,780 words against a 2,000 cap; 11 graphics listed against a 10 minimum. |
| 2 | Media gallery | Graphics list at the end of the writeup | Planned, 11 items. Needs the app built and captured. |
| 3 | Public notebook | `docs/notebook_plan.md`, then `notebooks/digonto_gemma.ipynb` | Planned in full. Needs writing and a clean run. |
| 4 | Video, 3 to 5 minutes | `docs/video_script.md` | Scripted shot by shot at 4:30. Needs recording. |
| 5 | Public project link | https://digonto.ahbab.dev and https://github.com/MdAhbab/Digonto | Domain and repository decided. Needs deploying. |

Two required elements are pass or fail and are easy to lose by accident:

- **Writeup under 2,000 words.** Currently 1,780. Re-count after every edit; do
  not count the graphics list into the prose if you trim, but do check both
  numbers.
- **Video under 5 minutes.** Script targets 4:30. Confirm on the exported file.

## Application rubric, 60 points

| Criterion | Points | What earns it here |
| --- | --- | --- |
| Usefulness | 15 | The app must run without errors during judging. A working narrow build beats a broad broken one. If time runs short, cut agents, not correctness. |
| Informativeness | 15 | `README.md`, `agents.md`, `backend/backend.md`, `docs/business_model.md`, and the paper. Documentation is already the project's strongest asset. |
| Engagement | 10 | The Truth Ledger citation sheet and the Timeline Reactor re-planning are the two moments a judge remembers. Make sure both are reachable in under 30 seconds from the landing page. |
| Documentation quality | 15 | Every number is sourced. Every unmeasured value is labelled a target. |
| Novelty | 5 | RC-RAG, the Truth Ledger, and the Agent Fee Reality Check. |

## Video rubric, 40 points

Covered in `docs/video_script.md`, including the rubric line that explicitly asks
for prompt engineering. That segment is 60 seconds and is the highest-value
minute in the submission.

## Priority order if time runs short

The rubric weighting makes the ordering clear, and it is not the intuitive one.

1. **Record the video.** It is 40 points on its own and it is the only component
   with no partial credit for effort. A rough video scores; a missing one does
   not.
2. **Get the five components submitted.** Incomplete means unjudged.
3. **Make the demo path work end to end.** One flawless flow (ask a question, open
   the citation, see a portal change re-plan the timeline) is worth more than six
   half-working features.
4. **Then breadth.** Additional agents, additional countries, additional polish.

The deep work already done on architecture and documentation only converts into
points if components 2 through 5 exist. Do not spend the last hours improving the
writeup.

## Honesty rules that apply to every component

Carried from `writing_instructions.md`, and they apply to the writeup, the README,
the video, and the notebook equally.

- No value is described as measured until it has been measured. Targets are
  labelled targets.
- Every number that appears in more than one document must be identical in all of
  them. The verified figures are in `README.md`; treat that as the source.
- If a feature is demonstrated with fixtures rather than live data, say so on
  screen and in the caption.
- The internal fallback path is not mentioned in any public artifact.

## Final pass before submitting

- [ ] Five components all present and public.
- [ ] Writeup word count re-counted after the last edit.
- [ ] Video runtime confirmed on the export.
- [ ] Live URL and repository URL open in a private browser window.
- [ ] Notebook runs clean on a fresh session.
- [ ] Every measured number matches across writeup, README, paper, and notebook.
- [ ] No mention of the internal fallback anywhere public.
- [ ] Writeup saved **and then submitted**. A saved draft is not a submission.
