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

# Your new RCS Card Template SID
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

@app.route('/send-rcs', methods=['POST'])
def send_rcs():
    """
    Send RCS message using your new Card template with quick replies
    """
    try:
        data = request.json
        recipient_phone = data.get('phone')
        
        # Get variables for the template
        customer_name = data.get('customer_name', 'Customer')
        appointment_date = data.get('date', 'tomorrow')
        appointment_time = data.get('time', '2:00 PM')
        
        # Validate phone number
        if not recipient_phone:
            return jsonify({'error': 'Phone number is required'}), 400
            
        if not recipient_phone.startswith('+'):
            recipient_phone = '+' + recipient_phone
        
        try:
            # Send RCS message using your Card template
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
            conn = sqlite3.connect('messages.db')
            c = conn.cursor()
            c.execute('''
                INSERT INTO messages 
                (recipient, message, template_used, variables, status, message_type, sid)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                recipient_phone, 
                f"Appointment reminder for {customer_name}",
                RCS_APPOINTMENT_TEMPLATE_SID,
                json.dumps({"name": customer_name, "date": appointment_date, "time": appointment_time}),
                'sent', 
                'RCS', 
                message.sid
            ))
            conn.commit()
            conn.close()
            
            return jsonify({
                'success': True,
                'message_sid': message.sid,
                'status': 'sent',
                'type': 'RCS Card with Quick Replies',
                'template_used': 'ringlypro_appointment_reminder'
            }), 200
            
        except TwilioRestException as e:
            print(f"Twilio error: {str(e)}")
            
            # Fallback to SMS
            try:
                sms_body = f"Hi {customer_name}! Appointment on {appointment_date} at {appointment_time}. Reply 1 to Confirm, 2 to Reschedule, 3 to Call us."
                
                message = twilio_client.messages.create(
                    from_=os.getenv('TWILIO_PHONE_NUMBER'),
                    to=recipient_phone,
                    body=sms_body
                )
                
                return jsonify({
                    'success': True,
                    'message_sid': message.sid,
                    'status': 'sent',
                    'type': 'SMS (RCS fallback)',
                    'note': 'Sent as SMS because RCS was unavailable'
                }), 200
                
            except Exception as sms_error:
                return jsonify({'error': f'Failed to send: {str(sms_error)}'}), 500
                
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/send-quick-rcs', methods=['POST'])
def send_quick_rcs():
    """
    Simplified endpoint for quick RCS sending
    """
    try:
        data = request.json
        
        message = twilio_client.messages.create(
            messaging_service_sid=TWILIO_MESSAGING_SERVICE_SID,
            to=data.get('phone'),
            content_sid=RCS_APPOINTMENT_TEMPLATE_SID,
            content_variables=json.dumps({
                "1": data.get('name', 'Customer'),
                "2": data.get('date', 'tomorrow'),
                "3": data.get('time', '2:00 PM')
            })
        )
        
        return jsonify({
            'success': True,
            'sid': message.sid
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Webhook to handle quick reply responses
@app.route('/rcs-webhook', methods=['POST'])
def handle_rcs_webhook():
    """
    Handle incoming RCS quick reply button clicks
    """
    # Get the webhook data
    message_sid = request.form.get('MessageSid')
    from_number = request.form.get('From')
    button_payload = request.form.get('ButtonPayload')  # This will be 'confirm', 'reschedule', or 'call_us'
    body = request.form.get('Body')
    
    print(f"Button clicked: {button_payload} from {from_number}")
    
    # Handle different button responses
    if button_payload == 'confirm':
        # Send confirmation message
        twilio_client.messages.create(
            messaging_service_sid=TWILIO_MESSAGING_SERVICE_SID,
            to=from_number,
            body="✅ Great! Your appointment is confirmed. We'll see you soon!"
        )
    
    elif button_payload == 'reschedule':
        # Send reschedule instructions
        twilio_client.messages.create(
            messaging_service_sid=TWILIO_MESSAGING_SERVICE_SID,
            to=from_number,
            body="To reschedule, please call us at 1-888-610-3810 or reply with your preferred date and time."
        )
    
    elif button_payload == 'call_us':
        # Send call information
        twilio_client.messages.create(
            messaging_service_sid=TWILIO_MESSAGING_SERVICE_SID,
            to=from_number,
            body="📞 Please call us at 1-888-610-3810. We're available Mon-Fri 9AM-5PM."
        )
    
    return '', 200

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
