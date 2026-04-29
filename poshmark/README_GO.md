# Poshmark Go Migration

This repository now contains a structured Go implementation of the core logic.

## Project layout

- `cmd/poshmark` - application entrypoint.
- `internal/config` - environment and static configuration.
- `internal/domain` - entities and default configs.
- `internal/storage` - JSON persistence (`userdata/<user_id>/*.json`).
- `internal/smtp` - SMTP sender with SSL/STARTTLS fallback.
- `internal/parser` - Poshmark parser service.

## Run

```bash
go mod tidy
go run ./cmd/poshmark
```

Run Telegram bot (Go version):

```bash
go run ./cmd/poshmark-bot
```

Optional env:

- `USER_ID` - user namespace in `userdata` (`demo` by default).
- `DATA_DIR` - data root folder (`userdata` by default).
- `BOT_TOKEN` - required for `cmd/poshmark-bot`.
- `BOT_ADMIN_IDS` - comma-separated Telegram IDs allowed to manage access (`123,456`).

## Notes

- Existing Python code is left intact as a reference during migration.
- The Go version focuses on structured core modules first, so handlers can be migrated incrementally.

## Telegram command quickstart (Go bot)

- `/help` - show all commands.
- `/whoami` - show your Telegram ID.
- `/account_add email password` - add SMTP account.
- `/template_set name <html>` + `/template_select name` - create/select templates.
- `/subjects_set subj1 | subj2` and `/var_set key value1 | value2` - configure content rotation.
- `/send email1 email2 ...` - run campaign.
- `/parser_start` / `/parser_stop` / `/parser_status` - control parser.

Admin-only access commands:

- `/grant <telegram_id>` - allow user.
- `/revoke <telegram_id>` - remove user access.
- `/access_list` - list allowed Telegram IDs.
