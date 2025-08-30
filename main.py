# main.py - Complete Production-Ready Calendar Sync Solution v4.0 - Handles Recurring Events
import os
import sqlite3
import hashlib
import json
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
from googleapiclient.discovery import build
from google.oauth2 import service_account
from google.cloud import storage
import time
import logging
import tempfile
import re
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass, asdict, field
from enum import Enum
import traceback

# Configure detailed logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s:%(name)s:%(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Environment variables
SHEET_ID = os.environ.get('SHEET_ID')
CALENDAR_ID = os.environ.get('CALENDAR_ID', 'primary')
BUCKET_NAME = os.environ.get('BUCKET_NAME', 'calendar-sync-db')
DB_FILE = 'calendar_sync.db'

# Configuration
class Config:
    SHEET_TAB = 'main_import'
    SHEET_RANGE = f'{SHEET_TAB}!A:I'
    BATCH_SIZE = 10
    RATE_LIMIT_DELAY = 0.5
    MAX_DESCRIPTION_LENGTH = 8000
    TIMEZONE = 'Africa/Cairo'
    MAX_RETRIES = 3
    RETRY_DELAY = 1.0
    
class EventType(Enum):
    DEFAULT = '1'
    FOCUS_TIME = '2'
    OUT_OF_OFFICE = '4'
    WORKING_LOCATION = '5'

@dataclass
class ParsedDateTime:
    """Parsed datetime with validation status"""
    datetime: Optional[datetime]
    is_valid: bool
    error_message: str = ""
    original_string: str = ""

@dataclass
class CalendarEvent:
    """Data class for calendar events with validation"""
    sheet_id: str
    name: str
    start_time: datetime
    end_time: datetime
    description: str = ''
    event_type: str = 'DEFAULT'
    color: str = ''
    focus_time: bool = False
    row_number: int = 0
    unique_id: str = ''  # Composite unique ID for handling duplicates
    validation_errors: List[str] = field(default_factory=list)
    
    def __post_init__(self):
        """Generate unique ID after initialization"""
        if not self.unique_id:
            # Create unique ID combining sheet_id and start_time
            self.unique_id = f"{self.sheet_id}_{self.start_time.isoformat()}"
    
    def is_valid(self) -> bool:
        """Check if event is valid for syncing"""
        errors = []
        
        # Validate required fields
        if not self.name or self.name.strip() == '':
            errors.append("Event name is empty")
        
        if not self.start_time:
            errors.append("Start time is missing")
            
        if not self.end_time:
            errors.append("End time is missing")
            
        # Validate time logic
        if self.start_time and self.end_time:
            if self.end_time <= self.start_time:
                errors.append(f"End time ({self.end_time}) must be after start time ({self.start_time})")
        
        self.validation_errors = errors
        return len(errors) == 0
    
    def to_google_event(self) -> Dict:
        """Convert to Google Calendar event format"""
        event = {
            'summary': self.name.strip(),
            'start': {
                'dateTime': self.start_time.isoformat(),
                'timeZone': Config.TIMEZONE,
            },
            'end': {
                'dateTime': self.end_time.isoformat(),
                'timeZone': Config.TIMEZONE,
            }
        }
        
        # Add description if present
        if self.description:
            # Clean HTML from description
            clean_desc = re.sub(r'<[^>]+>', '', self.description)
            clean_desc = clean_desc.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
            clean_desc = clean_desc.replace('&nbsp;', ' ').replace('<br>', '\n')
            clean_desc = clean_desc.strip()
            if clean_desc:
                event['description'] = clean_desc[:Config.MAX_DESCRIPTION_LENGTH]
        
        # Set color based on event type
        color_map = {
            'DEFAULT': EventType.DEFAULT.value,
            'FOCUS_TIME': EventType.FOCUS_TIME.value,
            'OUT_OF_OFFICE': EventType.OUT_OF_OFFICE.value,
            'WORKING_LOCATION': EventType.WORKING_LOCATION.value,
        }
        
        # Map event type
        event_type = self.event_type.upper().replace(' ', '_') if self.event_type else 'DEFAULT'
        if event_type in color_map:
            event['colorId'] = color_map[event_type]
        elif self.color:
            # Try to use color value if it's valid (1-11)
            try:
                color_id = str(int(float(self.color)))
                if 1 <= int(color_id) <= 11:
                    event['colorId'] = color_id
            except (ValueError, TypeError):
                pass
                
        return event
    
    def content_hash(self) -> str:
        """Generate hash based on event content for duplicate detection"""
        # Use name + start + end for unique identification
        content = f"{self.name.strip().lower()}|{self.start_time.isoformat()}|{self.end_time.isoformat()}"
        return hashlib.sha256(content.encode()).hexdigest()
    
    def content_key(self) -> str:
        """Generate a key for duplicate detection in calendar"""
        return f"{self.name.strip().lower()}|{self.start_time.isoformat()}"

class DateTimeParser:
    """Robust datetime parser for various formats"""
    
    @staticmethod
    def parse(date_str: str) -> ParsedDateTime:
        """Parse datetime string with multiple format support"""
        if not date_str:
            return ParsedDateTime(None, False, "Empty date string", date_str)
        
        # Clean the string
        date_str = str(date_str).strip()
        original = date_str
        
        # List of formats to try
        formats = [
            '%m/%d/%Y, %I:%M:%S %p',     # 8/7/2025, 12:00:00 AM
            '%m/%d/%Y %I:%M:%S %p',      # 8/7/2025 12:00:00 AM  
            '%m/%d/%Y, %H:%M:%S',        # 8/7/2025, 13:00:00
            '%m/%d/%Y %H:%M:%S',         # 8/7/2025 13:00:00
            '%Y-%m-%d %H:%M:%S',         # 2025-08-30 13:00:00
            '%d/%m/%Y, %I:%M:%S %p',     # 30/8/2025, 12:00:00 AM
            '%d/%m/%Y %I:%M:%S %p',      # 30/8/2025 12:00:00 AM
        ]
        
        # Try each format
        for fmt in formats:
            try:
                dt = datetime.strptime(date_str, fmt)
                return ParsedDateTime(dt, True, "", original)
            except ValueError:
                continue
        
        # Try flexible parsing for variations
        try:
            # Remove comma if present
            date_str = date_str.replace(',', '')
            parts = date_str.split()
            
            if len(parts) >= 2:
                date_part = parts[0]
                time_part = parts[1]
                am_pm = parts[2].upper() if len(parts) > 2 else None
                
                # Parse date
                date_components = date_part.split('/')
                if len(date_components) == 3:
                    month = int(date_components[0])
                    day = int(date_components[1])
                    year = int(date_components[2])
                    
                    # Parse time
                    time_components = time_part.split(':')
                    if len(time_components) >= 2:
                        hour = int(time_components[0])
                        minute = int(time_components[1])
                        second = int(time_components[2]) if len(time_components) > 2 else 0
                        
                        # Adjust for AM/PM
                        if am_pm:
                            if am_pm == 'PM' and hour != 12:
                                hour += 12
                            elif am_pm == 'AM' and hour == 12:
                                hour = 0
                        
                        dt = datetime(year, month, day, hour, minute, second)
                        return ParsedDateTime(dt, True, "", original)
                        
        except (ValueError, IndexError, AttributeError) as e:
            pass
        
        return ParsedDateTime(None, False, f"Could not parse date: {original}", original)

class CalendarSyncService:
    """Main service class for calendar synchronization"""
    
    def __init__(self):
        self.sheet_id = SHEET_ID
        self.calendar_id = CALENDAR_ID
        self.bucket_name = BUCKET_NAME
        self.parser = DateTimeParser()
        self._init_services()
        self._init_database()
        
    def _init_services(self):
        """Initialize Google API services"""
        try:
            self.sheets_service = build('sheets', 'v4')
            self.calendar_service = build('calendar', 'v3')
            logger.info("Google services initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Google services: {e}")
            self.sheets_service = None
            self.calendar_service = None
            
        try:
            self.storage_client = storage.Client()
            self.bucket = self.storage_client.bucket(self.bucket_name)
            logger.info(f"Storage bucket {self.bucket_name} initialized")
        except Exception as e:
            logger.warning(f"Could not initialize storage: {e}")
            self.storage_client = None
            self.bucket = None
    
    def _init_database(self):
        """Initialize SQLite database with proper schema"""
        self.temp_dir = tempfile.gettempdir()
        self.db_path = os.path.join(self.temp_dir, DB_FILE)
        
        # Download existing database from GCS if available
        if self.bucket:
            try:
                blob = self.bucket.blob(DB_FILE)
                if blob.exists():
                    logger.info("Downloading existing database from GCS")
                    blob.download_to_filename(self.db_path)
            except Exception as e:
                logger.warning(f"Could not download database: {e}")
        
        self.conn = sqlite3.connect(self.db_path)
        self.cursor = self.conn.cursor()
        
        # Create tables with proper schema
        self._create_tables()
        
        self.conn.commit()
        logger.info("Database initialized and ready")
    
    def _create_tables(self):
        """Create or update database tables"""
        # Drop and recreate for clean schema that handles duplicates
        self.cursor.executescript('''
            -- Events tracking table (uses composite unique ID)
            CREATE TABLE IF NOT EXISTS synced_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sheet_event_id TEXT NOT NULL,
                unique_event_id TEXT NOT NULL,
                calendar_event_id TEXT NOT NULL,
                event_hash TEXT DEFAULT '',
                event_name TEXT DEFAULT '',
                start_time TEXT DEFAULT '',
                end_time TEXT DEFAULT '',
                event_data TEXT,
                last_synced TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                sync_status TEXT DEFAULT 'active',
                UNIQUE(unique_event_id),
                UNIQUE(calendar_event_id)
            );
            
            CREATE INDEX IF NOT EXISTS idx_sheet_id ON synced_events(sheet_event_id);
            CREATE INDEX IF NOT EXISTS idx_unique_id ON synced_events(unique_event_id);
            CREATE INDEX IF NOT EXISTS idx_calendar_id ON synced_events(calendar_event_id);
            CREATE INDEX IF NOT EXISTS idx_event_hash ON synced_events(event_hash);
            CREATE INDEX IF NOT EXISTS idx_event_name ON synced_events(event_name);
            
            -- Sync history
            CREATE TABLE IF NOT EXISTS sync_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sync_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                events_created INTEGER DEFAULT 0,
                events_updated INTEGER DEFAULT 0,
                events_skipped INTEGER DEFAULT 0,
                events_deleted INTEGER DEFAULT 0,
                errors INTEGER DEFAULT 0,
                duration_seconds REAL,
                trigger_source TEXT,
                status TEXT,
                error_details TEXT,
                total_processed INTEGER DEFAULT 0
            );
            
            -- Failed events tracking
            CREATE TABLE IF NOT EXISTS failed_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sheet_event_id TEXT,
                unique_event_id TEXT,
                event_name TEXT,
                error_message TEXT,
                row_number INTEGER,
                attempted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                retry_count INTEGER DEFAULT 0
            );
            
            -- Validation errors
            CREATE TABLE IF NOT EXISTS validation_errors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                row_number INTEGER,
                event_name TEXT,
                validation_errors TEXT,
                logged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            
            -- Duplicate events tracking
            CREATE TABLE IF NOT EXISTS duplicate_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sheet_event_id TEXT,
                occurrences INTEGER,
                event_name TEXT,
                first_occurrence TEXT,
                last_occurrence TEXT,
                logged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        ''')
    
    def save_database(self):
        """Save database to Google Cloud Storage"""
        if self.bucket:
            try:
                self.conn.commit()
                blob = self.bucket.blob(DB_FILE)
                blob.upload_from_filename(self.db_path)
                logger.info("Database saved to GCS")
            except Exception as e:
                logger.error(f"Failed to save database to GCS: {e}")
    
    def read_sheet_events(self) -> Tuple[List[CalendarEvent], List[Dict], Dict[str, int]]:
        """Read and parse events from Google Sheet with validation and duplicate detection"""
        valid_events = []
        invalid_events = []
        duplicate_tracking = {}  # Track duplicate Event IDs
        
        try:
            # Get data from sheet
            result = self.sheets_service.spreadsheets().values().get(
                spreadsheetId=self.sheet_id,
                range=Config.SHEET_RANGE
            ).execute()
            
            values = result.get('values', [])
            
            if not values or len(values) < 2:
                logger.warning("No data found in sheet")
                return [], [], {}
            
            headers = values[0]
            logger.info(f"Sheet has {len(values)-1} data rows")
            
            # Process each row
            for row_num, row in enumerate(values[1:], start=2):
                if not row or len(row) == 0:
                    continue
                
                # Map row data to headers
                event_data = {}
                for i, header in enumerate(headers):
                    event_data[header] = row[i] if i < len(row) else ''
                
                # Get Event ID
                event_id = event_data.get('Event ID', '')
                if not event_id:
                    invalid_events.append({
                        'row': row_num,
                        'name': event_data.get('Event Name', 'Unknown'),
                        'error': 'Missing Event ID'
                    })
                    continue
                
                # Track duplicates
                if event_id in duplicate_tracking:
                    duplicate_tracking[event_id] += 1
                else:
                    duplicate_tracking[event_id] = 1
                
                # Parse dates
                start_parsed = self.parser.parse(event_data.get('Start Date/Time', ''))
                end_parsed = self.parser.parse(event_data.get('End Date/Time', ''))
                
                # Check date validity
                if not start_parsed.is_valid or not end_parsed.is_valid:
                    error_msg = []
                    if not start_parsed.is_valid:
                        error_msg.append(f"Invalid start date: {start_parsed.error_message}")
                    if not end_parsed.is_valid:
                        error_msg.append(f"Invalid end date: {end_parsed.error_message}")
                    
                    invalid_events.append({
                        'row': row_num,
                        'name': event_data.get('Event Name', 'Unknown'),
                        'error': '; '.join(error_msg),
                        'start': event_data.get('Start Date/Time', ''),
                        'end': event_data.get('End Date/Time', '')
                    })
                    continue
                
                # Create event object
                event = CalendarEvent(
                    sheet_id=str(event_id),
                    name=str(event_data.get('Event Name', 'Untitled Event')),
                    start_time=start_parsed.datetime,
                    end_time=end_parsed.datetime,
                    description=str(event_data.get('Description', '')),
                    event_type=str(event_data.get('Event Type', 'DEFAULT')),
                    color=str(event_data.get('Color', '')),
                    focus_time=str(event_data.get('Focus Time', '')).lower() == 'yes',
                    row_number=row_num
                )
                
                # Validate event
                if event.is_valid():
                    valid_events.append(event)
                else:
                    invalid_events.append({
                        'row': row_num,
                        'name': event.name,
                        'error': '; '.join(event.validation_errors)
                    })
            
            # Log duplicate Event IDs
            duplicates = {k: v for k, v in duplicate_tracking.items() if v > 1}
            if duplicates:
                logger.warning(f"Found {len(duplicates)} Event IDs with multiple occurrences")
                for event_id, count in duplicates.items():
                    # Find event names for this ID
                    event_names = [e.name for e in valid_events if e.sheet_id == event_id]
                    if event_names:
                        self.cursor.execute('''
                            INSERT INTO duplicate_events 
                            (sheet_event_id, occurrences, event_name, first_occurrence, last_occurrence)
                            VALUES (?, ?, ?, ?, ?)
                        ''', (event_id, count, event_names[0], 
                              min([e.start_time.isoformat() for e in valid_events if e.sheet_id == event_id]),
                              max([e.start_time.isoformat() for e in valid_events if e.sheet_id == event_id])))
            
            logger.info(f"Parsed {len(valid_events)} valid events, {len(invalid_events)} invalid")
            logger.info(f"Found {len(duplicates)} Event IDs with duplicates")
            
            # Log validation errors
            for invalid in invalid_events:
                self.cursor.execute('''
                    INSERT INTO validation_errors (row_number, event_name, validation_errors)
                    VALUES (?, ?, ?)
                ''', (invalid['row'], invalid.get('name', 'Unknown'), invalid['error']))
            
            return valid_events, invalid_events, duplicate_tracking
            
        except Exception as e:
            logger.error(f"Failed to read sheet events: {e}")
            logger.error(traceback.format_exc())
            return [], [], {}
    
    def get_existing_calendar_events(self, time_min: datetime, time_max: datetime) -> Dict[str, Dict]:
        """Fetch existing events from calendar"""
        try:
            all_events = {}
            page_token = None
            
            while True:
                events_result = self.calendar_service.events().list(
                    calendarId=self.calendar_id,
                    timeMin=time_min.isoformat() + 'Z',
                    timeMax=time_max.isoformat() + 'Z',
                    singleEvents=True,
                    orderBy='startTime',
                    pageToken=page_token,
                    maxResults=250
                ).execute()
                
                events = events_result.get('items', [])
                
                for event in events:
                    if event.get('status') == 'cancelled':
                        continue
                    
                    # Create content key for matching
                    summary = event.get('summary', '').strip().lower()
                    start = event.get('start', {}).get('dateTime', '')
                    
                    if summary and start:
                        # Parse the start time to normalize it
                        try:
                            start_dt = datetime.fromisoformat(start.replace('Z', '+00:00'))
                            content_key = f"{summary}|{start_dt.isoformat()}"
                            all_events[content_key] = event
                        except:
                            content_key = f"{summary}|{start}"
                            all_events[content_key] = event
                
                page_token = events_result.get('nextPageToken')
                if not page_token:
                    break
            
            logger.info(f"Found {len(all_events)} existing events in calendar")
            return all_events
            
        except Exception as e:
            logger.error(f"Failed to fetch calendar events: {e}")
            return {}
    
    def create_event_with_retry(self, event: CalendarEvent, max_retries: int = 3) -> Optional[str]:
        """Create calendar event with retry logic"""
        for attempt in range(max_retries):
            try:
                result = self.calendar_service.events().insert(
                    calendarId=self.calendar_id,
                    body=event.to_google_event()
                ).execute()
                
                return result['id']
                
            except Exception as e:
                error_msg = str(e)
                logger.warning(f"Attempt {attempt + 1} failed for '{event.name}' at {event.start_time}: {error_msg}")
                
                if attempt < max_retries - 1:
                    time.sleep(Config.RETRY_DELAY * (attempt + 1))
                else:
                    logger.error(f"Failed to create event '{event.name}' after {max_retries} attempts")
                    raise
        
        return None
    
    def sync_events(self, trigger_source: str = 'manual') -> Dict:
        """Main sync logic with comprehensive error handling and duplicate support"""
        start_time = time.time()
        logger.info(f"=" * 60)
        logger.info(f"Starting sync triggered by: {trigger_source}")
        
        # Read and validate events
        sheet_events, invalid_events, duplicate_tracking = self.read_sheet_events()
        
        if not sheet_events:
            logger.warning("No valid events to sync")
            return {
                'status': 'error' if not invalid_events else 'partial',
                'message': 'No valid events in sheet',
                'invalid_events': len(invalid_events),
                'validation_errors': invalid_events[:10]
            }
        
        # Get date range
        all_dates = [e.start_time for e in sheet_events] + [e.end_time for e in sheet_events]
        time_min = min(all_dates) - timedelta(days=1)
        time_max = max(all_dates) + timedelta(days=1)
        
        # Get existing calendar events
        existing_calendar_events = self.get_existing_calendar_events(time_min, time_max)
        
        # Statistics
        created = updated = skipped = errors = 0
        failed_events = []
        processed_count = 0
        duplicate_count = sum(1 for v in duplicate_tracking.values() if v > 1)
        
        logger.info(f"Processing {len(sheet_events)} events ({duplicate_count} Event IDs have duplicates)")
        
        # Process each event
        for event in sheet_events:
            processed_count += 1
            
            if processed_count % 10 == 0:
                logger.info(f"Processing event {processed_count}/{len(sheet_events)}...")
            
            try:
                content_hash = event.content_hash()
                content_key = event.content_key()
                
                # Use unique_id instead of sheet_id for database operations
                self.cursor.execute('''
                    SELECT calendar_event_id, event_hash, event_name
                    FROM synced_events 
                    WHERE unique_event_id = ?
                ''', (event.unique_id,))
                
                db_record = self.cursor.fetchone()
                
                if db_record:
                    cal_id, stored_hash, stored_name = db_record
                    
                    # Verify event exists in calendar
                    try:
                        cal_event = self.calendar_service.events().get(
                            calendarId=self.calendar_id,
                            eventId=cal_id
                        ).execute()
                        
                        if cal_event.get('status') != 'cancelled':
                            # Event exists, check if needs update
                            if stored_hash == content_hash:
                                skipped += 1
                                logger.debug(f"Skipped unchanged: {event.name} at {event.start_time}")
                            else:
                                # Update event
                                self.calendar_service.events().update(
                                    calendarId=self.calendar_id,
                                    eventId=cal_id,
                                    body=event.to_google_event()
                                ).execute()
                                
                                # Update database
                                self.cursor.execute('''
                                    UPDATE synced_events 
                                    SET event_hash = ?, event_name = ?, 
                                        start_time = ?, end_time = ?, 
                                        last_synced = CURRENT_TIMESTAMP
                                    WHERE unique_event_id = ?
                                ''', (content_hash, event.name, 
                                     event.start_time.isoformat(), 
                                     event.end_time.isoformat(), event.unique_id))
                                
                                updated += 1
                                logger.info(f"Updated: {event.name} at {event.start_time}")
                            continue
                            
                    except Exception as e:
                        # Event doesn't exist in calendar, remove from DB
                        logger.info(f"Event '{stored_name}' not in calendar, will recreate")
                        self.cursor.execute('''
                            DELETE FROM synced_events WHERE unique_event_id = ?
                        ''', (event.unique_id,))
                
                # Check if similar event already exists in calendar
                if content_key in existing_calendar_events:
                    existing = existing_calendar_events[content_key]
                    
                    # Link to existing event
                    self.cursor.execute('''
                        INSERT OR REPLACE INTO synced_events 
                        (sheet_event_id, unique_event_id, calendar_event_id, event_hash, 
                         event_name, start_time, end_time)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    ''', (event.sheet_id, event.unique_id, existing['id'], content_hash,
                          event.name, event.start_time.isoformat(), 
                          event.end_time.isoformat()))
                    
                    skipped += 1
                    logger.info(f"Linked to existing: {event.name} at {event.start_time}")
                    continue
                
                # Create new event
                calendar_id = self.create_event_with_retry(event)
                
                if calendar_id:
                    # Store in database
                    self.cursor.execute('''
                        INSERT INTO synced_events 
                        (sheet_event_id, unique_event_id, calendar_event_id, event_hash, 
                         event_name, start_time, end_time)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    ''', (event.sheet_id, event.unique_id, calendar_id, content_hash,
                          event.name, event.start_time.isoformat(), 
                          event.end_time.isoformat()))
                    
                    created += 1
                    logger.info(f"Created: {event.name} at {event.start_time}")
                    
                    # Rate limiting
                    if created % Config.BATCH_SIZE == 0:
                        time.sleep(Config.RATE_LIMIT_DELAY)
                        self.conn.commit()  # Commit periodically
                
            except Exception as e:
                errors += 1
                error_msg = str(e)
                logger.error(f"Failed to sync row {event.row_number} '{event.name}' at {event.start_time}: {error_msg}")
                
                failed_events.append({
                    'row': event.row_number,
                    'name': event.name,
                    'start_time': event.start_time.isoformat(),
                    'error': error_msg
                })
                
                # Log to failed_events table
                self.cursor.execute('''
                    INSERT INTO failed_events 
                    (sheet_event_id, unique_event_id, event_name, error_message, row_number)
                    VALUES (?, ?, ?, ?, ?)
                ''', (event.sheet_id, event.unique_id, event.name, error_msg, event.row_number))
        
        # Final commit
        self.conn.commit()
        self.save_database()
        
        # Calculate duration
        duration = time.time() - start_time
        
        # Log sync results
        self.cursor.execute('''
            INSERT INTO sync_log 
            (events_created, events_updated, events_skipped, events_deleted, 
             errors, duration_seconds, trigger_source, status, error_details, total_processed)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (created, updated, skipped, 0, errors, duration, trigger_source, 
              'completed', json.dumps(failed_events[:10]) if failed_events else None,
              len(sheet_events)))
        
        self.conn.commit()
        self.save_database()
        
        # Prepare result
        result = {
            'status': 'success' if errors == 0 else 'partial',
            'created': created,
            'updated': updated,
            'skipped': skipped,
            'errors': errors,
            'total_processed': len(sheet_events),
            'invalid_events': len(invalid_events),
            'duplicate_event_ids': duplicate_count,
            'duration': round(duration, 2),
            'trigger_source': trigger_source
        }
        
        if failed_events:
            result['failed_events'] = failed_events[:5]
        
        if invalid_events:
            result['validation_errors'] = invalid_events[:5]
        
        logger.info(f"Sync completed: {json.dumps(result)}")
        logger.info(f"=" * 60)
        
        return result
    
    def delete_events_in_range(self, days_before: int = 7, days_after: int = 14) -> Dict:
        """Delete all events within specified date range"""
        now = datetime.now()
        time_min = now - timedelta(days=days_before)
        time_max = now + timedelta(days=days_after)
        
        logger.info(f"Deleting events from {time_min} to {time_max}")
        
        try:
            deleted_count = 0
            page_token = None
            
            while True:
                events_result = self.calendar_service.events().list(
                    calendarId=self.calendar_id,
                    timeMin=time_min.isoformat() + 'Z',
                    timeMax=time_max.isoformat() + 'Z',
                    singleEvents=True,
                    pageToken=page_token,
                    maxResults=100
                ).execute()
                
                events = events_result.get('items', [])
                
                for event in events:
                    if event.get('status') == 'cancelled':
                        continue
                    
                    try:
                        # Delete from calendar
                        self.calendar_service.events().delete(
                            calendarId=self.calendar_id,
                            eventId=event['id']
                        ).execute()
                        
                        # Remove from database
                        self.cursor.execute('''
                            DELETE FROM synced_events WHERE calendar_event_id = ?
                        ''', (event['id'],))
                        
                        deleted_count += 1
                        logger.info(f"Deleted: {event.get('summary', 'Unknown')}")
                        
                        # Rate limiting
                        if deleted_count % 10 == 0:
                            time.sleep(0.5)
                            self.conn.commit()
                            
                    except Exception as e:
                        logger.error(f"Failed to delete event {event['id']}: {e}")
                
                page_token = events_result.get('nextPageToken')
                if not page_token:
                    break
            
            self.conn.commit()
            self.save_database()
            
            return {
                'status': 'success',
                'deleted_count': deleted_count,
                'date_range': {
                    'from': time_min.isoformat(),
                    'to': time_max.isoformat()
                }
            }
            
        except Exception as e:
            logger.error(f"Failed to delete events: {e}")
            return {
                'status': 'error',
                'error': str(e)
            }
    
    def reset_sync_data(self, force: bool = False) -> Dict:
        """Reset all sync data"""
        try:
            if force:
                # Drop and recreate all tables
                logger.info("Force reset: dropping all tables")
                self.cursor.execute('DROP TABLE IF EXISTS synced_events')
                self.cursor.execute('DROP TABLE IF EXISTS failed_events')
                self.cursor.execute('DROP TABLE IF EXISTS sync_log')
                self.cursor.execute('DROP TABLE IF EXISTS validation_errors')
                self.cursor.execute('DROP TABLE IF EXISTS duplicate_events')
                
                # Recreate tables
                self._create_tables()
            else:
                # Just clear data
                self.cursor.execute('DELETE FROM synced_events')
                self.cursor.execute('DELETE FROM failed_events')
                self.cursor.execute('DELETE FROM sync_log')
                self.cursor.execute('DELETE FROM validation_errors')
                self.cursor.execute('DELETE FROM duplicate_events')
            
            self.conn.commit()
            self.save_database()
            
            return {
                'status': 'success',
                'message': 'All sync data cleared' + (' (force reset)' if force else '')
            }
        except Exception as e:
            logger.error(f"Reset error: {e}")
            return {
                'status': 'error',
                'error': str(e)
            }
    
    def get_stats(self) -> Dict:
        """Get comprehensive sync statistics"""
        stats = {}
        
        try:
            # Synced events
            self.cursor.execute('''
                SELECT COUNT(*) as total,
                       COUNT(DISTINCT sheet_event_id) as unique_sheet_ids,
                       COUNT(CASE WHEN sync_status = 'active' THEN 1 END) as active
                FROM synced_events
            ''')
            result = self.cursor.fetchone()
            stats['synced_events'] = {
                'total': result[0],
                'unique_sheet_ids': result[1],
                'active': result[2]
            }
            
            # Duplicate Event IDs
            self.cursor.execute('''
                SELECT COUNT(*) as total_duplicates,
                       SUM(occurrences) as total_occurrences
                FROM duplicate_events
            ''')
            result = self.cursor.fetchone()
            stats['duplicate_event_ids'] = {
                'unique_ids_with_duplicates': result[0] or 0,
                'total_occurrences': result[1] or 0
            }
            
            # Recent syncs
            self.cursor.execute('''
                SELECT sync_time, events_created, events_updated, events_skipped, 
                       errors, duration_seconds, trigger_source, total_processed
                FROM sync_log
                ORDER BY sync_time DESC
                LIMIT 10
            ''')
            stats['recent_syncs'] = self.cursor.fetchall()
            
            # Failed events
            self.cursor.execute('SELECT COUNT(*) FROM failed_events')
            stats['total_failed'] = self.cursor.fetchone()[0]
            
            # Recent failures
            self.cursor.execute('''
                SELECT event_name, error_message, row_number, attempted_at
                FROM failed_events
                ORDER BY attempted_at DESC
                LIMIT 10
            ''')
            stats['recent_failures'] = self.cursor.fetchall()
            
            # Validation errors
            self.cursor.execute('SELECT COUNT(*) FROM validation_errors')
            stats['total_validation_errors'] = self.cursor.fetchone()[0]
            
            # Recent validation errors
            self.cursor.execute('''
                SELECT row_number, event_name, validation_errors
                FROM validation_errors
                ORDER BY logged_at DESC
                LIMIT 10
            ''')
            stats['recent_validation_errors'] = self.cursor.fetchall()
            
        except Exception as e:
            logger.error(f"Error getting stats: {e}")
            stats['error'] = str(e)
        
        return stats
    
    def verify_sync(self) -> Dict:
        """Verify sync status between database and calendar"""
        try:
            # Get all active synced events
            self.cursor.execute('''
                SELECT unique_event_id, calendar_event_id, event_name, event_hash, start_time
                FROM synced_events
                WHERE sync_status = 'active'
            ''')
            
            db_events = self.cursor.fetchall()
            
            verified = []
            missing = []
            
            for unique_id, cal_id, name, event_hash, start_time in db_events:
                try:
                    event = self.calendar_service.events().get(
                        calendarId=self.calendar_id,
                        eventId=cal_id
                    ).execute()
                    
                    if event.get('status') != 'cancelled':
                        verified.append({
                            'name': name,
                            'unique_id': unique_id,
                            'calendar_id': cal_id,
                            'start_time': start_time
                        })
                    else:
                        missing.append({
                            'name': name,
                            'unique_id': unique_id,
                            'start_time': start_time,
                            'reason': 'cancelled'
                        })
                except Exception as e:
                    if '404' in str(e):
                        missing.append({
                            'name': name,
                            'unique_id': unique_id,
                            'start_time': start_time,
                            'reason': 'not_found'
                        })
                    else:
                        missing.append({
                            'name': name,
                            'unique_id': unique_id,
                            'start_time': start_time,
                            'reason': str(e)
                        })
            
            return {
                'total_in_database': len(db_events),
                'verified': len(verified),
                'missing': len(missing),
                'missing_events': missing[:20],
                'verified_sample': verified[:5]
            }
            
        except Exception as e:
            logger.error(f"Verify error: {e}")
            return {
                'status': 'error',
                'error': str(e)
            }
    
    def cleanup(self):
        """Clean up resources"""
        if hasattr(self, 'conn'):
            self.conn.close()

# Flask Routes
@app.route('/')
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'service': 'Calendar Sync Service v4.0',
        'sheet_id': SHEET_ID,
        'calendar_id': CALENDAR_ID,
        'bucket': BUCKET_NAME
    })

@app.route('/sync', methods=['POST', 'GET'])
def sync_calendar():
    """Trigger calendar sync"""
    try:
        trigger_source = request.args.get('source', 'manual')
        service = CalendarSyncService()
        result = service.sync_events(trigger_source)
        service.cleanup()
        return jsonify(result), 200
    except Exception as e:
        logger.error(f"Sync endpoint error: {e}")
        logger.error(traceback.format_exc())
        return jsonify({
            'status': 'error',
            'error': str(e)
        }), 500

@app.route('/delete-range', methods=['POST'])
def delete_range():
    """Delete events within date range"""
    try:
        data = request.get_json() or {}
        days_before = data.get('days_before', 7)
        days_after = data.get('days_after', 14)
        
        service = CalendarSyncService()
        result = service.delete_events_in_range(days_before, days_after)
        service.cleanup()
        return jsonify(result), 200
    except Exception as e:
        logger.error(f"Delete range error: {e}")
        return jsonify({
            'status': 'error',
            'error': str(e)
        }), 500

@app.route('/reset', methods=['POST'])
def reset_sync():
    """Reset all sync data"""
    try:
        data = request.get_json() or {}
        force = data.get('force', False)
        
        service = CalendarSyncService()
        result = service.reset_sync_data(force=force)
        service.cleanup()
        return jsonify(result), 200
    except Exception as e:
        logger.error(f"Reset error: {e}")
        return jsonify({
            'status': 'error',
            'error': str(e)
        }), 500

@app.route('/stats', methods=['GET'])
def get_stats():
    """Get sync statistics"""
    try:
        service = CalendarSyncService()
        stats = service.get_stats()
        service.cleanup()
        return jsonify(stats), 200
    except Exception as e:
        logger.error(f"Stats error: {e}")
        return jsonify({
            'status': 'error',
            'error': str(e)
        }), 500

@app.route('/verify', methods=['GET'])
def verify_sync():
    """Verify sync status"""
    try:
        service = CalendarSyncService()
        result = service.verify_sync()
        service.cleanup()
        return jsonify(result), 200
    except Exception as e:
        logger.error(f"Verify error: {e}")
        return jsonify({
            'status': 'error',
            'error': str(e)
        }), 500

@app.route('/validation-errors', methods=['GET'])
def get_validation_errors():
    """Get validation errors from last sync"""
    try:
        service = CalendarSyncService()
        
        service.cursor.execute('''
            SELECT row_number, event_name, validation_errors, logged_at
            FROM validation_errors
            ORDER BY logged_at DESC
            LIMIT 100
        ''')
        
        errors = service.cursor.fetchall()
        
        service.cleanup()
        
        return jsonify({
            'total_errors': len(errors),
            'errors': [
                {
                    'row': e[0],
                    'name': e[1],
                    'error': e[2],
                    'time': e[3]
                } for e in errors
            ]
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/duplicates', methods=['GET'])
def get_duplicate_events():
    """Get duplicate Event IDs report"""
    try:
        service = CalendarSyncService()
        
        service.cursor.execute('''
            SELECT sheet_event_id, occurrences, event_name, 
                   first_occurrence, last_occurrence
            FROM duplicate_events
            ORDER BY occurrences DESC
            LIMIT 100
        ''')
        
        duplicates = service.cursor.fetchall()
        
        service.cleanup()
        
        return jsonify({
            'total_duplicate_ids': len(duplicates),
            'duplicates': [
                {
                    'event_id': d[0],
                    'occurrences': d[1],
                    'name': d[2],
                    'first': d[3],
                    'last': d[4]
                } for d in duplicates
            ]
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 8080))
    app.run(debug=False, host='0.0.0.0', port=port)