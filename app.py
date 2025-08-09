import os
import json
import sqlite3
from datetime import datetime
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = Flask(__name__)
CORS(app)  # Enable CORS for iframe embedding

# Twilio Configuration
TWILIO_ACCOUNT_SID = os.getenv('TWILIO_ACCOUNT_SID')
TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN')
TWILIO_MESSAGING_SERVICE_SID = os.getenv('TWILIO_MESSAGING_SERVICE_SID')
TWILIO_PHONE_NUMBER = os.getenv('TWILIO_PHONE_NUMBER', '+18886103810')

# RCS Configuration
RCS_APPOINTMENT_TEMPLATE_SID = 'HX73731cf6e6a059ba71d48a356ad3db40'

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
            variables TEXT,
            template_used TEXT,
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

def log_message(recipient, message, image_url=None, quick_replies=None, variables=None, status='sent', message_type='SMS', sid=None, template_used=None):
    """Log message to database"""
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute('''
        INSERT INTO messages (recipient, message, image_url, quick_replies, variables, template_used, status, message_type, sid)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        recipient, 
        message, 
        image_url, 
        json.dumps(quick_replies) if quick_replies else None, 
        json.dumps(variables) if variables else None,
        template_used,
        status, 
        message_type, 
        sid
    ))
    conn.commit()
    conn.close()

@app.route('/')
def index():
    """Serve the main RCS client interface"""
    return render_template('rcs.html')

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint for monitoring"""
    return jsonify({
        'status': 'healthy', 
        'service': 'RCS Assistant',
        'twilio_configured': bool(TWILIO_ACCOUNT_SID),
        'messaging_service': bool(TWILIO_MESSAGING_SERVICE_SID)
    }), 200

@app.route('/send-rcs', methods=['POST'])
def send_rcs():
    """Send RCS message with fallback to SMS"""
    try:
        data = request.json
        print(f"Received request data: {data}")
        
        recipient_phone = data.get('phone')
        custom_message = data.get('message')
        image_url = data.get('image_url')
        quick_replies = data.get('quick_replies', [])
        
        # Template variables
        customer_name = data.get('customer_name', 'Customer')
        appointment_date = data.get('date', 'tomorrow')
        appointment_time = data.get('time', '2:00 PM')
        
        # Validate required fields
        if not recipient_phone:
            return jsonify({'success': False, 'error': 'Phone number is required'}), 400
        
        # Clean phone number (add + if not present)
        if not recipient_phone.startswith('+'):
            recipient_phone = '+' + recipient_phone
        
        # Check if messaging service is configured
        if not TWILIO_MESSAGING_SERVICE_SID:
            print("ERROR: No messaging service configured")
            return jsonify({
                'success': False,
                'error': 'Messaging service not configured. Please set TWILIO_MESSAGING_SERVICE_SID.'
            }), 500
        
        try:
            # If custom message provided, send as regular SMS/MMS
            if custom_message:
                print(f"Sending custom message to {recipient_phone}")
                
                # Create message parameters
                message_params = {
                    'messaging_service_sid': TWILIO_MESSAGING_SERVICE_SID,
                    'to': recipient_phone,
                    'body': custom_message
                }
                
                # Add image if provided
                if image_url:
                    message_params['media_url'] = [image_url]
                
                message = twilio_client.messages.create(**message_params)
                
                # Log the message
                log_message(
                    recipient_phone, custom_message, image_url, quick_replies,
                    None, 'sent', 'SMS', message.sid, None
                )
                
                return jsonify({
                    'success': True,
                    'message_sid': message.sid,
                    'sid': message.sid,
                    'status': 'sent',
                    'message_type': 'SMS',
                    'note': 'Custom message sent'
                }), 200
            
            else:
                # Use RCS template
                print(f"Sending RCS template to {recipient_phone}")
                print(f"Template SID: {RCS_APPOINTMENT_TEMPLATE_SID}")
                
                message = twilio_client.messages.create(
                    messaging_service_sid=TWILIO_MESSAGING_SERVICE_SID,
                    to=recipient_phone,
                    content_sid=RCS_APPOINTMENT_TEMPLATE_SID,
                    content_variables=json.dumps({
                        "1": customer_name,
                        "2": appointment_date,
                        "3": appointment_time
                    })
                )
                
                # Log the message
                variables = {
                    'customer_name': customer_name,
                    'date': appointment_date,
                    'time': appointment_time
                }
                
                log_message(
                    recipient_phone,
                    f"Appointment reminder for {customer_name} on {appointment_date} at {appointment_time}",
                    image_url, quick_replies, variables,
                    'sent', 'RCS', message.sid, RCS_APPOINTMENT_TEMPLATE_SID
                )
                
                return jsonify({
                    'success': True,
                    'message_sid': message.sid,
                    'sid': message.sid,
                    'status': 'sent',
                    'message_type': 'RCS',
                    'template_used': True
                }), 200
            
        except TwilioRestException as rcs_error:
            print(f"RCS/Template failed: {str(rcs_error)}")
            error_msg = str(rcs_error)
            
            # Check for specific errors
            if "21610" in error_msg or "not found" in error_msg.lower():
                # Content template not found or not available
                print("Template not found, falling back to SMS")
            elif "21211" in error_msg or "sender" in error_msg.lower():
                # Invalid 'From' Phone Number
                print("Sender issue, check messaging service configuration")
            
            # Fallback to SMS
            try:
                print(f"Attempting SMS fallback to {recipient_phone}")
                
                if custom_message:
                    sms_body = custom_message
                else:
                    sms_body = f"Hi {customer_name}! Appointment on {appointment_date} at {appointment_time}.\n\nReply:\n1 - Confirm\n2 - Reschedule\n3 - Call Us"
                
                message = twilio_client.messages.create(
                    messaging_service_sid=TWILIO_MESSAGING_SERVICE_SID,
                    to=recipient_phone,
                    body=sms_body
                )
                
                # Log successful SMS fallback
                log_message(
                    recipient_phone, sms_body, None, None, None,
                    'sent', 'SMS', message.sid, None
                )
                
                return jsonify({
                    'success': True,
                    'message_sid': message.sid,
                    'sid': message.sid,
                    'status': 'sent',
                    'message_type': 'SMS',
                    'note': 'Sent as SMS (Template unavailable)'
                }), 200
                
            except Exception as sms_error:
                print(f"SMS fallback also failed: {str(sms_error)}")
                return jsonify({
                    'success': False,
                    'error': f'Failed to send message: {str(sms_error)}'
                }), 500
                
    except Exception as e:
        print(f"Unexpected error in send_rcs: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

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
            # Parse JSON fields
            for field in ['quick_replies', 'variables']:
                if msg.get(field):
                    try:
                        msg[field] = json.loads(msg[field])
                    except:
                        pass
            messages.append(msg)
        
        conn.close()
        return jsonify(messages), 200
        
    except Exception as e:
        print(f"Error in get_messages: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/test-simple', methods=['POST'])
def test_simple():
    """Simple test endpoint for debugging"""
    try:
        data = request.json
        phone = data.get('phone', '+16566001400')
        
        if not phone.startswith('+'):
            phone = '+' + phone
        
        # Send simple SMS
        message = twilio_client.messages.create(
            messaging_service_sid=TWILIO_MESSAGING_SERVICE_SID,
            to=phone,
            body="Test message from RinglyPro RCS System. If you see this, messaging works!"
        )
        
        return jsonify({
            'success': True,
            'message_sid': message.sid,
            'message_type': 'SMS'
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/rcs-webhook', methods=['POST'])
def handle_rcs_webhook():
    """Handle incoming RCS quick reply responses"""
    try:
        # Get the webhook data
        message_sid = request.form.get('MessageSid')
        from_number = request.form.get('From')
        button_payload = request.form.get('ButtonPayload')
        body = request.form.get('Body')
        
        print(f"Webhook received - From: {from_number}, Button: {button_payload}, Body: {body}")
        
        # Handle different quick reply actions
        response_text = ""
        if button_payload == 'confirm' or body == '1':
            response_text = "✅ Great! Your appointment is confirmed. We'll see you soon!"
        elif button_payload == 'reschedule' or body == '2':
            response_text = "📅 To reschedule, please call us at 1-888-610-3810 or reply with your preferred date and time."
        elif button_payload == 'call_us' or body == '3':
            response_text = "📞 Please call us at 1-888-610-3810. We're available Mon-Fri 9AM-5PM."
        else:
            response_text = "Thank you for your response. How can we help you today?"
        
        # Send response
        if response_text:
            twilio_client.messages.create(
                messaging_service_sid=TWILIO_MESSAGING_SERVICE_SID,
                to=from_number,
                body=response_text
            )
        
        return '', 200
        
    except Exception as e:
        print(f"Webhook error: {str(e)}")
        return '', 200

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    print(f"Starting RCS Assistant on port {port}")
    print(f"Messaging Service SID: {TWILIO_MESSAGING_SERVICE_SID}")
    print(f"Template SID: {RCS_APPOINTMENT_TEMPLATE_SID}")
    app.run(host='0.0.0.0', port=port, debug=False)
