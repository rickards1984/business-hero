# AI-1d — Codex code review 4, targeted (verbatim)

Model gpt-6-astra, read-only sandbox, 22 Nov 2026.

---

REQUEST CHANGES

1. **Medium — blocking: Aria’s previous stripping is not fully preserved.** [backend/services/ai_text.py:194](/Users/michaelrickards/dev/bh2-AI1d/backend/services/ai_text.py:194). For an answer starting with ` ```json[` followed by a newline, valid draft objects and `]`, without a closing fence, the old Aria code removed the backticks and `json` label and successfully parsed the array. `_legacy_strip` instead discards the first line, including `[`. Reproduced: JSON parsing fails and Aria returns fallback drafts. The new tests only exercise an opening fence on its own line.

2. **Medium — blocking: embedded fences can still replace a previously accepted payload.** [backend/services/ai_text.py:180](/Users/michaelrickards/dev/bh2-AI1d/backend/services/ai_text.py:180). Legacy stripping runs **after** fenced-block extraction. A valid classification array containing `"summary": "Customer quoted ```[]```"`, followed by a lone closing fence, previously parsed successfully. Now extraction returns the embedded `[]` before legacy stripping runs. Reproduced through inbox sorting: the classification disappears. The same selection error affects legacy-wrapped draft arrays. Tests cover wrappers and embedded fences separately, but miss this combination.

**Validation:** 92 tests passed across `test_ai_text.py` and `test_ai_text_sites.py`. Review 3’s exact examples are fixed; bare valid JSON containing fences and the earlier prose/closing-remark cases remain protected. The tests do not establish full legacy compatibility.

`check.sh` was not run because it writes artifacts. No files were modified, committed or pushed.