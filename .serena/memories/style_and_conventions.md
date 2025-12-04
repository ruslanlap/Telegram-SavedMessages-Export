# Style and Conventions
- Code is procedural within a single module; snake_case names, no type hints.
- Docstrings are short (often Ukrainian) with concise descriptions; logging uses emojis and f-strings for readable CLI output.
- Filters and messaging are user-facing; keep prompts concise and friendly; preserve bilingual tone where present.
- Uses Path/os/re for filesystem/text handling; avoid adding extra dependencies.