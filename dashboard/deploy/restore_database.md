# Restore database

1. Stop bot and dashboard API with PM2.
2. Copy the current `data/ryukomik.db` to a separate incident archive.
3. Copy the selected file from `data/backups/` to `data/ryukomik.db`.
4. Run `PRAGMA integrity_check` and compare assignment, invoice, invoice-item, and payment counts.
5. Start the API first, check `/health`, then start the bot and perform a Discord smoke test.

Never restore while either process is writing to SQLite.
