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

# Twilio Configuration
TWILIO_ACCOUNT_SID = os.getenv('TWILIO_ACCOUNT_SID')
TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN')
TWILIO_MESSAGING_SERVICE_SID = os.getenv('TWILIO_MESSAGING_SERVICE_SID')
TWILIO_PHONE_NUMBER = os.getenv('TWILIO_PHONE_NUMBER', '+18886103810')

# RCS Configuration
RCS_APPOINTMENT_TEMPLATE_SID = 'HX73731cf6e6a059ba71d48a356ad3db40'
RCS_AGENT = 'rcs:crmautopilot_mq8sq68w_agent'

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
            'template_configured': bool(RCS_APPOINTMENT_TEMPLATE_SID),
            'phone_number': TWILIO_PHONE_NUMBER
        }
    }), 200

@app.route('/send-rcs', methods=['POST'])
def send_rcs():
    """Send message - Simplified version that actually works"""
    try:
        data = request.json
        print(f"=== SEND RCS REQUEST ===")
        print(f"Request data: {data}")
        
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
        
        print(f"Sending to: {recipient_phone}")
        print(f"Messaging Service SID: {TWILIO_MESSAGING_SERVICE_SID}")
        
        # Check if messaging service is configured
        if not TWILIO_MESSAGING_SERVICE_SID:
            print("ERROR: No messaging service configured")
            # Fallback to direct phone number
            if TWILIO_PHONE_NUMBER:
                message_body = custom_message or f"Hi {customer_name}! Appointment on {appointment_date} at {appointment_time}. Reply 1-Confirm, 2-Reschedule, 3-Call."
                
                message = twilio_client.messages.create(
                    from_=TWILIO_PHONE_NUMBER,
                    to=recipient_phone,
                    body=message_body
                )
                
                log_message(recipient_phone, message_body, None, None, None, 'sent', 'SMS', message.sid)
                
                return jsonify({
                    'success': True,
                    'message_sid': message.sid,
                    'sid': message.sid,
                    'status': 'sent',
                    'message_type': 'SMS',
                    'note': 'Sent via phone number directly'
                }), 200
            else:
                return jsonify({
                    'success': False,
                    'error': 'No messaging service or phone number configured'
                }), 500
        
        try:
            # Try to send with RCS template first
            if not custom_message:  # Use template if no custom message
                print(f"Attempting RCS with template: {RCS_APPOINTMENT_TEMPLATE_SID}")
                
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
                
                print(f"RCS template message sent: {message.sid}")
                
                # Check actual status
                sent_msg = twilio_client.messages(message.sid).fetch()
                actual_from = str(sent_msg.from_)
                is_rcs = 'rcs:' in actual_from.lower()
                
                log_message(
                    recipient_phone,
                    f"Appointment for {customer_name} on {appointment_date} at {appointment_time}",
                    image_url, None,
                    {'name': customer_name, 'date': appointment_date, 'time': appointment_time},
                    sent_msg.status,
                    'RCS' if is_rcs else 'SMS',
                    message.sid,
                    RCS_APPOINTMENT_TEMPLATE_SID
                )
                
                return jsonify({
                    'success': True,
                    'message_sid': message.sid,
                    'sid': message.sid,
                    'status': sent_msg.status,
                    'message_type': 'RCS' if is_rcs else 'SMS',
                    'from': actual_from,
                    'template_used': True
                }), 200
                
        except TwilioRestException as template_error:
            print(f"Template failed: {str(template_error)}")
            print("Falling back to regular SMS...")
        
        # Send as regular SMS
        message_body = custom_message or f"Hi {customer_name}! Appointment on {appointment_date} at {appointment_time}.\n\nReply:\n1 - Confirm\n2 - Reschedule\n3 - Call Us"
        
        print(f"Sending SMS: {message_body[:50]}...")
        
        message_params = {
            'messaging_service_sid': TWILIO_MESSAGING_SERVICE_SID,
            'to': recipient_phone,
            'body': message_body
        }
        
        # Add image if provided
        if image_url:
            message_params['media_url'] = [image_url]
        
        message = twilio_client.messages.create(**message_params)
        
        print(f"SMS sent successfully: {message.sid}")
        
        # Check actual status
        sent_msg = twilio_client.messages(message.sid).fetch()
        
        log_message(
            recipient_phone, message_body, image_url, None, None,
            sent_msg.status, 'SMS', message.sid
        )
        
        return jsonify({
            'success': True,
            'message_sid': message.sid,
            'sid': message.sid,
            'status': sent_msg.status,
            'message_type': 'SMS',
            'from': str(sent_msg.from_),
            'actual_status': sent_msg.status
        }), 200
        
    except Exception as e:
        print(f"ERROR in send_rcs: {str(e)}")
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/debug-message', methods=['POST'])
def debug_message():
    """Debug endpoint to see exactly what Twilio is doing"""
    try:
        data = request.json
        phone = data.get('phone', '+16566001400')
        
        if not phone.startswith('+'):
            phone = '+' + phone
        
        print(f"=== DEBUG MESSAGE TEST for {phone} ===")
        
        # Test 1: Simple SMS
        print("TEST 1: Sending simple SMS...")
        test1_result = {}
        try:
            sms_message = twilio_client.messages.create(
                messaging_service_sid=TWILIO_MESSAGING_SERVICE_SID,
                to=phone,
                body="Debug Test 1: Simple SMS from RinglyPro"
            )
            sms_details = twilio_client.messages(sms_message.sid).fetch()
            test1_result = {
                'success': True,
                'sid': sms_message.sid,
                'from': str(sms_details.from_),
                'status': sms_details.status,
                'price': str(sms_details.price) if sms_details.price else 'N/A',
                'error_code': sms_details.error_code,
                'error_message': sms_details.error_message
            }
            print(f"Test 1 Result: {test1_result}")
        except Exception as e:
            test1_result = {'success': False, 'error': str(e)}
            print(f"Test 1 Failed: {str(e)}")
        
        # Test 2: RCS with Template
        print("TEST 2: Sending RCS with template...")
        test2_result = {}
        try:
            rcs_message = twilio_client.messages.create(
                messaging_service_sid=TWILIO_MESSAGING_SERVICE_SID,
                to=phone,
                content_sid=RCS_APPOINTMENT_TEMPLATE_SID,
                content_variables=json.dumps({
                    "1": "Debug User",
                    "2": "Today",
                    "3": "Now"
                })
            )
            rcs_details = twilio_client.messages(rcs_message.sid).fetch()
            test2_result = {
                'success': True,
                'sid': rcs_message.sid,
                'from': str(rcs_details.from_),
                'status': rcs_details.status,
                'is_rcs': 'rcs:' in str(rcs_details.from_).lower(),
                'price': str(rcs_details.price) if rcs_details.price else 'N/A',
                'error_code': rcs_details.error_code,
                'error_message': rcs_details.error_message
            }
            print(f"Test 2 Result: {test2_result}")
        except Exception as e:
            test2_result = {'success': False, 'error': str(e)}
            print(f"Test 2 Failed: {str(e)}")
        
        # Test 3: Check Messaging Service Configuration
        print("TEST 3: Checking messaging service configuration...")
        test3_result = {}
        try:
            service = twilio_client.messaging.v1.services(TWILIO_MESSAGING_SERVICE_SID).fetch()
            
            # Get senders
            senders = []
            phone_numbers = twilio_client.messaging.v1.services(TWILIO_MESSAGING_SERVICE_SID).phone_numbers.list()
            for pn in phone_numbers:
                senders.append({
                    'type': 'phone',
                    'value': pn.phone_number
                })
            
            # Check for other sender types (this might fail but let's try)
            try:
                # This is a placeholder - Twilio's API for RCS senders might be different
                all_senders = twilio_client.messaging.v1.services(TWILIO_MESSAGING_SERVICE_SID).senders.list()
                for sender in all_senders:
                    if hasattr(sender, 'sender'):
                        senders.append({
                            'type': 'other',
                            'value': sender.sender
                        })
            except:
                pass  # RCS sender enumeration might not be available
            
            test3_result = {
                'success': True,
                'service_name': service.friendly_name,
                'service_sid': service.sid,
                'senders_count': len(senders),
                'senders': senders,
                'fallback_to_long_code': service.fallback_to_long_code
            }
            print(f"Test 3 Result: {test3_result}")
        except Exception as e:
            test3_result = {'success': False, 'error': str(e)}
            print(f"Test 3 Failed: {str(e)}")
        
        # Test 4: Direct phone number SMS
        print("TEST 4: Direct phone number SMS...")
        test4_result = {}
        try:
            if TWILIO_PHONE_NUMBER:
                direct_message = twilio_client.messages.create(
                    from_=TWILIO_PHONE_NUMBER,
                    to=phone,
                    body="Debug Test 4: Direct SMS from your Twilio number"
                )
                direct_details = twilio_client.messages(direct_message.sid).fetch()
                test4_result = {
                    'success': True,
                    'sid': direct_message.sid,
                    'from': str(direct_details.from_),
                    'status': direct_details.status
                }
                print(f"Test 4 Result: {test4_result}")
            else:
                test4_result = {'success': False, 'error': 'No TWILIO_PHONE_NUMBER configured'}
        except Exception as e:
            test4_result = {'success': False, 'error': str(e)}
            print(f"Test 4 Failed: {str(e)}")
        
        return jsonify({
            'debug_results': {
                'test1_simple_sms': test1_result,
                'test2_rcs_template': test2_result,
                'test3_service_config': test3_result,
                'test4_direct_sms': test4_result
            },
            'environment': {
                'has_account_sid': bool(TWILIO_ACCOUNT_SID),
                'has_auth_token': bool(TWILIO_AUTH_TOKEN),
                'has_messaging_service': bool(TWILIO_MESSAGING_SERVICE_SID),
                'messaging_service_sid': TWILIO_MESSAGING_SERVICE_SID[:10] + '...' if TWILIO_MESSAGING_SERVICE_SID else None,
                'has_template': bool(RCS_APPOINTMENT_TEMPLATE_SID),
                'template_sid': RCS_APPOINTMENT_TEMPLATE_SID,
                'phone_number': TWILIO_PHONE_NUMBER
            },
            'recommendations': [
                'Check Twilio Console message logs for delivery status',
                'Verify RCS agent is active in Messaging Service',
                'Ensure recipient phone supports RCS',
                'Try with different phone numbers'
            ]
        }), 200
        
    except Exception as e:
        print(f"Debug endpoint error: {str(e)}")
        traceback.print_exc()
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

@app.route('/test-simple', methods=['POST'])
def test_simple():
    """Simple test endpoint for basic SMS"""
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
            body=f"Test from RinglyPro at {timestamp}. If you see this, messaging works!"
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

@app.route('/test-sms-only', methods=['POST'])
def test_sms_only():
    """Force SMS only - no RCS attempt"""
    try:
        data = request.json
        phone = data.get('phone', '+16566001400')
        
        if not phone.startswith('+'):
            phone = '+' + phone
        
        # Force SMS by using direct phone number
        if not TWILIO_PHONE_NUMBER:
            return jsonify({
                'success': False,
                'error': 'No phone number configured'
            }), 500
        
        message = twilio_client.messages.create(
            from_=TWILIO_PHONE_NUMBER,
            to=phone,
            body=f"SMS Test from RinglyPro at {datetime.now().strftime('%H:%M:%S')}"
        )
        
        # Get full details
        sent_message = twilio_client.messages(message.sid).fetch()
        
        return jsonify({
            'success': True,
            'sid': message.sid,
            'from': str(sent_message.from_),
            'status': sent_message.status,
            'delivered': sent_message.status in ['delivered', 'sent']
        }), 200
        
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

@app.route('/rcs-webhook', methods=['POST'])
def handle_rcs_webhook():
    """Handle incoming RCS quick reply responses"""
    try:
        # Get the webhook data
        message_sid = request.form.get('MessageSid')
        from_number = request.form.get('From')
        button_payload = request.form.get('ButtonPayload')
        body = request.form.get('Body')
        
        print(f"=== WEBHOOK RECEIVED ===")
        print(f"From: {from_number}")
        print(f"Button: {button_payload}")
        print(f"Body: {body}")
        
        # Handle different quick reply actions
        response_text = ""
        if button_payload == 'confirm' or body == '1':
            response_text = "✅ Great! Your appointment is confirmed. We'll see you soon!"
        elif button_payload == 'reschedule' or body == '2':
            response_text = "📅 To reschedule, please call us at 1-888-610-3810 or reply with your preferred date and time."
        elif button_payload == 'call_us' or button_payload == 'call' or body == '3':
            response_text = "📞 Please call us at 1-888-610-3810. We're available Mon-Fri 9AM-5PM EST."
        else:
            response_text = "Thank you for your response. How can we help you today?"
        
        # Send response
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
    print(f"=== STARTING RINGLYPRO RCS ASSISTANT ===")
    print(f"Port: {port}")
    print(f"Account SID: {TWILIO_ACCOUNT_SID[:10]}..." if TWILIO_ACCOUNT_SID else "Account SID: NOT SET")
    print(f"Messaging Service: {TWILIO_MESSAGING_SERVICE_SID}" if TWILIO_MESSAGING_SERVICE_SID else "Messaging Service: NOT SET")
    print(f"Template SID: {RCS_APPOINTMENT_TEMPLATE_SID}")
    print(f"Phone Number: {TWILIO_PHONE_NUMBER}")
    print(f"=== SERVER STARTING ===")
    app.run(host='0.0.0.0', port=port, debug=False)
