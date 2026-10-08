# Generated frontend contracts

The backend owns the wire contract. Do not edit files under `schema/` or
`generated/` by hand.

From the repository root, refresh both layers after a backend contract change:

```bash
python scripts/export_frontend_contracts.py
cd web && npm run contracts:generate
```

CI runs `python scripts/export_frontend_contracts.py --check` in backend contract
tests and `npm run contracts:check` before frontend typechecking. A drift failure
means the committed artifacts must be regenerated with the commands above.

`ask_user` options may include an opaque `option_id` (1–128 characters, unique
within the question). A single-choice reply carries it unchanged as
`answers[].selected_option_id`; `label` and `description` remain display copy.
Legacy options without IDs, skipped questions, and free-text replies keep their
existing text-only answer shape. Multi-select replies keep their existing joined
display text; they do not claim a single selected identity.
