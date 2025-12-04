# Project Overview
- Purpose: Export Telegram Saved Messages to a Notion database with filterable criteria (words, hashtags, message types, date ranges, media flags), dry-run previews, and optional local .txt saves via `--save`.
- Tech stack: Python + Pyrogram for Telegram, Notion client SDK, python-dotenv for env loading; dependencies declared in requirements.txt.
- Structure: Single main script `telegram_to_notion.py`; Pyrogram session file `saved_messages_session.session`; uses constants for Notion property names (Name, Type, Date, Message ID, Tags, URL).
- Runtime config: expects env vars TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_PHONE, NOTION_TOKEN, NOTION_DATABASE_ID (loaded from .env if present).
- Flow: parse CLI args -> connect to Telegram -> fetch & filter messages -> optional dry-run preview -> create Notion pages (with metadata blocks for media/links); optional `save_message_to_txt` writes matched messages locally when `--save` is set.