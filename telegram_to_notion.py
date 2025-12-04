import os
import re
import argparse
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv
from pyrogram import Client
from pyrogram.enums import MessageMediaType
from notion_client import Client as NotionClient

# Load environment variables
load_dotenv()


def parse_args():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description="Export Telegram Saved Messages to Notion",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python script.py                           # Export all messages
  python script.py --word github             # Only messages containing "github"
  python script.py --word "python|javascript" # Messages with "python" OR "javascript"
  python script.py --hashtag project         # Only messages with #project
  python script.py --type Photo Video        # Only photos and videos
  python script.py --limit 50                # Export only 50 messages
  python script.py --days 7                  # Messages from last 7 days
  python script.py --has-url                 # Only messages with URLs
  python script.py --dry-run                 # Preview without exporting
  python script.py --save exports            # Also save matched messages as .txt files
  python script.py --word github --type Text --limit 100
        """
    )
    
    # Content filters
    parser.add_argument(
        "--word", "-w",
        type=str,
        help="Filter by word/phrase (case-insensitive). Use | for OR: 'python|javascript'"
    )
    
    parser.add_argument(
        "--hashtag", "-t",
        type=str,
        nargs="+",
        help="Filter by hashtag(s) (without #). Example: --hashtag project work"
    )
    
    parser.add_argument(
        "--type",
        type=str,
        nargs="+",
        choices=["Text", "Photo", "Video", "Document", "Audio", "Voice", "GIF", "Sticker", "Poll", "Location", "Contact", "Other"],
        help="Filter by message type(s). Example: --type Photo Video"
    )
    
    # Time filters
    parser.add_argument(
        "--days",
        type=int,
        help="Export messages from last N days"
    )
    
    parser.add_argument(
        "--after",
        type=str,
        help="Export messages after date (YYYY-MM-DD)"
    )
    
    parser.add_argument(
        "--before",
        type=str,
        help="Export messages before date (YYYY-MM-DD)"
    )
    
    # Other filters
    parser.add_argument(
        "--has-url",
        action="store_true",
        help="Only messages containing URLs"
    )
    
    parser.add_argument(
        "--has-media",
        action="store_true",
        help="Only messages with media (photo, video, document, etc.)"
    )
    
    parser.add_argument(
        "--no-media",
        action="store_true",
        help="Only text messages without media"
    )
    
    # Export options
    parser.add_argument(
        "--limit", "-l",
        type=int,
        help="Maximum number of messages to export"
    )
    
    parser.add_argument(
        "--skip",
        type=int,
        default=0,
        help="Skip first N messages"
    )
    
    parser.add_argument(
        "--save", "-s",
        nargs="?",
        const="exported_messages.txt",
        default=None,
        metavar="FILE",
        help="Save matched messages into a single .txt FILE (default: exported_messages.txt when flag is used)"
    )
    
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview messages without exporting to Notion"
    )
    
    parser.add_argument(
        "--yes", "-y",
        action="store_true",
        help="Skip confirmation prompt"
    )
    
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show detailed output for each message"
    )
    
    return parser.parse_args()

# Telegram credentials
API_ID = os.getenv("TELEGRAM_API_ID")
API_HASH = os.getenv("TELEGRAM_API_HASH")
PHONE = os.getenv("TELEGRAM_PHONE")

# Notion credentials
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
DATABASE_ID = os.getenv("NOTION_DATABASE_ID")

# Clients initialization
telegram_app = Client("saved_messages_session", api_id=API_ID, api_hash=API_HASH)
notion = NotionClient(auth=NOTION_TOKEN)

# === FIXED PROPERTY NAMES FOR YOUR NOTION DATABASE ===
# According to the Notion database structure
PROP_NAME = "Name"           # title
PROP_TYPE = "Type"           # select
PROP_DATE = "Date"           # date
PROP_MESSAGE_ID = "Message ID"  # number
PROP_TAGS = "Tags"           # multi_select
PROP_URL = "URL"             # url


def extract_urls(text):
    """Extract all URLs from text"""
    if not text:
        return []
    url_pattern = r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+'
    return re.findall(url_pattern, text)


def extract_hashtags(text):
    """Extract all hashtags from text"""
    if not text:
        return []
    return re.findall(r'#(\w+)', text)


def get_message_type(message):
    """Determine message type matching Notion options"""
    if message.photo:
        return "Photo"
    elif message.video:
        return "Video"
    elif message.document:
        return "Document"
    elif message.audio:
        return "Audio"
    elif message.voice:
        return "Voice"
    elif message.sticker:
        return "Sticker"
    elif message.animation:
        return "GIF"  # Matches option in database
    elif message.poll:
        return "Poll"
    elif message.location:
        return "Location"
    elif message.contact:
        return "Contact"
    elif message.text:
        return "Text"
    else:
        return "Other"


def create_notion_page(message):
    """Create a Notion page with message data"""
    
    # Main text
    text = message.text or message.caption or ""
    
    # Extract metadata
    urls = extract_urls(text)
    hashtags = extract_hashtags(text)
    msg_type = get_message_type(message)
    
    # Trim text for Title (Notion has a limit)
    title = text[:100] if text else f"{msg_type} message"
    if len(text) > 100:
        title += "..."
    
    # Build Notion properties
    properties = {
        PROP_NAME: {
            "title": [
                {
                    "text": {
                        "content": title
                    }
                }
            ]
        },
        PROP_TYPE: {
            "select": {
                "name": msg_type
            }
        },
        PROP_DATE: {
            "date": {
                "start": message.date.isoformat()
            }
        },
        PROP_MESSAGE_ID: {
            "number": message.id
        }
    }
    
    # Add hashtags as multi-select (max 5)
    if hashtags:
        properties[PROP_TAGS] = {
            "multi_select": [{"name": tag} for tag in hashtags[:5]]
        }
    
    # Add first URL
    if urls:
        properties[PROP_URL] = {
            "url": urls[0]
        }
    
    # Build page content
    children = []
    
    # Add main text (if longer than 100 chars)
    if text and len(text) > 100:
        # Split into paragraphs (Notion has 2000 char limit per block)
        paragraphs = [text[i:i+2000] for i in range(0, len(text), 2000)]
        for para in paragraphs:
            children.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{
                        "type": "text",
                        "text": {"content": para}
                    }]
                }
            })
    
    # Add media info
    if message.photo:
        children.append({
            "object": "block",
            "type": "callout",
            "callout": {
                "rich_text": [{
                    "type": "text",
                    "text": {"content": f"📷 Photo (File ID: {message.photo.file_id})"}
                }],
                "icon": {"emoji": "📷"}
            }
        })
    
    if message.video:
        children.append({
            "object": "block",
            "type": "callout",
            "callout": {
                "rich_text": [{
                    "type": "text",
                    "text": {"content": f"🎥 Video (File ID: {message.video.file_id})"}
                }],
                "icon": {"emoji": "🎥"}
            }
        })
    
    if message.document:
        file_name = message.document.file_name or "Unknown"
        children.append({
            "object": "block",
            "type": "callout",
            "callout": {
                "rich_text": [{
                    "type": "text",
                    "text": {"content": f"📎 Document: {file_name}"}
                }],
                "icon": {"emoji": "📎"}
            }
        })
    
    if message.audio:
        title_audio = message.audio.title or message.audio.file_name or "Unknown"
        children.append({
            "object": "block",
            "type": "callout",
            "callout": {
                "rich_text": [{
                    "type": "text",
                    "text": {"content": f"🎵 Audio: {title_audio}"}
                }],
                "icon": {"emoji": "🎵"}
            }
        })
    
    if message.voice:
        duration = message.voice.duration
        children.append({
            "object": "block",
            "type": "callout",
            "callout": {
                "rich_text": [{
                    "type": "text",
                    "text": {"content": f"🎤 Voice message ({duration}s)"}
                }],
                "icon": {"emoji": "🎤"}
            }
        })
    
    if message.sticker:
        emoji = message.sticker.emoji or "🎨"
        children.append({
            "object": "block",
            "type": "callout",
            "callout": {
                "rich_text": [{
                    "type": "text",
                    "text": {"content": f"Sticker: {emoji}"}
                }],
                "icon": {"emoji": emoji}
            }
        })
    
    if message.animation:
        children.append({
            "object": "block",
            "type": "callout",
            "callout": {
                "rich_text": [{
                    "type": "text",
                    "text": {"content": f"🎬 GIF (File ID: {message.animation.file_id})"}
                }],
                "icon": {"emoji": "🎬"}
            }
        })
    
    if message.location:
        children.append({
            "object": "block",
            "type": "callout",
            "callout": {
                "rich_text": [{
                    "type": "text",
                    "text": {"content": f"📍 Location: {message.location.latitude}, {message.location.longitude}"}
                }],
                "icon": {"emoji": "📍"}
            }
        })
    
    if message.contact:
        contact_name = f"{message.contact.first_name or ''} {message.contact.last_name or ''}".strip()
        children.append({
            "object": "block",
            "type": "callout",
            "callout": {
                "rich_text": [{
                    "type": "text",
                    "text": {"content": f"👤 Contact: {contact_name} ({message.contact.phone_number})"}
                }],
                "icon": {"emoji": "👤"}
            }
        })
    
    if message.poll:
        children.append({
            "object": "block",
            "type": "callout",
            "callout": {
                "rich_text": [{
                    "type": "text",
                    "text": {"content": f"📊 Poll: {message.poll.question}"}
                }],
                "icon": {"emoji": "📊"}
            }
        })
    
    # Add all URLs as list
    if urls:
        children.append({
            "object": "block",
            "type": "heading_3",
            "heading_3": {
                "rich_text": [{
                    "type": "text",
                    "text": {"content": "🔗 Links"}
                }]
            }
        })
        for url in urls:
            children.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{
                        "type": "text",
                        "text": {"content": url, "link": {"url": url}}
                    }]
                }
            })
    
    try:
        # Create page in Notion
        create_args = {
            "parent": {"database_id": DATABASE_ID},
            "properties": properties
        }
        
        if children:  # Only when there is content
            create_args["children"] = children
        
        notion.pages.create(**create_args)
        return True
    except Exception as e:
        print(f"❌ Notion API Error: {e}")
        return False


def save_message_to_txt(message, file_path):
    """Append a message with metadata to a single text file"""
    text = message.text or message.caption or ""
    msg_type = get_message_type(message)
    hashtags = extract_hashtags(text)
    urls = extract_urls(text)
    
    lines = [
        f"Message ID: {message.id}",
        f"Date: {message.date.isoformat()}",
        f"Type: {msg_type}"
    ]
    
    if hashtags:
        lines.append(f"Hashtags: #{' #'.join(hashtags)}")
    if urls:
        lines.append(f"URLs: {' '.join(urls)}")
    
    lines.append("")
    lines.append(text or "(no text)")
    block = "\n".join(lines)
    with open(file_path, "a", encoding="utf-8") as f:
        f.write(block + "\n\n")
    return file_path


def message_matches_filters(message, args):
    """
    Check whether a message satisfies the provided filters
    
    Returns:
        bool: True if the message passes all filters
    """
    text = message.text or message.caption or ""
    msg_type = get_message_type(message)
    
    # Word/phrase filter
    if args.word:
        pattern = args.word.replace("|", "|")  # Supports OR via |
        if not re.search(pattern, text, re.IGNORECASE):
            return False
    
    # Hashtag filter
    if args.hashtag:
        message_hashtags = [tag.lower() for tag in extract_hashtags(text)]
        required_hashtags = [tag.lower() for tag in args.hashtag]
        if not any(tag in message_hashtags for tag in required_hashtags):
            return False
    
    # Message type filter
    if args.type:
        if msg_type not in args.type:
            return False
    
    # Date filter (--days)
    if args.days:
        cutoff_date = datetime.now() - timedelta(days=args.days)
        if message.date.replace(tzinfo=None) < cutoff_date:
            return False
    
    # Date filter (--after)
    if args.after:
        after_date = datetime.strptime(args.after, "%Y-%m-%d")
        if message.date.replace(tzinfo=None) < after_date:
            return False
    
    # Date filter (--before)
    if args.before:
        before_date = datetime.strptime(args.before, "%Y-%m-%d")
        if message.date.replace(tzinfo=None) > before_date:
            return False
    
    # Filter: only with URL
    if args.has_url:
        if not extract_urls(text):
            return False
    
    # Filter: only with media
    if args.has_media:
        if msg_type == "Text" or msg_type == "Other":
            return False
    
    # Filter: text only (no media)
    if args.no_media:
        if msg_type != "Text":
            return False
    
    return True


def print_message_preview(message, idx):
    """Print a preview of the message for dry-run"""
    text = message.text or message.caption or ""
    msg_type = get_message_type(message)
    date_str = message.date.strftime("%Y-%m-%d %H:%M")
    
    # Trim text for preview
    preview = text[:80].replace("\n", " ")
    if len(text) > 80:
        preview += "..."
    
    hashtags = extract_hashtags(text)
    urls = extract_urls(text)
    
    print(f"\n{idx}. [{msg_type}] {date_str}")
    print(f"   📝 {preview if preview else '(no text)'}")
    if hashtags:
        print(f"   🏷️  #{' #'.join(hashtags[:5])}")
    if urls:
        print(f"   🔗 {urls[0]}")


async def export_saved_messages(args):
    """
    Main export function with filtering
    
    Args:
        args: Parsed CLI arguments
    """
    print("🚀 Telegram Saved Messages → Notion Export")
    print("=" * 60)
    
    save_path = Path(args.save) if args.save else None
    if save_path:
        save_path.parent.mkdir(parents=True, exist_ok=True)
        save_path.write_text("", encoding="utf-8")  # start fresh per run
    
    # Display active filters
    filters_active = []
    if args.word:
        filters_active.append(f"word: '{args.word}'")
    if args.hashtag:
        filters_active.append(f"hashtags: #{', #'.join(args.hashtag)}")
    if args.type:
        filters_active.append(f"types: {', '.join(args.type)}")
    if args.days:
        filters_active.append(f"last {args.days} days")
    if args.after:
        filters_active.append(f"after {args.after}")
    if args.before:
        filters_active.append(f"before {args.before}")
    if args.has_url:
        filters_active.append("has URL")
    if args.has_media:
        filters_active.append("has media")
    if args.no_media:
        filters_active.append("text only")
    if args.limit:
        filters_active.append(f"limit: {args.limit}")
    if args.skip:
        filters_active.append(f"skip: {args.skip}")
    
    if filters_active:
        print(f"🔍 Filters: {' | '.join(filters_active)}")
    else:
        print("🔍 Filters: none (all messages)")
    
    if save_path:
        print(f"🗂️  Save to txt: {save_path.resolve()}")
    
    if args.dry_run:
        print("⚠️  DRY RUN MODE - no changes will be made")
    
    print(f"📋 Database ID: {DATABASE_ID}")
    print("=" * 60)
    
    async with telegram_app:
        print("\n✅ Connected to Telegram")
        
        # Fetch and filter messages
        messages = []
        total_fetched = 0
        skipped = 0
        
        print("📥 Fetching and filtering messages...")
        
        async for message in telegram_app.get_chat_history("me"):
            total_fetched += 1
            
            # Skip first N messages
            if skipped < args.skip:
                skipped += 1
                continue
            
            # Apply filters
            if message_matches_filters(message, args):
                messages.append(message)
                
                # Respect limit
                if args.limit and len(messages) >= args.limit:
                    break
            
            if total_fetched % 100 == 0:
                print(f"   Scanned {total_fetched} messages, matched {len(messages)}...")
        
        print(f"\n✅ Scanned: {total_fetched} | Matched: {len(messages)}")
        
        if not messages:
            print("❌ No messages match the filters.")
            return
        
        # Dry run - show preview only
        if args.dry_run:
            print("\n📋 Messages that would be exported:")
            if save_path:
                print("ℹ️  Save to txt is skipped in dry-run mode.")
            for idx, message in enumerate(reversed(messages), 1):
                print_message_preview(message, idx)
                if idx >= 20:
                    remaining = len(messages) - 20
                    if remaining > 0:
                        print(f"\n   ... and {remaining} more messages")
                    break
            print(f"\n✅ Dry run complete. {len(messages)} messages would be exported.")
            return
        
        # Confirmation
        if not args.yes:
            confirm = input(f"\n📤 Export {len(messages)} messages to Notion? (y/n): ")
            if confirm.lower() != 'y':
                print("❌ Export cancelled.")
                return
        
        print(f"\n🔄 Starting export...")
        print("=" * 60)
        
        # Export to Notion (reverse order - oldest first)
        success_count = 0
        failed_count = 0
        saved_count = 0
        save_errors = 0
        
        for idx, message in enumerate(reversed(messages), 1):
            saved_path = None
            if save_path:
                try:
                    saved_path = save_message_to_txt(message, save_path)
                    saved_count += 1
                    if args.verbose:
                        print(f"   🗂️ [{idx}/{len(messages)}] Saved to {save_path.name}")
                except Exception as e:
                    save_errors += 1
                    if args.verbose:
                        print(f"   ⚠️ [{idx}/{len(messages)}] Failed to save txt: {e}")
            
            success = create_notion_page(message)
            
            if success:
                success_count += 1
                if args.verbose:
                    text = (message.text or message.caption or "")[:50]
                    print(f"   ✓ [{idx}/{len(messages)}] {text}...")
            else:
                failed_count += 1
                if args.verbose:
                    print(f"   ✗ [{idx}/{len(messages)}] Failed")
            
            if not args.verbose and idx % 10 == 0:
                pct = idx * 100 // len(messages)
                print(f"   Progress: {idx}/{len(messages)} ({pct}%) | ✓ {success_count} | ✗ {failed_count}")
        
        print("=" * 60)
        print(f"\n✨ Export completed!")
        print(f"   ✓ Successfully exported: {success_count}")
        print(f"   ✗ Failed: {failed_count}")
        print(f"   Total: {len(messages)}")
        if save_path:
            save_summary = f"   🗂️ Saved to txt: {saved_count}"
            if save_errors:
                save_summary += f" | errors: {save_errors}"
            print(f"{save_summary} → {save_path.resolve()}")


if __name__ == "__main__":
    args = parse_args()
    telegram_app.run(export_saved_messages(args))
