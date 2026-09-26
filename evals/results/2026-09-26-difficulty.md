# Difficulty round, 2026-09-26

Most routing mistakes start in the difficulty question, so this round tried to improve it and tested
the result on prompts written for that purpose.

## Data

`evals/difficulty-120.jsonl`: 119 prompts written around the boundaries (trivial/moderate and
moderate/hard): 40 trivial, 41 moderate, 38 hard, across all kinds, with repository context and three
Dutch prompts. Two labellers answered all three questions blind (the author, and an agent that saw
only the prompts and the question wording): agreement kind 96% (kappa 0.94), difficulty 98% (0.97),
tools 100% (1.00). The 7 disagreements are settled in the file with the reason for each.

## Protocol

Wordings and weights were designed on the 136 development prompts (`calibration-100.jsonl` and
`prompts.jsonl`). The comparison on the new 119 was written down before any wording was scored on
them:

- A: the current difficulty wording, unchanged.
- B: the current wording with option weights moderate x3, hard x2 (chosen on the dev prompts).
- Adopt B only if a paired McNemar exact test on right target favours it with p < 0.05, and it does
  not send more prompts to a model that is too weak. Everything else is descriptive only.

## What the dev prompts showed

The router's difficulty errors are one-sided: of 44 moderate prompts, 17 were called trivial (short
requests such as "add a --verbose flag", "write a Dockerfile", "review my staged changes"), while 61 of
62 trivial prompts were right. Five rewordings (concrete examples per option, a count of steps,
tighter time anchors, and "judge the work, not the length of the request") all did worse than the
current wording on the dev prompts (57.4% to 74.3% against 78.7%). Adding examples made the router
call moderate work trivial even more often. Weighting the options instead corrected the bias: on the
dev prompts, moderate x3 and hard x2 moved right target from 77.2% to 82.4%, and every neighbouring
setting scored 80% to 82%.

## Result on the 119 held-out prompts

| | A: current | B: weights moderate x3, hard x2 |
|---|---|---|
| Difficulty correct | 79.0% | 85.7% |
| trivial / moderate / hard | 100% / 44% / 95% | 90% / 80% / 87% |
| Right target | 73.9% | 78.2% |
| Sent to a model too weak | 13 | 7 |
| Sent to a model too strong | 14 | 15 |

Paired, B fixes 10 targets and breaks 5 (McNemar exact p = 0.30); on difficulty it fixes 15 and breaks
7 (p = 0.13). The improvement held on unseen prompts and nearly halved the too-weak mistakes, but it
does not meet the significance bar set in advance, so the weights ship as an option
(`option_weights`), off by default.

Descriptive only (not eligible for adoption), on the 119: gentler weights x2 / x1.5 gave 84.0%
difficulty and 79.0% right target; the reworded questions with or without weights gave 50.4% to 82.4%
difficulty and 51.3% to 72.3% right target. On the sets used to choose the weights, B also raises right
target (calibration-100 test 71.4% to 78.6%; the old 36, 80.6% to 88.9%), which is expected and does
not count as evidence.

## Next

The effect is consistent in direction on every set; what is missing is the number of prompts to
show it beyond chance. With these effect sizes, roughly 300 paired prompts would settle it. Real,
rated prompts from `ask export` are the right way to get there.
