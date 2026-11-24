"""Make a prompt safe before it goes anywhere: the router, the decision log or a model.

Four kinds of findings, each with its own action in the config's `guard` block:
  secrets    keys, tokens, passwords and private keys, recognised by their shape
  hidden     invisible characters that can hide instructions in pasted text
  injection  text that poses as something other than the user's own words: chat control tokens, role
             tags and labels, claims of authority, orders to drop earlier instructions, encoded blocks
  personal   payment card numbers and IBANs, checked by their checksum

Pure functions: no model, no I/O. The patterns are heuristics: they miss secrets without a known
shape, and a finding is never printed or logged, only its kind.
"""

from __future__ import annotations

import re

ACTIONS = ["off", "warn", "redact", "block"]
DEFAULTS = {"secrets": "redact", "hidden": "redact", "injection": "warn", "personal": "warn"}

# (kind, pattern). With a group, only the group is the secret; without, the whole match.
SECRETS = [
    ("private-key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)", re.S)),
    ("aws-access-key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("github-token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{22,})")),
    ("anthropic-key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}")),
    ("openai-key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}")),
    ("slack-token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    ("google-api-key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}")),
    ("stripe-key", re.compile(r"\b[sr]k_live_[0-9A-Za-z]{16,}")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")),
    ("bearer-token", re.compile(r"(?i)\bbearer\s+([A-Za-z0-9._~+/=-]{20,})")),
    ("url-password", re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s:/@]+:([^\s@/]{3,})@")),
    ("password", re.compile(
        # No \b in front: DB_PASSWORD and PASSWORD_PROD are names too.
        r"(?i)(?<![A-Za-z])(?:password|passwd|pwd|secret|api[_-]?key|access[_-]?key|auth[_-]?token|token)"
        r"[A-Za-z0-9_]*[\"']?\s*[:=]\s*[\"']?([^\s\"',;]{6,})")),
]
# A value made of letters, dots and underscores is a variable or a placeholder, one with brackets or a
# dollar sign is code, and a plain number is a setting: `password = settings.db_password`,
# `token = os.environ["TOKEN"]`, `max_tokens=100000`.
_CODE_NOT_SECRET = re.compile(r"^[A-Za-z_.]+$|^\d+$|[()\[\]{}<>$]")

# Text that can make a model take pasted content for the system, the assistant or a tool speaking.
# Heuristics for known shapes; the wording of an attack is free, so this cannot be complete.
INJECTION = [
    ("chat-control-token", re.compile(r"<\|[A-Za-z_]{2,30}\|>|\[/?INST\]|<</?SYS>>")),
    ("role-tag", re.compile(
        r"(?i)</?(?:system|assistant|human|developer|system[-_]reminder|system[-_]prompt|tool[-_]result|"
        r"tool[-_]use|function[-_]calls|function[-_]results)(?:\s[^<>]*)?>")),
    ("role-label", re.compile(
        r"(?im)^[ \t>*#-]*(?:\[?system\s+(?:prompt|message|instructions?|note)\]?|\[system\]|assistant)\s*:")),
    ("override-instruction", re.compile(
        r"(?i)\b(?:ignore|disregard|forget|override)\s+(?:(?:all|any|of|the|your|my)\s+){0,3}"
        r"(?:previous|prior|above|earlier|preceding|system)\s+(?:instructions?|prompts?|rules?|messages?|context)"
        r"|\bnew\s+(?:system\s+)?instructions?\s*:"
        r"|\bdo\s+not\s+(?:tell|inform|alert|notify)\s+the\s+user"
        r"|\byou\s+are\s+now\s+(?:in\s+)?(?:developer|jailbreak|unrestricted|dan)\b")),
    ("authority-claim", re.compile(
        r"(?i)\b(?:message|note|notice|instructions?|directive)\s+from\s+(?:anthropic|openai|the\s+system|"
        r"the\s+(?:system\s+)?administrator|your\s+(?:developers?|creators?|operator))\b")),
    # A long unbroken run of base64: text a person cannot read but a model can decode.
    ("encoded-block", re.compile(r"(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{200,}={0,2}")),
]

# Zero-width and direction-override characters, and the "tag" block that mirrors ASCII invisibly.
# Not U+200C/U+200D: those join letters and emoji in ordinary text.
HIDDEN = re.compile("[\u200b\u200e\u200f\u202a-\u202e\u2060-\u2064\u2066-\u2069\ufeff\U000e0000-\U000e007f]+")

CARD = re.compile(r"(?<![\w-])\d(?:[ -]?\d){12,18}(?![\w-])")
IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,3})?\b")


class Blocked(ValueError):
    """The config says a prompt with this kind of finding must not go anywhere."""


def _luhn(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch) * (2 if i % 2 else 1)
        total += n - 9 if n > 9 else n
    return total % 10 == 0


def _iban(text: str) -> bool:
    s = text.replace(" ", "")
    if not 15 <= len(s) <= 34:
        return False
    return int("".join(str(int(c, 36)) for c in s[4:] + s[:4])) % 97 == 1


def scan(prompt: str) -> list[tuple[str, str, int, int]]:
    """(category, kind, start, end) per finding, in order and without overlaps."""
    found = []
    for kind, pattern in SECRETS:
        for m in pattern.finditer(prompt):
            group = 1 if pattern.groups else 0
            if kind == "password" and _CODE_NOT_SECRET.search(m.group(1)):
                continue
            found.append(("secrets", kind, m.start(group), m.end(group)))
    for kind, pattern in INJECTION:
        for m in pattern.finditer(prompt):
            found.append(("injection", kind, m.start(), m.end()))
    for m in HIDDEN.finditer(prompt):
        found.append(("hidden", "hidden-characters", m.start(), m.end()))
    for m in CARD.finditer(prompt):
        if _luhn(re.sub(r"\D", "", m.group())):
            found.append(("personal", "card-number", m.start(), m.end()))
    for m in IBAN.finditer(prompt):
        if _iban(m.group()):
            found.append(("personal", "iban", m.start(), m.end()))
    found.sort(key=lambda f: (f[2], -f[3]))
    kept, end = [], 0
    for f in found:  # the earliest and then the longest finding wins where two overlap
        if f[2] >= end:
            kept.append(f)
            end = f[3]
    return kept


def actions(cfg: dict) -> dict:
    return {**DEFAULTS, **(cfg.get("guard") or {})}


def apply(cfg: dict, prompt: str) -> tuple[str, list[dict]]:
    """The prompt that may go on, and what was found: [{"category", "kind", "action", "count"}].

    Raises Blocked when a finding's category is set to block."""
    todo = actions(cfg)
    findings = [f for f in scan(prompt) if todo[f[0]] != "off"]
    summary: dict[tuple, dict] = {}
    for category, kind, _, _ in findings:
        entry = summary.setdefault((category, kind), {"category": category, "kind": kind,
                                                       "action": todo[category], "count": 0})
        entry["count"] += 1
    report = list(summary.values())
    blocked = [r for r in report if r["action"] == "block"]
    if blocked:
        raise Blocked("the prompt holds " + describe(blocked, verb=False)
                      + "; remove it, or change the `guard` setting in your targets.yaml")
    for category, kind, start, end in reversed(findings):
        if todo[category] == "redact":
            prompt = prompt[:start] + ("" if category == "hidden" else f"[REDACTED:{kind}]") + prompt[end:]
    return prompt, report


def describe(report: list[dict], verb: bool = True) -> str:
    """"redacted 1 github-token, warning: 1 card-number": never the finding itself."""
    words = {"redact": "redacted", "warn": "found", "block": "found"}
    return ", ".join((f"{words[r['action']]} " if verb else "") + f"{r['count']} {r['kind']}" for r in report)
