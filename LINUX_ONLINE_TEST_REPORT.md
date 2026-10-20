# Linux online MCP validation

Tested October 10, 2026 on Linux with Python 3.12, using credentials saved by
the user in Secret Service. The plugin launcher ran a real MCP stdio server
with temporary small-task limits. All six API submissions succeeded; retries
were disabled. No API keys are included in this report or committed files.

| Check | Actual model | Result |
| --- | --- | --- |
| DeepSeek text | `deepseek-flash` | Returned `def add(a, b): return a + b` |
| Gemini text | `gemini-3.8-flash` | Returned exactly `OK` |
| Knowledge/search | `gemini-3.8-flash` | Answered Paris; actual search enabled, one source returned |
| Audio | `gemini-3.8-flash` | Correctly identified the synthetic one-second tone as non-speech |
| Image generation | `gemini-3.1-flash-image` | Saved a valid 512 x 512 JPEG with blue foreground and white background |
| Reference-image edit | `gemini-3.1-flash-image` | Saved a valid 512 x 512 JPEG with red foreground and white background |

The gateway exposed all nine tools. Image files decoded successfully with
Pillow. Pixel checks measured approximately 16% blue / 84% white in the
generated image and 16% red / 84% white in the edit, with no remaining blue
foreground in the edit. These are automated file/color checks, not a human
visual inspection. Text and audio responses were also reviewed against the
synthetic prompts; generated code was not executed.

Provider-reported total tokens: DeepSeek 53; Gemini text 106, knowledge 360,
audio 146, generation 1010, edit 1200. Gemini totals can include thinking and
image tokens. These figures are not monetary cost estimates; Google Search
and image charges follow provider pricing.

Reproduce with `.venv/bin/python run_online_selftest.py` after installing the
plugin and saving keys. This makes paid requests. The runner stores full
results under the ignored `outputs/online-self-test/<UTC timestamp>/`
directory and synthetic audio under ignored `inputs/`. Generated images,
configuration, credentials, and raw response evidence are not committed.

This validates the tested accounts and configured models at the test time.
Quota, model access, and networking can differ on other devices/accounts.
