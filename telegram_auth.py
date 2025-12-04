"""
Telegram Authentication Script
Run this once to create a session file before using the GUI.

Usage:
    py telegram_auth.py
"""

import json
from pathlib import Path
from pyrogram import Client


def load_config():
    """Load config from file"""
    config_path = Path("telegram_notion_config.json")
    if config_path.exists():
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def main():
    print("=" * 50)
    print("Telegram Authentication")
    print("=" * 50)
    
    config = load_config()
    
    api_id = config.get('telegram_api_id')
    api_hash = config.get('telegram_api_hash')
    phone = config.get('telegram_phone')
    
    if not api_id or not api_hash:
        print("\n❌ Missing API credentials!")
        print("Please enter your Telegram API ID and Hash in the GUI first,")
        print("or create telegram_notion_config.json with:")
        print('  {"telegram_api_id": "YOUR_ID", "telegram_api_hash": "YOUR_HASH", "telegram_phone": "+380..."}')
        return
    
    if not phone:
        phone = input("\nEnter your phone number (e.g., +380...): ").strip()
    
    print(f"\n📱 Phone: {phone}")
    print("🔑 Connecting to Telegram...")
    print("\nYou will receive a confirmation code via Telegram.")
    print("If you have 2FA enabled, you'll also need to enter your password.\n")
    
    app = Client(
        "telegram_notion_session",
        api_id=api_id,
        api_hash=api_hash,
        phone_number=phone
    )
    
    with app:
        me = app.get_me()
        print(f"\n✅ Successfully logged in as: {me.first_name} (@{me.username or 'no username'})")
        print(f"📁 Session saved to: telegram_notion_session.session")
        print("\nYou can now use the GUI without entering credentials again!")


if __name__ == "__main__":
    main()
