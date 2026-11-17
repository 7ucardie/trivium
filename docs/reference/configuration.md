# Configuration

`ask targets` prints the config file in use. To customise it:

```sh
mkdir -p ~/.config/trivium
cp src/trivium/targets.yaml ~/.config/trivium/targets.yaml   # or point TRIVIUM_CONFIG at any file
```

The file has four parts: `router` (model, pinned revision, quantisation, port), `questions` (wording
and option descriptions), `targets` (vendor, tier, model id, optional effort) and `rules`
(first match wins, plus `default` and `fallback`).

Wording is the biggest lever. Questions ask what the text *says*, not what to do, and every option
has a description. Changing the difficulty question from "How demanding is the work?" to "How much
work would a skilled engineer need?" with time-based options moved difficulty accuracy from 67% to
81% on the bundled eval set.
