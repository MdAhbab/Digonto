# Demo video script (4 minutes 30 seconds)

The video is worth **40 of the 100 available points**, the same weight as
usefulness, documentation, and novelty combined. It is scored separately from the
application. Treat it as a deliverable, not as a recording of the app.

**Hard requirement:** under 5 minutes. Target 4:30 so that a slow upload or an
added title card cannot push it over.

## What the video rubric actually asks for

| Criterion | Points | What the script does about it |
| --- | --- | --- |
| Accuracy | 10 | Every number on screen is one of the verified figures from `README.md`. No claim about performance is stated as measured unless it has been measured. |
| Informativeness | 10 | The rubric explicitly names **prompt engineering**. Section 3 of this script is a dedicated 60 second segment on the four prompt patterns, with the actual prompts on screen. |
| Instructional value | 10 | The rubric asks that the video be "a valuable learning resource". Section 3 and Section 5 are written so a viewer can copy the technique into their own project without using Digonto at all. |
| Entertainment and production | 10 | One continuous narrative, no dead air, no screen-recorded typing, captions burned in, Bangla and English both visible. |

Two notes on the rubric wording. It refers to "Gemini API users", which is carried
over from a sibling competition. Do not change the model story to match it: the
competition disqualifies submissions that do not use Gemma as a core component.
Serve the intent instead, which is transferable teaching, and say plainly that
the techniques shown apply to any tool-calling model.

## Shot list

### 0:00 to 0:25 | The problem, told with one person

Open on a student at a desk with a stack of printed documents and a phone. No
narration for the first three seconds, just the sound of pages.

> **Narration (English, Bangla subtitles):** "In 2024, Schengen states refused
> 54.9 percent of visa applications from Bangladesh. Twenty thousand nine hundred
> and fifty-seven refusals. Every one of them cost a fee that is never returned."

On screen, the four verified numbers appear as plain typeset figures, one at a
time: 52,799 students abroad. 667.77 million dollars in FY25. Hundreds of
consultancies, no mandatory registration system. 54.9 percent refused.

> "The information that prevents most of those refusals is already public. It is
> just written in English no one explains, spread across portals that change
> without telling anyone."

**Do not** use stock footage of airports or graduation caps. Use the real
documents and the real portals.

### 0:25 to 0:50 | What Digonto is, in one sentence and one screen

Cut to the app, light theme, Ask Digonto page, a real question typed in Bangla.

> "Digonto reads those portals so a student does not have to, and answers in
> Bangla. It is free, and it will stay free."

Show the answer streaming. Then click a citation. The Truth Ledger side sheet
opens, showing the archived snapshot with the quoted sentence highlighted and its
timestamp.

> "Every claim links to a stored copy of the official page it came from. A student
> can show this to a bank officer."

### 0:50 to 1:35 | The part that is not a chatbot

This segment exists because the competition disqualifies chatbot wrappers. Make
the automation visible.

Split screen. Left: an embassy page. Right: the event log. Change a date on a
local copy of the embassy page and let the crawler pick it up.

> "Nothing here waits for a user to ask a question. The crawler re-fetches this
> embassy page every six hours. When one sentence changes, that change becomes an
> event."

Show the single event reaching four consumers, animated: knowledge store update,
cache invalidation, timeline re-planning, Bangla alert. Then cut to a phone
showing the alert arriving, quoting the changed sentence.

> "One edit on one page. The knowledge store updates, the stale cached answers are
> dropped, every affected student's plan is recalculated, and the students who
> depend on that page get told what moved, in Bangla, with the source attached."

### 1:35 to 2:35 | Prompt engineering (the highest-value minute)

Screen recording of the actual prompts, in a code editor, large type. Explain four
patterns and why each exists. This is the segment the rubric rewards most and the
one most submissions will skip.

1. **The refusal contract.** Show the output schema with `refusal_reason`.
   > "The model cannot return an answer without a supporting passage, because the
   > schema will not validate. Refusal is a field, not a behaviour we hope for. On
   > a visa question, a confident wrong answer is worse than no answer."
2. **The data-only frame.** Show retrieved portal text wrapped in a delimiter
   block with tool calling disabled.
   > "Crawled pages are untrusted input. If someone hides an instruction in a web
   > page, we do not want the model to follow it. So retrieved text goes inside a
   > frame that is marked as data, and tools are switched off while the model is
   > answering from sources."
3. **Enum-constrained classification.** Show Porter's triage prompt returning one
   of five values.
   > "Porter decides whether a change is a deadline, a fee, a document rule, a
   > policy, or only wording. Constraining the output to five values means a
   > cosmetic edit never wakes a student at midnight."
4. **Per-criterion scoring.** Show Khoji's scholarship prompt returning a reason
   string per criterion.
   > "We never ask for a score alone. Every criterion returns its own reason, so a
   > ranking can be explained to the student instead of asserted."

> "None of this is specific to our app. Any tool-calling model, any domain where
> being wrong is expensive: these four patterns transfer."

### 2:35 to 3:20 | The four agents, fifteen seconds each

Fast, concrete, one screen each. No feature-list narration.

- **Prohori** finds a passport expiring four months before the projected arrival
  date and explains the six-month rule, cited.
- **Khoji** produces a funding plan where the bank solvency line is drawn as a
  threshold the budget bar must cross.
- **Shonchari** asks an uncomfortable interview question, then flags where the
  spoken answer contradicts the student's own uploaded documents.
- **Porter** was already shown at 1:35. Reference it in one line rather than
  repeating it.

> "These are the four services a consultancy charges for. Here they are free, and
> every one of them shows its source."

### 3:20 to 3:50 | Why Gemma, and why this size

Terminal, running `ollama show gemma4:e2b`, output on screen.

> "Gemma 4 E2B: 2.3 billion effective parameters, a 128 thousand token context,
> and native support for tools, vision, and audio. Tool calling is why the agents
> are real function callers. Vision reads uploaded transcripts. Audio takes Bangla
> voice input. One model, one runtime."

> "It runs on one ordinary virtual machine, which decides two things. Passports
> and bank statements never leave our own server. And the cost of an answer is
> close to the electricity cost of a machine we already rent, which is how the
> service stays free."

### 3:50 to 4:20 | Recurrent Continual RAG, the research idea

One clean animated diagram of the three loops. Do not narrate the whole
architecture. Narrate the single insight.

> "Facts and skills change at different speeds, so we update them at different
> speeds. Visa rules change weekly, so they live in a knowledge store the crawler
> refreshes in hours. Explaining a solvency rule clearly in Bangla is a skill, so
> that lives in the model weights and improves every few weeks from real
> corrections."

> "Every retrain has to pass a fixed 200-question benchmark before it reaches a
> student. If any score drops, it rolls back. The knowledge learns daily. The
> model learns monthly. Nothing ships unchecked."

### 4:20 to 4:30 | Close

Back to the student from the opening, now with the plan on the phone.

> "Digonto. Free, in Bangla, and every answer shows its source."

End card: the live URL, the repository URL, and the licence. Hold four seconds.

## Production notes

- **Record at 1920x1080, 60 fps for UI, 30 fps for the talking segments.** Export
  at high bitrate; YouTube compression damages fine typography and this design has
  a lot of it.
- **Captions burned in, not auto-generated.** The judges are Bangladeshi
  engineers; some will watch without sound. Bangla on screen and English narration
  is the correct pairing, not the reverse.
- **No typing on camera.** Pre-fill every input and cut to the result. Recorded
  typing is the single most common reason demo videos run long.
- **Use a real, slow connection for at least one shot** so the streaming answer
  looks honest.
- **Do not show the fallback path.** It is internal.
- **Show one failure on purpose.** A refusal card, when the store has no source
  for a question. Judges score honesty, and a system that admits ignorance is more
  convincing than one that never does. This costs eight seconds and it is worth
  it.

## Pre-upload checklist

- [ ] Runtime under 5:00 confirmed on the exported file, not the timeline.
- [ ] Every on-screen number matches `README.md`.
- [ ] No unmeasured value is described as measured.
- [ ] Prompt engineering segment is present and at least 60 seconds.
- [ ] Gemma's role is shown, not only stated.
- [ ] Uploaded unlisted or public to YouTube, link works while signed out.
- [ ] Captions checked for Bangla rendering (conjuncts clip at tight leading).
