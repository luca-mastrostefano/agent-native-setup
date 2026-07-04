# Community profile index

`index.json` is the curated, discoverable list of community profiles. It holds **URLs**, not the
profiles themselves — each profile lives in its own git repo and keeps its own versions and update
stream. Consumers find entries with:

```bash
agent-native-setup profile search auth        # match name / description / tags
agent-native-setup profile list --community    # the whole index
```

## Add your profile

1. Publish your profile to a public git repo and **tag a version** (for reproducible installs).
2. Get the entry ready: `agent-native-setup profile publish ./my-profile` validates it and prints a
   ready-to-paste entry (with the correct `git+https://…@<tag>` URL).
3. Open a PR adding that entry to the `profiles` array below. CI and a maintainer review it.

Entry shape:

```json
{
  "name": "my-team",
  "url": "git+https://github.com/me/my-team-profile.git@v1.0.0",
  "description": "one line — what it sets up and for whom",
  "author": "your name / handle",
  "tags": ["python", "backend"]
}
```

## What listing means (and doesn't)

A listing is **discovery, not endorsement**. It is not a safety guarantee: `profile add` derives a
profile's safe/unsafe tier from its *content* at fetch time and asks for consent before running any
code-carrying (`unsafe`) profile — that classifier, not this list, is the trust boundary. Keep
entries honest and useful; being merged means "plausibly useful," not "vetted safe."

A team can run a **private index** by pointing `AGENT_NATIVE_SETUP_INDEX_URL` at their own JSON.
