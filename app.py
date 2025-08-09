import os
import json
import sqlite3
from datetime import datetime
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
CORS(app)

# Twilio Configuration
TWILIO_ACCOUNT_SID = os.getenv('TWILIO_ACCOUNT_SID')
TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN')
TWILIO_MESSAGING_SERVICE_SID = os.getenv('TWILIO_MESSAGING_SERVICE_SID')
TWILIO_PHONE_NUMBER = '+18886103810'  # Your toll-free number

# Your RCS Configuration
RCS_AGENT = 'rcs:crmautopilot_mq8sq68w_agent'  # Your RCS agent
RCS_APPOINTMENT_TEMPLATE_SID = 'HX73731cf6e6a059ba71d48a356ad3db40'

twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# Initialize database
def init_db():
    conn = sqlite3.connect('messages.db')
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            recipient TEXT NOT NULL,
            message TEXT NOT NULL,
            template_used TEXT,
            variables TEXT,
            status TEXT,
            message_type TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            sid TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

@app.route('/')
def index():
    """Serve the main RCS client interface"""
    return render_template('rcs.html')

@app.route('/health')
def health():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'service': 'RinglyPro RCS Service',
        'rcs_agent': RCS_AGENT,
        'has_senders': True
    }), 200

@app.route('/send-rcs', methods=['POST'])
def send_rcs():
    """Send RCS message using your configured RCS agent"""
    try:
        data = request.json
        recipient_phone = data.get('phone')
        
        if not recipient_phone:
            return jsonify({'error': 'Phone number is required'}), 400
            
        if not recipient_phone.startswith('+'):
            recipient_phone = '+' + recipient_phone
        
        # Get variables for template
        customer_name = data.get('customer_name', data.get('name', 'Customer'))
        appointment_date = data.get('date', 'tomorrow')
        appointment_time = data.get('time', '2:00 PM')
        
        print(f"Sending RCS to {recipient_phone}")
        print(f"Using Messaging Service: {TWILIO_MESSAGING_SERVICE_SID}")
        print(f"Using Content Template: {RCS_APPOINTMENT_TEMPLATE_SID}")
        
        try:
            # Send RCS using Content Template and Messaging Service
            # The messaging service will automatically select the RCS agent
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
            
            print(f"Message sent: {message.sid}")
            print(f"Status: {message.status}")
            
            # Check if it actually sent as RCS
            sent_message = twilio_client.messages(message.sid).fetch()
            actual_from = sent_message.from_
            is_rcs = 'rcs:' in str(actual_from).lower()
            
            # Log the message
            conn = sqlite3.connect('messages.db')
            c = conn.cursor()
            c.execute('''
                INSERT INTO messages 
                (recipient, message, template_used, variables, status, message_type, sid)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                recipient_phone, 
                f"Appointment for {customer_name} on {appointment_date} at {appointment_time}",
                RCS_APPOINTMENT_TEMPLATE_SID,
                json.dumps({"name": customer_name, "date": appointment_date, "time": appointment_time}),
                'sent', 
                'RCS' if is_rcs else 'SMS',
                message.sid
            ))
            conn.commit()
            conn.close()
            
            return jsonify({
                'success': True,
                'message_sid': message.sid,
                'status': 'sent',
                'message_type': 'RCS' if is_rcs else 'SMS',
                'from': str(actual_from),
                'template_used': True
            }), 200
            
        except TwilioRestException as e:
            print(f"RCS failed: {str(e)}, falling back to SMS")
            
            # Fallback to SMS with quick reply instructions
            sms_body = f"Hi {customer_name}! Appointment on {appointment_date} at {appointment_time}.\n\nReply:\n1 - Confirm\n2 - Reschedule\n3 - Call Us"
            
            message = twilio_client.messages.create(
                messaging_service_sid=TWILIO_MESSAGING_SERVICE_SID,
                to=recipient_phone,
                body=sms_body  # Regular SMS body
            )
            
            # Log SMS
            conn = sqlite3.connect('messages.db')
            c = conn.cursor()
            c.execute('''
                INSERT INTO messages 
                (recipient, message, status, message_type, sid)
                VALUES (?, ?, ?, ?, ?)
            ''', (recipient_phone, sms_body, 'sent', 'SMS', message.sid))
            conn.commit()
            conn.close()
            
            return jsonify({
                'success': True,
                'message_sid': message.sid,
                'status': 'sent',
                'message_type': 'SMS',
                'note': 'Sent as SMS (RCS unavailable for this recipient)'
            }), 200
                
    except Exception as e:
        print(f"Error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/messages', methods=['GET'])
def get_messages():
    """Get message history"""
    try:
        limit = request.args.get('limit', 50, type=int)
        conn = sqlite3.connect('messages.db')
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
            if msg.get('variables'):
                try:
                    msg['variables'] = json.loads(msg['variables'])
                except:
                    pass
            messages.append(msg)
        
        conn.close()
        return jsonify(messages), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Webhook for button responses
@app.route('/rcs-webhook', methods=['POST'])
def handle_rcs_webhook():
    """Handle RCS quick reply button clicks"""
    try:
        message_sid = request.form.get('MessageSid')
        from_number = request.form.get('From')
        button_payload = request.form.get('ButtonPayload')
        body = request.form.get('Body')
        
        print(f"Webhook: Button '{button_payload}' clicked by {from_number}")
        
        # Respond based on button clicked
        response_messages = {
            'confirm': "✅ Perfect! Your appointment is confirmed. See you soon!",
            'reschedule': "📅 To reschedule, please call 1-888-610-3810 or reply with your preferred date/time.",
            'call_us': "📞 Call us at 1-888-610-3810 (Mon-Fri 9AM-5PM EST)"
        }
        
        response_text = response_messages.get(button_payload, "Thank you for your response!")
        
        # Send response
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
    app.run(host='0.0.0.0', port=port, debug=False)
