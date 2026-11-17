# Configuration

`ask targets` prints the config file in use. To customise it:

```sh
mkdir -p ~/.config/trivium
cp src/trivium/targets.yaml ~/.config/trivium/targets.yaml   # or point TRIVIUM_CONFIG at any file
```

The file has four parts: `router` (model, pinned revision, quantisation, port), `questions` (wording
and option descriptions), `targets` (vendor, tier, model id, optional effort) and `rules`
(first match wins, plus `default` and `fallback`).

`router.cache: true` keeps the router's scores on disk, in `route-cache` next to the decision log, and
reuses them when the same prompt is typed in the same repository with the same questions and router
settings. It ships off. It only helps for exact repeats, which matters most on the slow `llamacpp`
runtime. Rules, calibration and option weights are applied after the cache, so changing those needs no
clearing; `ask eval` and `ask calibrate` never use it.

Wording is the biggest lever. Questions ask what the text *says*, not what to do, and every option
has a description. Changing the difficulty question from "How demanding is the work?" to "How much
work would a skilled engineer need?" with time-based options moved difficulty accuracy from 67% to
81% on the bundled eval set.
