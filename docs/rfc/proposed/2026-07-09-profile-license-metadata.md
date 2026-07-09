# Declare a profile's license, carry it into the index

- **Status:** Proposed
- **Date:** 2026-07-09
- **Author:** Luca Mastrostefano
- [ ] Implemented

## Context

A profile is not a dependency you link against — it is a **pile of files copied into the
adopter's repo**. `content_hash` covers "exactly `profile.json` + every file under
`templates/`" (`profiles.py:1710`), and that is precisely the surface that lands in someone
else's working tree and gets committed there. Whatever terms govern those bytes travel with
them.

Today nothing in the system says what those terms are. `profile.json` has no `license` key
(`_PROFILE_KEYS`, `profiles.py:93`), the index entry has none, `profile show` prints none, and
the website renders none. An adopter running

```
uvx --from git+https://github.com/luca-mastrostefano/agent-native-setup agent-native-setup \
  -o ./my-app --profile tolaria-setup
```

gets ~dozens of files written into their repo having been told the profile's `description`,
`author`, and `tags` — and nothing about whether they may ship the result. To find out they
must leave the tool, find the source repo, and read a file. That is the wrong default for a
tool whose entire premise is that a setup should install and update *like a package*, and
every package manager that copies code surfaces its license.

Worse, the `LICENSE` file a profile author writes **does not reach the adopter at all**. The
applied surface is `templates/` (`template_files()`, `profiles.py:198`); the `LICENSE` sits at
the profile repo's *root*, beside `profile.json`, and is never copied. Neither `tolaria-setup`
nor `agent-native-baseline` ships a `templates/LICENSE` today. (`LICENSE` does appear in
`_INERT_NAMES`, `profiles.py:1659` — but that list governs which *output paths* can still earn
a `safe` verdict from the classifier, not what a profile ships.) So the terms currently reach
the adopter through no channel whatsoever.

**The obvious workarounds don't work.** Three ways to avoid a declared field, all wrong:

*Read the profile repo's `LICENSE` and interpret it.* Interpreting it means text
classification. GitHub's own classifier — the best-tuned one available — returns
`NOASSERTION` / `"Other"` for **two of our three listed profiles**, because both append a
provenance note under the MIT text. Both are plainly MIT. A classifier that gets two-thirds of
the current index wrong is not a source of truth.

> Reproduce (checked 2026-07-09):
> `gh api repos/luca-mastrostefano/tolaria-setup/license --jq '.license.spdx_id'` → `NOASSERTION`;
> same for `andrej-karpathy-skills-setup`; `agent-native-baseline` → `MIT`.

*Ask the profile repo's host.* Same answer, same `NOASSERTION`, plus it only works for GitHub
and only over the network.

*Infer it from where the profile came from.* This one is actively dangerous, and the current
index proves it. `tolaria-setup` was extracted from `refactoringhq/tolaria`, which **is
AGPL-3.0**. The profile repo is **MIT** — its `LICENSE` closes with:

> The files under `templates/` are derived from the Tolaria project
> (https://github.com/refactoringhq/tolaria, AGPL-3.0), extracted and relicensed under this
> MIT license by their copyright holder.

Only the copyright holder could make that statement, and no amount of inspection recovers it.
Infer from the upstream and you tell an adopter they have taken on AGPL obligations they have
not. Infer from nothing and you tell them nothing. The fact is **declarable only by the
author**, which is exactly why it needs a declared field.

(For the record, all three currently-listed profiles are MIT. The problem this RFC solves is
not that one of them is copyleft — it is that an adopter has no way to know either way, and
the ecosystem is meant to grow beyond three entries authored by one person.)

**Doesn't this reintroduce "declared, not derived"?** RFC 2026-07-04-community-index §3
deliberately refused an author-declared `safety` field, because that would re-open the
anti-pattern RFC 2026-07-03-profile-safety §3 rejected: a hostile author writes
`"safety": "safe"` and walks past the gate. RFC 2026-07-08 then drew the line precisely —
`content_hash` is fine to declare because it is **objectively verifiable**, and it lives in
*our* index, a different trust domain from the author's repo.

`license` sits on neither side of that line, and pretending otherwise would be dishonest. It
is **not verifiable** (no re-fetch proves an author holds the copyright they claim) and it is
**not a control**. The distinction that makes it safe is different:

- `safety` was a *security control*, and its declarer was the adversary it constrained. A
  declared value there is worth nothing — it is the attacker's own testimony about whether to
  stop them.
- `license` is a *legal claim by the copyright holder about their own work*. The author is the
  **only party with standing** to make it. A false declaration is a legal wrong committed
  against an adopter, not a bypass of one of our gates — because there is no gate. Nothing in
  the engine reads `license` to grant a privilege, skip a prompt, or admit bytes. It is
  display metadata, and the safe/unsafe classifier and consent gate remain the only trust
  boundary, untouched.

The asymmetry is the whole point: we refuse to let an author *self-certify past a gate*, and
we require an author to *state a fact only they possess*.

## Decision

**1. `license` is an optional `profile.json` key holding an SPDX identifier.** A short string
— `"MIT"`, `"Apache-2.0"`, `"AGPL-3.0-only"`, `"CC-BY-4.0"`. Added to `_PROFILE_KEYS` and the
`Profile` dataclass beside `tags`, which is the exact precedent: freeform-ish author metadata,
advisory to the engine, carried outward by `publish`.

Optional in the schema, permanently. `load()` must never reject a profile for omitting it —
that would break every profile written against today's engine, the forward-compat rule
`_PROFILE_KEYS` exists to protect (`profiles.py:88`).

**2. `publish` carries it into the index entry; the entry never states it independently.**
One line beside the existing `"tags": list(prof.tags),  # carried from the profile's own tags`
(`profiles.py:2043`), and one line in `_render_index_entry`. The profile is authoritative; the
index is a **cache of a declaration**, exactly as `content_hash` is a cache of a computation.
A curator hand-typing `"license": "MIT"` into `index.json` is inventing a legal claim on an
author's behalf, and is forbidden by construction: nothing in the flow offers a way to.

**3. `check_index` verifies declared == fetched, and requires presence.** The identical
treatment `name` and `content_hash` already receive (`tools/checks/check_index.py:85-105`).
An entry whose listed `license` disagrees with the fetched `profile.json` fails CI, so a
listing cannot drift into advertising MIT for a profile that has since gone copyleft. An entry
with no `license` fails CI with the correcting value printed, as `content_hash` does:

> `missing license — add "license": "AGPL-3.0-only" to profile.json (SPDX identifier;
> `profile publish` carries it into the entry)`

This is the one place it is required. Optional in the schema, required in the **curated
index** — a third-party profile fetched by URL stays loadable without one, while the list this
repo puts its name on is complete by construction. That split is the same one the index
already draws: the schema tolerates an unpinned `@ref`, `check_index` refuses one.

**4. `validate` lints, advisory.** No `license` → "no license declared; adopters copy your
`templates/` into their repo and can't tell what terms apply." Declared but no `LICENSE` file
shipped → "declares `AGPL-3.0-only` but ships no `LICENSE`." Both advisory: they nudge the
author who will publish, without breaking the author who is iterating locally.

**5. Surfaced where the decision is made, not only where it is browsable.** The website badge
is the cheapest and the least important. In order of value:

- **Scaffold time** — the line that already prints the resolved profile also prints its
  license. This is the only surface an adopter cannot miss, and the only one shown *before*
  the files land.
- **`profile show`** — beside `description` / `author` / `tags`.
- **`search` / `list --community`** — so it is filterable before a fetch.
- **The website** — `site/index.html` already `fetch`es `contributions/index.json` live at
  runtime (`site/index.html:630`), so a field added to the index renders with **no build
  step**: a badge on the card, and the hardcoded snapshot above it updated to match.

**6. Validation is a shape check, not an SPDX registry.** Assert a non-empty single-line
string of `[A-Za-z0-9.+-]` and reasonable length; reject `"MIT License"` and free prose. We do
**not** vendor the ~600-entry SPDX list, and we do **not** add a dependency (`license-expr`,
`spdx-tools`) to validate one advisory display string — that fails Simplicity First, and it
would reject the day SPDX adds an identifier faster than we bump a pin. A typo'd
`"Apach-2.0"` renders as typed and a human reviewing the listing PR catches it. The cost of a
wrong-but-well-formed string is a misspelled badge; the cost of a vendored list is a
dependency and a recurring sync.

**Not in scope.** No `license` in the generated project's own manifest, no license-compat
checking between profile and adopter, no `--allow-license` gate on `add`, no attempt to make
this legal advice. Those are speculative and none were asked for.

## Consequences

**What becomes easier**

- An adopter sees the terms of the files being copied into their repo, at the moment they are
  copied, without leaving the tool.
- The index becomes filterable by license, which is a real procurement question ("show me
  permissive profiles") the moment a second author lists anything.
- The `tolaria-setup` relicensing — MIT packaging of AGPL-3.0-derived templates — becomes
  *expressible* rather than a paragraph buried in a `LICENSE` file nobody fetches.

**What this costs, concretely**

- **Every listed profile must be re-tagged and re-listed.** `content_hash` hashes
  `profile.json` itself (`profiles.py:1714`). Adding `license` to `profile.json` changes the
  hash, which invalidates the pinned entry, which requires a new tag and an index bump — for
  all three current entries, plus the `baseline-pin.json` pin for the flagship. This is the
  real cost of the design and it is not avoidable while keeping the profile authoritative. It
  is a one-time cost, and the fixed `profile publish` flow (which now emits and re-pins
  `content_hash` correctly) is exactly the tool for it.
- **Therefore §3's "required" must land second.** Flipping `check_index` to require `license`
  before the entries carry one turns the weekly index-check red and blocks unrelated PRs.
  Sequence: (a) schema + `publish` + `show` + `validate` lint; (b) backfill the three profiles,
  re-tag, bump the index; (c) flip `check_index` to required; (d) website badge. Steps (a) and
  (c) are separate PRs and the RFC is not Implemented until (c).
- **A single SPDX id cannot express a mixed-license profile.** `tolaria-setup` is the live
  example: MIT packaging, templates derived from AGPL-3.0 upstream and relicensed. `"MIT"` is
  the correct answer *here* only because the copyright holder relicensed. A profile that
  vendors third-party templates it does not own has no honest single identifier. We accept
  this: the field says what governs the profile as distributed, the shipped `LICENSE` file
  carries the nuance, and we do not invent a `license_expression` / `license_note` schema for
  a case that does not yet exist in the index. Revisit when it does.
- **An author can lie, and we will have amplified the lie.** RFC 2026-07-04-community-index
  §3's "discovery ≠ endorsement" tension gets sharper, not softer: a *license badge on our
  website* reads as vetting far more than a `description` does. We cannot verify it and must
  not imply we did. The badge and `show` output must attribute it — "license (as declared by
  the author): MIT" — and `CONTRIBUTING.md` / `contributions/README.md` must state that
  listing does not constitute a legal review. This is the honest cost of a field that is
  useful *because* it is unverifiable.

**What we give up**

- Nothing that works today. The field is additive; a profile without one loads, validates
  (with a lint), scaffolds, and updates exactly as now.
- **Half of this is reversible and half is sticky.** The `profile.json` key and the dataclass
  field are cheap to drop — they are additive and forward-compat by construction. But once
  `publish` emits `license`, `_render_index_entry` renders it, and `check_index` *requires* it,
  the index entry shape becomes an add-only compatibility contract, the same discipline
  `ASSET_NAME` (`profiles.py:68`) and `AGENT_POINTERS` (`profiles.py:80`) already carry:
  removing the field later breaks every listing and every client that reads one. Step (c) of
  the sequence below is the point of no easy return; steps (a)–(b) are not.

## Alternatives considered

**Do nothing; adopters read the source repo.** Rejected on the premise of the project: a
profile installs like a package, and the terms of the code being copied are a fact the tool
knows how to carry and currently drops. The friction is small per-adopter and paid by everyone,
forever.

**Put `license` only in `index.json`, hand-written by the curator.** Simpler by one field and
skips the re-tagging cost entirely — genuinely tempting, and the reason this RFC exists rather
than a one-line PR. Rejected because it makes a *curator* author a *copyright holder's* legal
claim, with no mechanism to keep the two in sync: a profile relicenses, the index keeps
advertising the old terms, and nothing can detect it. `tags` and `description` may drift
harmlessly. A license that drifts is a false statement about someone's legal obligations. The
authority for the claim and the storage of the claim must not be separated.

**Point at the profile's shipped `LICENSE` verbatim, without interpreting it.** The cheapest
option that touches the primary problem, and the strongest competitor to this RFC. The engine
already has the whole profile in cache at scaffold time, so it could print "this profile is
governed by `LICENSE` in its repo — read it" (or copy that file into the adopter's tree) with
**no schema field, no classifier, no re-tagging, no two-PR sequence**. That solves decision
point 5's headline claim — terms surfaced before the files land — at roughly zero cost, and it
is genuinely tempting.

Rejected because it solves only that one surface, and not the one this work exists for. An
opaque blob of legal text is not filterable (`search --license MIT` is impossible), not
renderable as a badge (the website has nothing structured to display — and a badge is what was
asked for), and not comparable across profiles: an adopter scanning the index still cannot see
that one entry is copyleft and three are not without opening three files. It also degrades
badly where it matters most — a profile that ships *no* `LICENSE` (the majority case today,
since the file lives at the repo root, outside `templates/`) yields nothing to point at, and
silence is exactly the status quo. A declared identifier is the only form that is
simultaneously surfaceable, filterable, and comparable.

The two are complements, not rivals, and the cheap one should land first: pointing at the
`LICENSE` at scaffold time is a small, independent improvement that needs no RFC, and it
remains correct after this RFC ships.

**Derive it from the profile's `LICENSE` file.** Rejected on evidence, above: GitHub's
classifier says `NOASSERTION` for two of our three entries, both of which are unambiguously
MIT to a human. Text classification of license files is a real, hard problem with a real, hard
failure mode (silently wrong), and we would be shipping a worse classifier than the one that
already fails.

**Derive it from the upstream repo the profile was extracted from.** Rejected as actively
harmful: it would label `tolaria-setup` AGPL-3.0, which is false, and would tell adopters they
have obligations they do not have. Relicensing by the copyright holder is invisible to
inspection.

**Full SPDX expression support with a validating dependency.** Rejected under Simplicity
First: a new dependency, a list to keep synced, and an engine that rejects identifiers newer
than its pin — all to validate a string the engine only ever displays. A shape check plus human
PR review is proportionate.

**Require `license` in the schema (hard-fail `load()`).** Rejected: it breaks every existing
profile on upgrade and violates the forward-compat contract `_PROFILE_KEYS` was designed
around. Optional-in-schema / required-in-index gets the completeness where it matters and
costs nothing elsewhere.
