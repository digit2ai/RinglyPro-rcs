import os
import json
import sqlite3
from datetime import datetime
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException
from dotenv import load_dotenv
import traceback

# Load environment variables
load_dotenv()

app = Flask(__name__)
CORS(app)  # Enable CORS for iframe embedding

# Twilio Configuration from Environment Variables
TWILIO_ACCOUNT_SID = os.getenv('TWILIO_ACCOUNT_SID')
TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN')
TWILIO_MESSAGING_SERVICE_SID = os.getenv('TWILIO_MESSAGING_SERVICE_SID')
TWILIO_PHONE_NUMBER = os.getenv('TWILIO_PHONE_NUMBER', '+18886103810')

# RCS Template Configuration from Environment Variable
RCS_CARD_TEMPLATE_SID = os.getenv('RCS_CARD_TEMPLATE_SID', 'HXdcfc307e1d9ec7c0b89c700bb5367247')

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
    try:
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
    except Exception as e:
        print(f"Error logging message: {str(e)}")

@app.route('/')
def index():
    """Serve the main RCS client interface"""
    return render_template('rcs.html')

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint for monitoring"""
    return jsonify({
        'status': 'healthy', 
        'service': 'RinglyPro RCS Assistant',
        'timestamp': datetime.now().isoformat(),
        'config': {
            'twilio_configured': bool(TWILIO_ACCOUNT_SID),
            'messaging_service': bool(TWILIO_MESSAGING_SERVICE_SID),
            'template_configured': bool(RCS_CARD_TEMPLATE_SID),
            'template_sid': RCS_CARD_TEMPLATE_SID[:10] + '...' if RCS_CARD_TEMPLATE_SID else None,
            'phone_number': TWILIO_PHONE_NUMBER
        }
    }), 200

@app.route('/send-rcs', methods=['POST'])
def send_rcs():
    """Send RCS message using Card template with SMS fallback"""
    try:
        data = request.json
        print(f"=== SEND RCS REQUEST ===")
        print(f"Request data: {data}")
        print(f"Using template: {RCS_CARD_TEMPLATE_SID}")
        
        recipient_phone = data.get('phone')
        
        if not recipient_phone:
            return jsonify({'success': False, 'error': 'Phone number is required'}), 400
            
        if not recipient_phone.startswith('+'):
            recipient_phone = '+' + recipient_phone
        
        # Get message variables
        customer_name = data.get('customer_name', 'Customer')
        appointment_date = data.get('date', 'tomorrow')
        appointment_time = data.get('time', '2:00 PM')
        custom_message = data.get('message')
        image_url = data.get('image_url')
        quick_replies = data.get('quick_replies', [])
        
        # Build the complete message
        if custom_message:
            complete_message = custom_message
        else:
            complete_message = f"Hi {customer_name}! Your appointment is scheduled for {appointment_date} at {appointment_time}. Please confirm your attendance. Reply 1 to Confirm, 2 to Reschedule, or 3 to Call us."
        
        print(f"Sending to: {recipient_phone}")
        print(f"Message: {complete_message[:100]}...")
        
        # Check if messaging service is configured
        if not TWILIO_MESSAGING_SERVICE_SID:
            print("ERROR: No messaging service configured")
            return jsonify({
                'success': False,
                'error': 'Messaging service not configured. Please check environment variables.'
            }), 500
        
        try:
            # Try sending with RCS Card template
            print(f"Attempting RCS with template: {RCS_CARD_TEMPLATE_SID}")
            
            message = twilio_client.messages.create(
                messaging_service_sid=TWILIO_MESSAGING_SERVICE_SID,
                to=recipient_phone,
                content_sid=RCS_CARD_TEMPLATE_SID,
                content_variables=json.dumps({
                    "1": complete_message  # Single variable containing entire message
                })
            )
            
            print(f"Message sent successfully: {message.sid}")
            
            # Check if it actually sent as RCS
            sent_msg = twilio_client.messages(message.sid).fetch()
            from_field = str(sent_msg.from_)
            is_rcs = 'rcs:' in from_field.lower()
            
            print(f"Sent from: {from_field}")
            print(f"Is RCS: {is_rcs}")
            
            # Log the message
            log_message(
                recipient_phone,
                complete_message,
                image_url,
                quick_replies if quick_replies else None,
                {'name': customer_name, 'date': appointment_date, 'time': appointment_time},
                sent_msg.status,
                'RCS' if is_rcs else 'SMS',
                message.sid,
                RCS_CARD_TEMPLATE_SID
            )
            
            return jsonify({
                'success': True,
                'message_sid': message.sid,
                'sid': message.sid,
                'status': sent_msg.status,
                'message_type': 'RCS' if is_rcs else 'SMS',
                'from': from_field,
                'template_used': 'rcs_card'
            }), 200
            
        except TwilioRestException as e:
            error_code = e.code if hasattr(e, 'code') else None
            error_msg = str(e)
            
            print(f"Template failed (Code {error_code}): {error_msg}")
            print("Falling back to regular SMS...")
            
            # Fallback to SMS
            message_params = {
                'messaging_service_sid': TWILIO_MESSAGING_SERVICE_SID,
                'to': recipient_phone,
                'body': complete_message
            }
            
            # Add image if provided (MMS)
            if image_url:
                message_params['media_url'] = [image_url]
            
            message = twilio_client.messages.create(**message_params)
            
            print(f"SMS sent successfully: {message.sid}")
            
            # Check actual status
            sent_msg = twilio_client.messages(message.sid).fetch()
            
            # Log the SMS
            log_message(
                recipient_phone,
                complete_message,
                image_url,
                quick_replies if quick_replies else None,
                {'name': customer_name, 'date': appointment_date, 'time': appointment_time},
                sent_msg.status,
                'SMS' if not image_url else 'MMS',
                message.sid,
                None
            )
            
            return jsonify({
                'success': True,
                'message_sid': message.sid,
                'sid': message.sid,
                'status': sent_msg.status,
                'message_type': 'SMS' if not image_url else 'MMS',
                'from': str(sent_msg.from_),
                'note': f'Sent as SMS/MMS (Template error: {error_code})'
            }), 200
            
    except Exception as e:
        print(f"ERROR in send_rcs: {str(e)}")
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/test-template', methods=['POST'])
def test_template():
    """Test endpoint for the RCS template"""
    try:
        data = request.json
        phone = data.get('phone', '+16566001400')
        
        if not phone.startswith('+'):
            phone = '+' + phone
        
        print(f"=== TESTING TEMPLATE ===")
        print(f"Template SID: {RCS_CARD_TEMPLATE_SID}")
        print(f"Phone: {phone}")
        
        # Simple test message
        test_message = f"Test at {datetime.now().strftime('%H:%M:%S')}: This is a test of the RCS card template. If you see this, the template is working!"
        
        message = twilio_client.messages.create(
            messaging_service_sid=TWILIO_MESSAGING_SERVICE_SID,
            to=phone,
            content_sid=RCS_CARD_TEMPLATE_SID,
            content_variables=json.dumps({
                "1": test_message
            })
        )
        
        # Check details
        sent_msg = twilio_client.messages(message.sid).fetch()
        from_field = str(sent_msg.from_)
        is_rcs = 'rcs:' in from_field.lower()
        
        return jsonify({
            'success': True,
            'message_sid': message.sid,
            'from': from_field,
            'status': sent_msg.status,
            'is_rcs': is_rcs,
            'message_type': 'RCS' if is_rcs else 'SMS',
            'template_sid': RCS_CARD_TEMPLATE_SID
        }), 200
        
    except TwilioRestException as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'error_code': e.code if hasattr(e, 'code') else None,
            'template_sid': RCS_CARD_TEMPLATE_SID,
            'suggestion': 'Check if template is properly configured for RCS in Twilio Console'
        }), 500
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/test-sms', methods=['POST'])
def test_sms():
    """Test simple SMS without template"""
    try:
        data = request.json
        phone = data.get('phone', '+16566001400')
        
        if not phone.startswith('+'):
            phone = '+' + phone
        
        timestamp = datetime.now().strftime('%H:%M:%S')
        
        # Send simple SMS
        message = twilio_client.messages.create(
            messaging_service_sid=TWILIO_MESSAGING_SERVICE_SID,
            to=phone,
            body=f"Simple SMS test from RinglyPro at {timestamp}. No template used."
        )
        
        # Get status
        sent_msg = twilio_client.messages(message.sid).fetch()
        
        return jsonify({
            'success': True,
            'message_sid': message.sid,
            'from': str(sent_msg.from_),
            'status': sent_msg.status,
            'message_type': 'SMS'
        }), 200
        
    except Exception as e:
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

@app.route('/check-message-status/<message_sid>', methods=['GET'])
def check_message_status(message_sid):
    """Check the actual status of a sent message"""
    try:
        message = twilio_client.messages(message_sid).fetch()
        
        return jsonify({
            'sid': message.sid,
            'from': str(message.from_),
            'to': str(message.to),
            'status': message.status,
            'direction': message.direction,
            'price': str(message.price) if message.price else 'N/A',
            'error_code': message.error_code,
            'error_message': message.error_message,
            'date_sent': str(message.date_sent),
            'date_created': str(message.date_created),
            'messaging_service_sid': message.messaging_service_sid,
            'num_segments': message.num_segments,
            'body': message.body[:100] + '...' if message.body else None
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/debug', methods=['POST'])
def debug_configuration():
    """Debug endpoint to check configuration"""
    try:
        data = request.json
        phone = data.get('phone', '+16566001400')
        
        if not phone.startswith('+'):
            phone = '+' + phone
        
        print("=== DEBUG CONFIGURATION ===")
        
        # Test 1: Configuration check
        config_check = {
            'account_sid_set': bool(TWILIO_ACCOUNT_SID),
            'auth_token_set': bool(TWILIO_AUTH_TOKEN),
            'messaging_service_set': bool(TWILIO_MESSAGING_SERVICE_SID),
            'messaging_service_sid': TWILIO_MESSAGING_SERVICE_SID[:10] + '...' if TWILIO_MESSAGING_SERVICE_SID else None,
            'template_set': bool(RCS_CARD_TEMPLATE_SID),
            'template_sid': RCS_CARD_TEMPLATE_SID,
            'phone_number': TWILIO_PHONE_NUMBER
        }
        
        # Test 2: Try simple SMS
        sms_test = {}
        try:
            msg = twilio_client.messages.create(
                messaging_service_sid=TWILIO_MESSAGING_SERVICE_SID,
                to=phone,
                body="Debug test: SMS working"
            )
            sms_test = {'success': True, 'sid': msg.sid}
        except Exception as e:
            sms_test = {'success': False, 'error': str(e)}
        
        # Test 3: Try template
        template_test = {}
        try:
            msg = twilio_client.messages.create(
                messaging_service_sid=TWILIO_MESSAGING_SERVICE_SID,
                to=phone,
                content_sid=RCS_CARD_TEMPLATE_SID,
                content_variables=json.dumps({"1": "Debug: Template test"})
            )
            sent_msg = twilio_client.messages(msg.sid).fetch()
            template_test = {
                'success': True,
                'sid': msg.sid,
                'from': str(sent_msg.from_),
                'is_rcs': 'rcs:' in str(sent_msg.from_).lower()
            }
        except Exception as e:
            template_test = {'success': False, 'error': str(e)}
        
        # Test 4: Check messaging service
        service_test = {}
        try:
            service = twilio_client.messaging.v1.services(TWILIO_MESSAGING_SERVICE_SID).fetch()
            service_test = {
                'success': True,
                'name': service.friendly_name,
                'sid': service.sid
            }
        except Exception as e:
            service_test = {'success': False, 'error': str(e)}
        
        return jsonify({
            'configuration': config_check,
            'sms_test': sms_test,
            'template_test': template_test,
            'service_test': service_test,
            'recommendations': [
                'Check Twilio Console for message delivery status',
                'Verify template is configured for RCS channel',
                'Ensure recipient device supports RCS'
            ]
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/rcs-webhook', methods=['POST'])
def handle_rcs_webhook():
    """Handle incoming RCS quick reply responses"""
    try:
        # Get webhook data
        message_sid = request.form.get('MessageSid')
        from_number = request.form.get('From')
        button_payload = request.form.get('ButtonPayload')
        body = request.form.get('Body')
        
        print(f"=== WEBHOOK RECEIVED ===")
        print(f"From: {from_number}")
        print(f"Body: {body}")
        print(f"Button: {button_payload}")
        
        # Determine response based on input
        response_text = ""
        
        if button_payload:
            # RCS button click
            if button_payload.lower() in ['confirm', 'confirmed']:
                response_text = "✅ Great! Your appointment is confirmed. We'll see you soon!"
            elif button_payload.lower() in ['reschedule', 'rescheduled']:
                response_text = "📅 To reschedule, please call us at 1-888-610-3810 or reply with your preferred date and time."
            elif button_payload.lower() in ['call', 'call_us', 'call us']:
                response_text = "📞 Please call us at 1-888-610-3810. We're available Mon-Fri 9AM-5PM EST."
        elif body:
            # SMS reply
            body_lower = body.strip().lower()
            if body_lower in ['1', 'confirm', 'yes']:
                response_text = "✅ Great! Your appointment is confirmed. We'll see you soon!"
            elif body_lower in ['2', 'reschedule']:
                response_text = "📅 To reschedule, please call us at 1-888-610-3810 or reply with your preferred date and time."
            elif body_lower in ['3', 'call']:
                response_text = "📞 Please call us at 1-888-610-3810. We're available Mon-Fri 9AM-5PM EST."
            else:
                response_text = f"Thank you for your message. For assistance, please call 1-888-610-3810."
        
        # Send response if we have one
        if response_text and from_number:
            twilio_client.messages.create(
                messaging_service_sid=TWILIO_MESSAGING_SERVICE_SID,
                to=from_number,
                body=response_text
            )
            print(f"Webhook response sent: {response_text[:50]}...")
        
        return '', 200
        
    except Exception as e:
        print(f"Webhook error: {str(e)}")
        traceback.print_exc()
        return '', 200

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    print("=" * 50)
    print("🚀 STARTING RINGLYPRO RCS ASSISTANT")
    print("=" * 50)
    print(f"Port: {port}")
    print(f"Account SID: {'✓ Set' if TWILIO_ACCOUNT_SID else '✗ Not Set'}")
    print(f"Auth Token: {'✓ Set' if TWILIO_AUTH_TOKEN else '✗ Not Set'}")
    print(f"Messaging Service: {TWILIO_MESSAGING_SERVICE_SID if TWILIO_MESSAGING_SERVICE_SID else '✗ Not Set'}")
    print(f"RCS Template: {RCS_CARD_TEMPLATE_SID if RCS_CARD_TEMPLATE_SID else '✗ Not Set'}")
    print(f"Phone Number: {TWILIO_PHONE_NUMBER}")
    print("=" * 50)
    app.run(host='0.0.0.0', port=port, debug=False)
