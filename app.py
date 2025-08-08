import os
import json
import sqlite3
from datetime import datetime
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException
from dotenv import load_dotenv
from utils.rcs_payload import create_rcs_payload, create_sms_fallback

# Load environment variables
load_dotenv()

app = Flask(__name__)
CORS(app)  # Enable CORS for iframe embedding

# Twilio Configuration
TWILIO_ACCOUNT_SID = os.getenv('TWILIO_ACCOUNT_SID')
TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN')
TWILIO_RCS_AGENT_ID = os.getenv('TWILIO_RCS_AGENT_ID')
TWILIO_PHONE_NUMBER = os.getenv('TWILIO_PHONE_NUMBER')

# Initialize Twilio client
twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# Database setup
DATABASE = 'messages.db'

def init_db():
    """Initialize SQLite database"""
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            recipient TEXT NOT NULL,
            message TEXT NOT NULL,
            image_url TEXT,
            quick_replies TEXT,
            status TEXT,
            message_type TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            sid TEXT
        )
    ''')
    conn.commit()
    conn.close()

# Initialize database on startup
init_db()

def log_message(recipient, message, image_url, quick_replies, status, message_type, sid):
    """Log message to database"""
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute('''
        INSERT INTO messages (recipient, message, image_url, quick_replies, status, message_type, sid)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (recipient, message, image_url, json.dumps(quick_replies) if quick_replies else None, 
          status, message_type, sid))
    conn.commit()
    conn.close()

@app.route('/')
def index():
    """Serve the main RCS client interface"""
    return render_template('rcs.html')

@app.route('/send-rcs', methods=['POST'])
def send_rcs():
    try:
        data = request.json
        recipient_phone = data.get('phone')
        message_body = data.get('message')
        image_url = data.get('image_url')
        quick_replies = data.get('quick_replies', [])
        
        if not recipient_phone or not message_body:
            return jsonify({'error': 'Phone and message are required'}), 400
        
        if not recipient_phone.startswith('+'):
            recipient_phone = '+' + recipient_phone
        
        try:
            # For RCS, use Messaging Service SID, not phone number
            messaging_service_sid = os.getenv('TWILIO_MESSAGING_SERVICE_SID')
            
            # Build the message parameters
            message_params = {
                'messaging_service_sid': messaging_service_sid,  # Use this instead of 'from_'
                'to': recipient_phone,
                'body': message_body
            }
            
            # Add media if provided
            if image_url:
                message_params['media_url'] = [image_url]
            
            # Add RCS-specific parameters if quick replies exist
            if quick_replies:
                # Format quick replies for RCS
                rcs_suggestions = []
                for reply in quick_replies[:11]:
                    rcs_suggestions.append({
                        "type": "reply",
                        "text": reply,
                        "postbackData": reply
                    })
                message_params['persistent_action'] = rcs_suggestions
            
            # Send the message
            message = twilio_client.messages.create(**message_params)
            
            # Log successful message
            log_message(
                recipient_phone, message_body, image_url, quick_replies,
                'sent', 'RCS', message.sid
            )
            
            return jsonify({
                'success': True,
                'message_type': 'RCS',
                'sid': message.sid,
                'status': 'sent'
            }), 200
            
        except (TwilioRestException, Exception) as rcs_error:
            print(f"RCS failed, falling back to SMS: {str(rcs_error)}")
            
            # Fallback to SMS
            try:
                sms_body = create_sms_fallback(message_body, quick_replies)
                message = twilio_client.messages.create(
                    body=sms_body,
                    from_=TWILIO_PHONE_NUMBER,
                    to=recipient_phone,
                    media_url=[image_url] if image_url else None
                )
                
                # Log successful SMS fallback
                log_message(
                    recipient_phone, sms_body, image_url, quick_replies,
                    'sent', 'SMS', message.sid
                )
                
                return jsonify({
                    'success': True,
                    'message_type': 'SMS',
                    'sid': message.sid,
                    'status': 'sent',
                    'note': 'Sent as SMS (RCS unavailable)'
                }), 200
                
            except Exception as sms_error:
                return jsonify({
                    'error': f'Failed to send message: {str(sms_error)}'
                }), 500
                
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/messages', methods=['GET'])
def get_messages():
    """Get message history"""
    try:
        limit = request.args.get('limit', 50, type=int)
        conn = sqlite3.connect(DATABASE)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute('''
            SELECT * FROM messages 
            ORDER BY timestamp DESC 
            LIMIT ?
        ''', (limit,))
        
        messages = []
        for row in c.fetchall():
            msg = dict(row)
            if msg['quick_replies']:
                msg['quick_replies'] = json.loads(msg['quick_replies'])
            messages.append(msg)
        
        conn.close()
        return jsonify(messages), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint for monitoring"""
    return jsonify({'status': 'healthy', 'service': 'RCS Assistant'}), 200

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
