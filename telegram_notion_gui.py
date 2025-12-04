"""
Telegram Saved Messages → Notion Exporter
GUI Application for Windows/Mac/Linux

Requirements:
    pip install PyQt6 pyrogram tgcrypto notion-client python-dotenv

Author: Ruslan
"""

import sys
import os
import re
import json
import asyncio
from datetime import datetime, timedelta
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QTextEdit, QProgressBar,
    QGroupBox, QFormLayout, QComboBox, QCheckBox, QSpinBox,
    QDateEdit, QTabWidget, QFileDialog, QMessageBox, QFrame,
    QScrollArea, QSplitter, QStatusBar, QStyle, QInputDialog
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QDate, QSettings
from PyQt6.QtGui import QFont, QIcon, QPalette, QColor

# Telegram & Notion imports
from pyrogram import Client
from notion_client import Client as NotionClient


class Config:
    """Manages application configuration"""
    
    CONFIG_FILE = "telegram_notion_config.json"
    
    @classmethod
    def load(cls):
        """Load config from file"""
        config_path = Path(cls.CONFIG_FILE)
        if config_path.exists():
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                pass
        return {}
    
    @classmethod
    def save(cls, data):
        """Save config to file"""
        with open(cls.CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)


# Global variable to hold pending auth input (for GUI dialogs)
_auth_input_result = None
_auth_input_event = None


class AuthInputDialog:
    """Helper class for authentication dialogs in GUI"""
    
    @staticmethod
    def get_code(phone_number: str) -> str:
        """Show dialog to get confirmation code"""
        code, ok = QInputDialog.getText(
            None,
            "Telegram Confirmation Code",
            f"Enter the confirmation code sent to {phone_number}:",
            QLineEdit.EchoMode.Normal
        )
        return code if ok else ""
    
    @staticmethod
    def get_password(hint: str = None) -> str:
        """Show dialog to get 2FA password"""
        hint_text = f"\nHint: {hint}" if hint else ""
        password, ok = QInputDialog.getText(
            None,
            "Two-Factor Authentication",
            f"Enter your 2FA password:{hint_text}",
            QLineEdit.EchoMode.Password
        )
        return password if ok else ""


class ExportWorker(QThread):
    """Background worker for export operations"""
    
    progress = pyqtSignal(int, int, str)  # current, total, message
    log = pyqtSignal(str)  # log message
    finished = pyqtSignal(int, int)  # success_count, failed_count
    error = pyqtSignal(str)  # error message
    request_code = pyqtSignal(str)  # phone_number - request confirmation code
    request_password = pyqtSignal(str)  # hint - request 2FA password
    
    def __init__(self, config, filters, export_settings):
        super().__init__()
        self.config = config
        self.filters = filters
        self.export_settings = export_settings
        self._is_cancelled = False
        self._auth_code = None
        self._auth_password = None
        self._auth_event = None
    
    def cancel(self):
        self._is_cancelled = True
    
    def set_auth_code(self, code: str):
        """Set the auth code from GUI dialog"""
        self._auth_code = code
        if self._auth_event:
            self._auth_event.set()
    
    def set_auth_password(self, password: str):
        """Set the 2FA password from GUI dialog"""
        self._auth_password = password
        if self._auth_event:
            self._auth_event.set()
    
    def run(self):
        """Main export logic"""
        try:
            asyncio.run(self._export())
        except Exception as e:
            self.error.emit(f"Export error: {str(e)}")
    
    async def _export(self):
        """Async export implementation"""
        
        # Initialize clients
        self.log.emit("🔑 Connecting to Telegram...")
        
        phone = self.config.get('telegram_phone') or None
        
        # Check if session already exists
        session_file = Path("telegram_notion_session.session")
        need_auth = not session_file.exists()
        
        if need_auth:
            self.log.emit("📱 First-time login - you'll be asked for confirmation code...")
        
        # Create client with GUI-based auth handlers
        telegram = Client(
            "telegram_notion_session",
            api_id=self.config['telegram_api_id'],
            api_hash=self.config['telegram_api_hash'],
            phone_number=phone
        )
        
        notion = NotionClient(auth=self.config['notion_token'])
        
        # Connect with GUI dialog handlers for auth
        try:
            # Use connect() instead of start() to handle auth manually
            is_authorized = await telegram.connect()
            
            if not is_authorized:
                self.log.emit("📲 Sending confirmation code...")
                sent_code = await telegram.send_code(phone)
                
                # Request code via signal (will show dialog in main thread)
                self.request_code.emit(phone)
                
                # Wait for code to be set
                while self._auth_code is None and not self._is_cancelled:
                    await asyncio.sleep(0.1)
                
                if self._is_cancelled or not self._auth_code:
                    self.error.emit("❌ Authentication cancelled")
                    await telegram.disconnect()
                    return
                
                self.log.emit("🔐 Signing in...")
                try:
                    await telegram.sign_in(phone, sent_code.phone_code_hash, self._auth_code)
                except Exception as e:
                    if "password" in str(e).lower() or "2fa" in str(e).lower() or "two-step" in str(e).lower():
                        # 2FA required
                        self.log.emit("🔒 Two-factor authentication required...")
                        self.request_password.emit("")
                        
                        while self._auth_password is None and not self._is_cancelled:
                            await asyncio.sleep(0.1)
                        
                        if self._is_cancelled or not self._auth_password:
                            self.error.emit("❌ Authentication cancelled")
                            await telegram.disconnect()
                            return
                        
                        await telegram.check_password(self._auth_password)
                    else:
                        raise e
                
                self.log.emit("✅ Successfully logged in!")
        
        except Exception as auth_error:
            self.error.emit(f"❌ Connection error: {auth_error}")
            try:
                await telegram.disconnect()
            except:
                pass
            return
        
        try:
            self.log.emit("✅ Connected to Telegram")
            
            # Fetch messages
            self.log.emit("📥 Fetching messages...")
            messages = []
            total_scanned = 0
            
            async for message in telegram.get_chat_history("me"):
                if self._is_cancelled:
                    self.log.emit("❌ Export cancelled by user")
                    return
                
                total_scanned += 1
                
                if self._matches_filters(message):
                    messages.append(message)
                    
                    if self.filters.get('limit') and len(messages) >= self.filters['limit']:
                        break
                
                if total_scanned % 100 == 0:
                    self.progress.emit(0, 0, f"Scanned {total_scanned}, matched {len(messages)}...")
            
            self.log.emit(f"✅ Found {len(messages)} matching messages")
            
            if not messages:
                self.log.emit("⚠️ No messages match the filters")
                self.finished.emit(0, 0)
                return
            
            # Export to selected format
            export_format = self.export_settings.get('format', 'notion')
            
            if export_format == 'notion':
                success, failed = await self._export_to_notion(messages, notion)
            elif export_format == 'json':
                success, failed = self._export_to_json(messages)
            elif export_format == 'csv':
                success, failed = self._export_to_csv(messages)
            elif export_format == 'markdown':
                success, failed = self._export_to_markdown(messages)
            else:
                success, failed = await self._export_to_notion(messages, notion)
            
            self.finished.emit(success, failed)
        finally:
            try:
                await telegram.disconnect()
            except Exception:
                pass  # Ignore disconnect errors
    
    def _matches_filters(self, message):
        """Check if message matches all filters"""
        text = message.text or message.caption or ""
        msg_type = self._get_message_type(message)
        
        # Word filter
        if self.filters.get('word'):
            pattern = self.filters['word']
            if not re.search(pattern, text, re.IGNORECASE):
                return False
        
        # Hashtag filter
        if self.filters.get('hashtags'):
            msg_hashtags = [t.lower() for t in re.findall(r'#(\w+)', text)]
            required = [t.lower() for t in self.filters['hashtags']]
            if not any(t in msg_hashtags for t in required):
                return False
        
        # Type filter
        if self.filters.get('types'):
            if msg_type not in self.filters['types']:
                return False
        
        # Date filters
        msg_date = message.date.replace(tzinfo=None)
        
        if self.filters.get('date_from'):
            if msg_date < self.filters['date_from']:
                return False
        
        if self.filters.get('date_to'):
            if msg_date > self.filters['date_to']:
                return False
        
        # Has URL filter
        if self.filters.get('has_url'):
            urls = re.findall(r'https?://\S+', text)
            if not urls:
                return False
        
        # Has media filter
        if self.filters.get('has_media'):
            if msg_type in ['Text', 'Other']:
                return False
        
        # No media filter
        if self.filters.get('no_media'):
            if msg_type != 'Text':
                return False
        
        return True
    
    def _get_message_type(self, message):
        """Determine message type"""
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
            return "GIF"
        elif message.poll:
            return "Poll"
        elif message.location:
            return "Location"
        elif message.contact:
            return "Contact"
        elif message.text:
            return "Text"
        return "Other"
    
    def _extract_urls(self, text):
        """Extract URLs from text"""
        if not text:
            return []
        return re.findall(r'https?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+', text)
    
    def _extract_hashtags(self, text):
        """Extract hashtags from text"""
        if not text:
            return []
        return re.findall(r'#(\w+)', text)
    
    async def _export_to_notion(self, messages, notion):
        """Export messages to Notion database"""
        success_count = 0
        failed_count = 0
        total = len(messages)
        database_id = self.config['notion_database_id']
        
        for idx, message in enumerate(reversed(messages), 1):
            if self._is_cancelled:
                break
            
            try:
                text = message.text or message.caption or ""
                urls = self._extract_urls(text)
                hashtags = self._extract_hashtags(text)
                msg_type = self._get_message_type(message)
                
                title = text[:100] if text else f"{msg_type} message"
                if len(text) > 100:
                    title += "..."
                
                properties = {
                    "Name": {"title": [{"text": {"content": title}}]},
                    "Type": {"select": {"name": msg_type}},
                    "Date": {"date": {"start": message.date.isoformat()}},
                    "Message ID": {"number": message.id}
                }
                
                if hashtags:
                    properties["Tags"] = {"multi_select": [{"name": tag} for tag in hashtags[:5]]}
                
                if urls:
                    properties["URL"] = {"url": urls[0]}
                
                # Create page content
                children = []
                if text and len(text) > 100:
                    for i in range(0, len(text), 2000):
                        children.append({
                            "object": "block",
                            "type": "paragraph",
                            "paragraph": {
                                "rich_text": [{"type": "text", "text": {"content": text[i:i+2000]}}]
                            }
                        })
                
                create_args = {
                    "parent": {"database_id": database_id},
                    "properties": properties
                }
                if children:
                    create_args["children"] = children
                
                notion.pages.create(**create_args)
                success_count += 1
                
            except Exception as e:
                failed_count += 1
                self.log.emit(f"❌ Failed message {message.id}: {str(e)[:50]}")
            
            self.progress.emit(idx, total, f"Exporting {idx}/{total}")
        
        return success_count, failed_count
    
    def _export_to_json(self, messages):
        """Export messages to JSON file"""
        output_path = self.export_settings.get('output_path', 'telegram_export.json')
        
        data = []
        for message in reversed(messages):
            text = message.text or message.caption or ""
            data.append({
                "id": message.id,
                "date": message.date.isoformat(),
                "type": self._get_message_type(message),
                "text": text,
                "urls": self._extract_urls(text),
                "hashtags": self._extract_hashtags(text)
            })
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        self.log.emit(f"✅ Saved to {output_path}")
        return len(messages), 0
    
    def _export_to_csv(self, messages):
        """Export messages to CSV file"""
        import csv
        output_path = self.export_settings.get('output_path', 'telegram_export.csv')
        
        with open(output_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['ID', 'Date', 'Type', 'Text', 'URLs', 'Hashtags'])
            
            for message in reversed(messages):
                text = message.text or message.caption or ""
                writer.writerow([
                    message.id,
                    message.date.isoformat(),
                    self._get_message_type(message),
                    text,
                    ', '.join(self._extract_urls(text)),
                    ', '.join(self._extract_hashtags(text))
                ])
        
        self.log.emit(f"✅ Saved to {output_path}")
        return len(messages), 0
    
    def _export_to_markdown(self, messages):
        """Export messages to Markdown file"""
        output_path = self.export_settings.get('output_path', 'telegram_export.md')
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write("# Telegram Saved Messages Export\n\n")
            f.write(f"Exported: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n")
            f.write("---\n\n")
            
            for message in reversed(messages):
                text = message.text or message.caption or ""
                msg_type = self._get_message_type(message)
                date_str = message.date.strftime('%Y-%m-%d %H:%M')
                
                f.write(f"## [{msg_type}] {date_str}\n\n")
                f.write(f"{text}\n\n")
                
                urls = self._extract_urls(text)
                if urls:
                    f.write("**Links:**\n")
                    for url in urls:
                        f.write(f"- {url}\n")
                    f.write("\n")
                
                f.write("---\n\n")
        
        self.log.emit(f"✅ Saved to {output_path}")
        return len(messages), 0


class MainWindow(QMainWindow):
    """Main application window"""
    
    def __init__(self):
        super().__init__()
        self.worker = None
        self.init_ui()
        self.load_config()
    
    def init_ui(self):
        """Initialize the user interface"""
        self.setWindowTitle("Telegram → Notion Exporter")
        self.setMinimumSize(800, 700)
        style = self.style()
        
        # Central widget
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setSpacing(10)
        layout.setContentsMargins(15, 15, 15, 15)
        
        # Tab widget
        tabs = QTabWidget()
        layout.addWidget(tabs)
        
        # === Tab 1: Credentials ===
        creds_tab = QWidget()
        creds_layout = QVBoxLayout(creds_tab)
        
        # Telegram credentials
        tg_group = QGroupBox("🔐 Telegram API")
        tg_layout = QFormLayout(tg_group)
        
        self.tg_api_id = QLineEdit()
        self.tg_api_id.setPlaceholderText("Get from my.telegram.org")
        tg_layout.addRow("API ID:", self.tg_api_id)
        
        self.tg_api_hash = QLineEdit()
        self.tg_api_hash.setPlaceholderText("Get from my.telegram.org")
        self.tg_api_hash.setEchoMode(QLineEdit.EchoMode.Password)
        tg_layout.addRow("API Hash:", self.tg_api_hash)
        
        self.tg_phone = QLineEdit()
        self.tg_phone.setPlaceholderText("Phone number used for Telegram login (e.g., +380...)")
        tg_layout.addRow("Phone:", self.tg_phone)
        
        tg_help = QLabel('<a href="https://my.telegram.org/apps">Get credentials at my.telegram.org</a>')
        tg_help.setOpenExternalLinks(True)
        tg_layout.addRow("", tg_help)
        
        creds_layout.addWidget(tg_group)
        
        # Notion credentials
        notion_group = QGroupBox("📝 Notion API")
        notion_layout = QFormLayout(notion_group)
        
        self.notion_token = QLineEdit()
        self.notion_token.setPlaceholderText("Internal Integration Token")
        self.notion_token.setEchoMode(QLineEdit.EchoMode.Password)
        notion_layout.addRow("Token:", self.notion_token)
        
        self.notion_db_id = QLineEdit()
        self.notion_db_id.setPlaceholderText("Database ID from URL")
        notion_layout.addRow("Database ID:", self.notion_db_id)
        
        notion_help = QLabel('<a href="https://www.notion.so/my-integrations">Create integration at notion.so</a>')
        notion_help.setOpenExternalLinks(True)
        notion_layout.addRow("", notion_help)
        
        creds_layout.addWidget(notion_group)
        
        # Save credentials button
        save_creds_btn = QPushButton("Save Credentials")
        save_creds_btn.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton))
        save_creds_btn.clicked.connect(self.save_config)
        creds_layout.addWidget(save_creds_btn)
        
        creds_layout.addStretch()
        tabs.addTab(creds_tab, "🔑 Credentials")
        
        # === Tab 2: Filters ===
        filters_tab = QWidget()
        filters_layout = QVBoxLayout(filters_tab)
        
        # Content filters
        content_group = QGroupBox("📝 Content Filters")
        content_layout = QFormLayout(content_group)
        
        self.filter_word = QLineEdit()
        self.filter_word.setPlaceholderText("e.g., github or python|javascript")
        content_layout.addRow("Keyword:", self.filter_word)
        
        self.filter_hashtags = QLineEdit()
        self.filter_hashtags.setPlaceholderText("e.g., project, work, idea")
        content_layout.addRow("Hashtags:", self.filter_hashtags)
        
        filters_layout.addWidget(content_group)
        
        # Type filters
        type_group = QGroupBox("📎 Message Types")
        type_layout = QHBoxLayout(type_group)
        
        self.type_checkboxes = {}
        types = ["Text", "Photo", "Video", "Document", "Audio", "Voice", "GIF", "Other"]
        
        for msg_type in types:
            cb = QCheckBox(msg_type)
            cb.setChecked(True)
            self.type_checkboxes[msg_type] = cb
            type_layout.addWidget(cb)
        
        filters_layout.addWidget(type_group)
        
        # Date filters
        date_group = QGroupBox("📅 Date Range")
        date_layout = QFormLayout(date_group)
        
        self.date_enabled = QCheckBox("Enable date filter")
        date_layout.addRow("", self.date_enabled)
        
        self.date_from = QDateEdit()
        self.date_from.setCalendarPopup(True)
        self.date_from.setDate(QDate.currentDate().addMonths(-1))
        self.date_from.setEnabled(False)
        date_layout.addRow("From:", self.date_from)
        
        self.date_to = QDateEdit()
        self.date_to.setCalendarPopup(True)
        self.date_to.setDate(QDate.currentDate())
        self.date_to.setEnabled(False)
        date_layout.addRow("To:", self.date_to)
        
        self.date_enabled.toggled.connect(self.date_from.setEnabled)
        self.date_enabled.toggled.connect(self.date_to.setEnabled)
        
        filters_layout.addWidget(date_group)
        
        # Other filters
        other_group = QGroupBox("⚙️ Other Filters")
        other_layout = QFormLayout(other_group)
        
        self.filter_has_url = QCheckBox("Only with URLs")
        other_layout.addRow("", self.filter_has_url)
        
        self.filter_has_media = QCheckBox("Only with media")
        other_layout.addRow("", self.filter_has_media)
        
        self.filter_no_media = QCheckBox("Text only (no media)")
        other_layout.addRow("", self.filter_no_media)
        
        self.filter_limit = QSpinBox()
        self.filter_limit.setRange(0, 10000)
        self.filter_limit.setValue(0)
        self.filter_limit.setSpecialValueText("No limit")
        other_layout.addRow("Limit:", self.filter_limit)
        
        filters_layout.addWidget(other_group)
        filters_layout.addStretch()
        
        tabs.addTab(filters_tab, "🔍 Filters")
        
        # === Tab 3: Export Settings ===
        export_tab = QWidget()
        export_layout = QVBoxLayout(export_tab)
        
        format_group = QGroupBox("📤 Export Format")
        format_layout = QFormLayout(format_group)
        
        self.export_format = QComboBox()
        self.export_format.addItems([
            "Notion Database",
            "JSON File",
            "CSV File",
            "Markdown File"
        ])
        self.export_format.currentIndexChanged.connect(self.on_format_changed)
        format_layout.addRow("Format:", self.export_format)
        
        # Output path (for file exports)
        path_widget = QWidget()
        path_layout = QHBoxLayout(path_widget)
        path_layout.setContentsMargins(0, 0, 0, 0)
        
        self.output_path = QLineEdit()
        self.output_path.setPlaceholderText("telegram_export.json")
        self.output_path.setEnabled(False)
        path_layout.addWidget(self.output_path)
        
        self.browse_btn = QPushButton("Browse...")
        self.browse_btn.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon))
        self.browse_btn.setEnabled(False)
        self.browse_btn.clicked.connect(self.browse_output)
        path_layout.addWidget(self.browse_btn)
        
        format_layout.addRow("Save to:", path_widget)
        
        export_layout.addWidget(format_group)
        export_layout.addStretch()
        
        tabs.addTab(export_tab, "📤 Export")
        
        # === Progress & Log Section ===
        progress_group = QGroupBox("📊 Progress")
        progress_layout = QVBoxLayout(progress_group)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(True)
        progress_layout.addWidget(self.progress_bar)
        
        self.progress_label = QLabel("Ready")
        progress_layout.addWidget(self.progress_label)
        
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(150)
        self.log_text.setStyleSheet("font-family: Consolas, monospace; font-size: 11px;")
        progress_layout.addWidget(self.log_text)
        
        layout.addWidget(progress_group)
        
        # === Action Buttons ===
        btn_layout = QHBoxLayout()
        
        self.start_btn = QPushButton("Start Export")
        self.start_btn.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
        self.start_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                font-size: 14px;
                font-weight: bold;
                padding: 12px 24px;
                border-radius: 6px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
            QPushButton:disabled {
                background-color: #cccccc;
            }
        """)
        self.start_btn.clicked.connect(self.start_export)
        btn_layout.addWidget(self.start_btn)
        
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_DialogCancelButton))
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #f44336;
                color: white;
                font-size: 14px;
                padding: 12px 24px;
                border-radius: 6px;
            }
            QPushButton:hover {
                background-color: #da190b;
            }
            QPushButton:disabled {
                background-color: #cccccc;
            }
        """)
        self.cancel_btn.clicked.connect(self.cancel_export)
        btn_layout.addWidget(self.cancel_btn)
        
        layout.addLayout(btn_layout)
        
        # Status bar
        self.statusBar().showMessage("Ready")
    
    def on_format_changed(self, index):
        """Handle export format change"""
        is_file = index > 0  # Not Notion
        self.output_path.setEnabled(is_file)
        self.browse_btn.setEnabled(is_file)
        
        # Set default filename
        extensions = ['', '.json', '.csv', '.md']
        if is_file:
            self.output_path.setText(f"telegram_export{extensions[index]}")
    
    def browse_output(self):
        """Open file browser for output path"""
        index = self.export_format.currentIndex()
        filters = {
            1: "JSON Files (*.json)",
            2: "CSV Files (*.csv)",
            3: "Markdown Files (*.md)"
        }
        
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Export As",
            self.output_path.text(),
            filters.get(index, "All Files (*)")
        )
        
        if path:
            self.output_path.setText(path)
    
    def load_config(self):
        """Load saved configuration"""
        config = Config.load()
        
        self.tg_api_id.setText(config.get('telegram_api_id', ''))
        self.tg_api_hash.setText(config.get('telegram_api_hash', ''))
        self.tg_phone.setText(config.get('telegram_phone', ''))
        self.notion_token.setText(config.get('notion_token', ''))
        self.notion_db_id.setText(config.get('notion_database_id', ''))
        
        self.log("📂 Configuration loaded")
    
    def save_config(self):
        """Save current configuration"""
        config = {
            'telegram_api_id': self.tg_api_id.text(),
            'telegram_api_hash': self.tg_api_hash.text(),
            'telegram_phone': self.tg_phone.text(),
            'notion_token': self.notion_token.text(),
            'notion_database_id': self.notion_db_id.text()
        }
        
        Config.save(config)
        self.log("💾 Configuration saved")
        self.statusBar().showMessage("Configuration saved", 3000)
    
    def get_config(self):
        """Get current configuration"""
        return {
            'telegram_api_id': self.tg_api_id.text(),
            'telegram_api_hash': self.tg_api_hash.text(),
            'telegram_phone': self.tg_phone.text(),
            'notion_token': self.notion_token.text(),
            'notion_database_id': self.notion_db_id.text()
        }
    
    def get_filters(self):
        """Get current filter settings"""
        filters = {}
        
        # Word filter
        word = self.filter_word.text().strip()
        if word:
            filters['word'] = word
        
        # Hashtag filter
        hashtags = self.filter_hashtags.text().strip()
        if hashtags:
            filters['hashtags'] = [t.strip().lstrip('#') for t in hashtags.split(',')]
        
        # Type filter
        selected_types = [t for t, cb in self.type_checkboxes.items() if cb.isChecked()]
        if len(selected_types) < len(self.type_checkboxes):
            filters['types'] = selected_types
        
        # Date filter
        if self.date_enabled.isChecked():
            filters['date_from'] = datetime(
                self.date_from.date().year(),
                self.date_from.date().month(),
                self.date_from.date().day()
            )
            filters['date_to'] = datetime(
                self.date_to.date().year(),
                self.date_to.date().month(),
                self.date_to.date().day(),
                23, 59, 59
            )
        
        # Other filters
        if self.filter_has_url.isChecked():
            filters['has_url'] = True
        if self.filter_has_media.isChecked():
            filters['has_media'] = True
        if self.filter_no_media.isChecked():
            filters['no_media'] = True
        
        limit = self.filter_limit.value()
        if limit > 0:
            filters['limit'] = limit
        
        return filters
    
    def get_export_settings(self):
        """Get export settings"""
        formats = ['notion', 'json', 'csv', 'markdown']
        return {
            'format': formats[self.export_format.currentIndex()],
            'output_path': self.output_path.text()
        }
    
    def validate_config(self):
        """Validate configuration before export"""
        config = self.get_config()
        export_settings = self.get_export_settings()
        
        # Check Telegram credentials
        if not config['telegram_api_id'] or not config['telegram_api_hash']:
            QMessageBox.warning(self, "Missing Credentials",
                "Please enter your Telegram API ID and Hash in the Credentials tab.")
            return False
        if not config.get('telegram_phone'):
            QMessageBox.warning(self, "Missing Phone",
                "Please enter the phone number used for this Telegram account (e.g., +380...).")
            return False
        
        # Check Notion credentials (if exporting to Notion)
        if export_settings['format'] == 'notion':
            if not config['notion_token'] or not config['notion_database_id']:
                QMessageBox.warning(self, "Missing Credentials",
                    "Please enter your Notion Token and Database ID in the Credentials tab.")
                return False
        
        # Check output path (if exporting to file)
        if export_settings['format'] != 'notion':
            if not export_settings['output_path']:
                QMessageBox.warning(self, "Missing Output Path",
                    "Please specify an output file path in the Export tab.")
                return False
        
        return True
    
    def log(self, message):
        """Add message to log"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.append(f"[{timestamp}] {message}")
    
    def start_export(self):
        """Start the export process"""
        if not self.validate_config():
            return
        
        # Clear log
        self.log_text.clear()
        self.log("🚀 Starting export...")
        
        # Get settings
        config = self.get_config()
        filters = self.get_filters()
        export_settings = self.get_export_settings()
        
        # Log filters
        if filters:
            self.log(f"🔍 Active filters: {', '.join(filters.keys())}")
        
        # Create and start worker
        self.worker = ExportWorker(config, filters, export_settings)
        self.worker.progress.connect(self.on_progress)
        self.worker.log.connect(self.log)
        self.worker.finished.connect(self.on_finished)
        self.worker.error.connect(self.on_error)
        self.worker.request_code.connect(self.on_request_code)
        self.worker.request_password.connect(self.on_request_password)
        
        # Update UI
        self.start_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.progress_bar.setValue(0)
        
        self.worker.start()
    
    def cancel_export(self):
        """Cancel the export process"""
        if self.worker:
            self.worker.cancel()
            self.log("⏳ Cancelling...")
    
    def on_progress(self, current, total, message):
        """Handle progress update"""
        if total > 0:
            self.progress_bar.setMaximum(total)
            self.progress_bar.setValue(current)
        self.progress_label.setText(message)
    
    def on_finished(self, success, failed):
        """Handle export completion"""
        self.log(f"✨ Export completed! Success: {success}, Failed: {failed}")
        self.progress_label.setText(f"Completed: {success} exported, {failed} failed")
        self.statusBar().showMessage(f"Export completed: {success} messages", 5000)
        
        # Reset UI
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.progress_bar.setValue(self.progress_bar.maximum())
        
        # Show completion message
        QMessageBox.information(self, "Export Complete",
            f"Export finished!\n\n"
            f"✅ Successfully exported: {success}\n"
            f"❌ Failed: {failed}")
    
    def on_error(self, message):
        """Handle export error"""
        self.log(f"❌ Error: {message}")
        self.statusBar().showMessage("Export failed", 5000)
        
        # Reset UI
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        
        QMessageBox.critical(self, "Export Error", message)
    
    def on_request_code(self, phone: str):
        """Handle request for confirmation code"""
        code, ok = QInputDialog.getText(
            self,
            "Telegram Confirmation Code",
            f"Enter the confirmation code sent to {phone}:",
            QLineEdit.EchoMode.Normal
        )
        if ok and code:
            self.worker.set_auth_code(code)
        else:
            self.worker.cancel()
    
    def on_request_password(self, hint: str):
        """Handle request for 2FA password"""
        hint_text = f"\nHint: {hint}" if hint else ""
        password, ok = QInputDialog.getText(
            self,
            "Two-Factor Authentication",
            f"Enter your 2FA password:{hint_text}",
            QLineEdit.EchoMode.Password
        )
        if ok and password:
            self.worker.set_auth_password(password)
        else:
            self.worker.cancel()


def get_icon_path():
    """Get the path to the application icon (prefers .icns on macOS)"""
    is_macos = sys.platform == "darwin"
    preferred_ext = ".icns" if is_macos else ".ico"
    fallback_ext = ".ico" if is_macos else ".icns"
    
    def candidates(ext):
        paths = [
            Path(__file__).parent / f"icon{ext}",
            Path(sys.executable).parent / f"icon{ext}",
            Path(f"icon{ext}"),
        ]
        if getattr(sys, 'frozen', False):
            paths.insert(0, Path(sys._MEIPASS) / f"icon{ext}")
        return paths
    
    for ext in (preferred_ext, fallback_ext):
        for path in candidates(ext):
            if path.exists():
                return str(path)
    return None


def main():
    """Application entry point"""
    app = QApplication(sys.argv)
    
    # Set application style
    app.setStyle("Fusion")
    
    # Set application icon
    icon_path = get_icon_path()
    if icon_path:
        app.setWindowIcon(QIcon(icon_path))
    
    # Create and show main window
    window = MainWindow()
    
    # Set window icon
    if icon_path:
        window.setWindowIcon(QIcon(icon_path))
    
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
