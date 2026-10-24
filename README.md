# Show Quote in Context

**This came from there.**

Ostensive definition: **"That thing THERE."** Point to the evidence, not just
the page that contains it.

An agent skill that links an exact quotation to its original webpage passage
using destination-verified Very Deep Links (VDLs), also called text-fragment
links. The source isn't just attached. The evidence is pointed to.

For journalism, scholarly web citations, news with sources, and everyday
"where does it say that?" questions. One small part of a verifiable trail:
claim -> quotation -> source passage -> surrounding context.

## Example

Given `https://tactiq.io/claude` and these exact words:

> and quote it back with the source attached

Return [the quotation in its original context](https://tactiq.io/claude#:~:text=and%20quote%20it%20back%20with%20the%20source%20attached).

The bundled helper freshly fetched and verified this passage on October 24,
2026. Pages can change. The browser handles scrolling and highlighting;
this skill does not launch a browser or claim to have tested highlighting.

## Install

The source folder must be named `show-quote-in-context`, with `SKILL.md` at
its root. Download and extract the repository, then place that folder in your
agent's personal skills directory:

The repository is [show-quote-in-context-ai-skill](https://github.com/metaartisan/show-quote-in-context-ai-skill).
Its repository name can differ from the installed skill folder name.

| Agent | Folder |
| --- | --- |
| Codex | `~/.agents/skills/show-quote-in-context/` |
| Claude Code | `~/.claude/skills/show-quote-in-context/` |

For a fresh Codex installation (the destination must not already exist):

```sh
mkdir -p ~/.agents/skills
git clone https://github.com/metaartisan/show-quote-in-context-ai-skill.git \
  ~/.agents/skills/show-quote-in-context
```

For a fresh Claude Code installation:

```sh
mkdir -p ~/.claude/skills
git clone https://github.com/metaartisan/show-quote-in-context-ai-skill.git \
  ~/.claude/skills/show-quote-in-context
```

Ask: "Show this quote in context," providing the URL and exact text.
You can also invoke `$show-quote-in-context` in Codex or
`/show-quote-in-context` in Claude Code.

See the official [Codex skills documentation](https://developers.openai.com/codex/skills/)
and [Claude Code skills documentation](https://code.claude.com/docs/en/skills).
Local Codex use and the standalone helper have been tested. Claude Code
execution and Claude desktop import have not yet been tested; installing
Claude desktop alone is not the same as installing this skill in Claude Code.

A distributed `.skill` file is a ZIP-format bundle of the source folder,
not an executable or a universal installer. The readable source is canonical.

## Run Without an Agent

Requires Python 3.10+ and permitted direct HTTP(S) access. No third-party
Python packages, API keys, browser, or paid verification service are required.
From the skill folder:

```sh
python3 scripts/quote_link.py \
  --url 'https://tactiq.io/claude' \
  --quote 'and quote it back with the source attached'
```

The JSON result includes `vdl`, `matched_text`, the selector, check time, and
a SHA-256 digest of the fetched HTML. For repeated passages, add
`--prefix 'immediately preceding words'` and/or
`--suffix 'immediately following words'`. Ambiguous results include snippets
to help identify the intended occurrence. Do not supply paraphrases as quotes.

| Status | Meaning |
| --- | --- |
| `destination_text_verified` | Fresh destination HTML text and selector checked. |
| `fixture_text_verified` | Local fixture checked; not live verification. |
| `not_verified` | Check failed; no VDL is returned. |

Exit status is 0 for a successful check, including fixture checks, or 2 for
failure. Offline testing uses `--html-file path/to/page.html` and never sets
`verified` to true.

## What Verification Means

The helper checks the passage in server-returned HTML, normalizes whitespace,
and verifies that its selector identifies the intended occurrence. It encodes
reserved characters and uses start/end selectors for cross-block quotations.
It does not silently truncate the quote or pick the first ambiguous match.

It does **not** prove a claim true, guarantee future page content, execute
JavaScript, evaluate external CSS, inspect a rendered DOM, or test browser
highlighting. PDF-only, authenticated, blocked, or rendering-dependent pages
may be unsupported. Use an ordinary source link and explain the limitation
when verification fails. Never manufacture a verified link.

The network helper rejects credential URLs, non-public IP addresses,
HTTPS-to-HTTP redirects, non-HTML responses, excessive redirects, and oversized
responses. It dials validated numeric addresses while preserving TLS hostname
verification. Environment proxies are intentionally disabled so they cannot
bypass destination checks; proxy-only networks may be unsupported.
Fetching sends an ordinary request to the source server, without browser
cookies. Generated links add no promotional tracking.

Protocol: [Text Fragments](https://wicg.github.io/scroll-to-text-fragment/).

## An Older Hypertext Ideal

The inspiration goes back to late-1980s Macintosh hypertext, including Guide:
follow a quotation back to where it came from. This is an old aspiration,
not a claim to have invented deep linking.

Guide itself is earlier than circa 1989: [Peter Brown dates its creation to
1985](https://empslocal.ex.ac.uk/people/staff/pjbrown/public_html/guide/), and
[CERN's hypertext chronology records OWL introducing Guide in
1986](https://info.cern.ch/hypertext/History.html). Today's browser text
fragments provide a different mechanism for pointing at a passage on the Web.

## Development

```sh
python3 -B scripts/test_quote_link.py
```

The offline suite covers text extraction, encoding, ambiguity, cross-block
selectors, and network safeguards, including DNS rebinding and TLS hostname
verification. Live fetches are a separate check, not part of the offline suite.
The standard skill validator additionally requires PyYAML in its own authoring
environment; PyYAML is not a runtime dependency of this project.

## License

[MIT](LICENSE). Copyright (c) 2026 Jean Tantra.
