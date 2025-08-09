import os
import json
import sqlite3
import re
import random
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
RCS_CARD_TEMPLATE_SID = os.getenv('RCS_CARD_TEMPLATE_SID', 'HXf872225ca0766f4b7f0f7ab024685ae7')

# Initialize Twilio client
twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# ==========================================
# DATABASE SETUP - MUST BE FIRST!
# ==========================================
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

# Initialize main database
init_db()

# ==========================================
# CONVERSATION TRACKING DATABASE
# ==========================================
def init_conversation_db():
    """Initialize conversation tracking database"""
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone_number TEXT NOT NULL,
            message TEXT NOT NULL,
            response TEXT,
            intent TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

# Initialize conversation database
init_conversation_db()

def log_conversation(phone, message, response, intent=None):
    """Log conversation for learning and analytics"""
    try:
        conn = sqlite3.connect(DATABASE)
        c = conn.cursor()
        c.execute('''
            INSERT INTO conversations (phone_number, message, response, intent)
            VALUES (?, ?, ?, ?)
        ''', (phone, message, response, intent))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error logging conversation: {str(e)}")

# ==========================================
# INTELLIGENT RESPONSE SYSTEM
# ==========================================

class IntelligentResponder:
    """AI-powered response system for customer queries"""
    
    def __init__(self):
        # Define intents and responses
        self.intents = {
            'greeting': {
                'patterns': [r'\bhello\b', r'\bhi\b', r'\bhey\b', r'\bgood morning\b', r'\bgood afternoon\b', r'\bgood evening\b'],
                'responses': [
                    "Hello! 👋 Welcome to RinglyPro! How can I help you today?",
                    "Hi there! 😊 Thanks for reaching out to RinglyPro. What can I assist you with?",
                    "Hey! Great to hear from you. How can RinglyPro help your business today?"
                ]
            },
            'get_started': {
                'patterns': [r'get started', r'how.*start', r'sign up', r'begin', r'try.*free', r'start.*trial'],
                'responses': [
                    "🚀 Getting started with RinglyPro is easy!\n\n1️⃣ Sign up for free at ringlypro.com\n2️⃣ Connect your phone number\n3️⃣ Start automating!\n\nReply DEMO for a walkthrough or PRICING for our plans."
                ]
            },
            'pricing': {
                'patterns': [r'pric', r'cost', r'how much', r'plans', r'subscription', r'fee'],
                'responses': [
                    "💰 RinglyPro Pricing:\n\n📱 Starter: $29/mo\n- 1,000 messages\n- Basic automation\n\n🚀 Pro: $99/mo\n- 10,000 messages\n- Advanced AI\n- Priority support\n\n🏢 Enterprise: Custom\n- Unlimited messages\n- Custom integrations\n\nReply TRIAL for 14-day free trial!"
                ]
            },
            'features': {
                'patterns': [r'features', r'what.*do', r'capabilities', r'benefits', r'what.*offer'],
                'responses': [
                    "✨ RinglyPro Features:\n\n🤖 24/7 AI Receptionist\n📅 Smart appointment scheduling\n💬 RCS & SMS automation\n📊 Analytics dashboard\n🔄 CRM integration\n📞 Missed call text-back\n🎯 Lead qualification\n\nReply DEMO to see it in action!"
                ]
            },
            'demo': {
                'patterns': [r'demo', r'trial', r'test', r'try', r'sample', r'example'],
                'responses': [
                    "🎥 I'd love to show you RinglyPro in action!\n\n📅 Book a demo: ringlypro.com/demo\n📞 Call us: 1-888-610-3810\n💬 Or reply SCHEDULE to book right now!\n\nYou can also start your 14-day free trial immediately!"
                ]
            },
            'support': {
                'patterns': [r'help', r'support', r'problem', r'issue', r'not work', r'trouble'],
                'responses': [
                    "🛟 I'm here to help!\n\n📧 Email: support@ringlypro.com\n📞 Phone: 1-888-610-3810\n💬 Live chat: ringlypro.com/chat\n\nWhat specific issue are you experiencing? I'll help you right away!"
                ]
            },
            'appointment': {
                'patterns': [r'appointment', r'schedule', r'book', r'meeting', r'calendar'],
                'responses': [
                    "📅 Let's schedule your appointment!\n\nAvailable slots this week:\n⏰ Tomorrow 2:00 PM\n⏰ Thursday 10:00 AM\n⏰ Friday 3:30 PM\n\nReply with your preferred time or CALL to speak with someone now."
                ]
            },
            'thanks': {
                'patterns': [r'thank', r'thanks', r'thx', r'appreciate', r'ty'],
                'responses': [
                    "You're welcome! 😊 We're always here to help. Don't hesitate to reach out if you need anything else!",
                    "Happy to help! 🎉 Is there anything else you'd like to know about RinglyPro?"
                ]
            },
            'bye': {
                'patterns': [r'bye', r'goodbye', r'see you', r'later', r'exit'],
                'responses': [
                    "Goodbye! 👋 Thanks for chatting with RinglyPro. We're here 24/7 whenever you need us!",
                    "See you soon! 🚀 Remember, you can always text us or visit ringlypro.com. Have a great day!"
                ]
            }
        }
    
    def detect_intent(self, message):
        """Detect the intent of the user's message"""
        message_lower = message.lower()
        
        for intent, data in self.intents.items():
            for pattern in data['patterns']:
                if re.search(pattern, message_lower):
                    return intent
        return None
    
    def get_response(self, message, phone_number=None):
        """Get intelligent response based on message"""
        
        # Detect intent
        intent = self.detect_intent(message)
        
        if intent and intent in self.intents:
            responses = self.intents[intent]['responses']
            return random.choice(responses)
        
        # Check for yes/no responses
        message_lower = message.lower()
        if any(word in message_lower for word in ['yes', 'yeah', 'sure', 'ok', 'okay', 'yep']):
            return "Great! 🎉 What would you like to do next? You can:\n\n1️⃣ Start free trial\n2️⃣ Schedule a demo\n3️⃣ Learn about features\n\nJust reply with your choice!"
        
        if any(word in message_lower for word in ['no', 'nope', 'not', 'nah']):
            return "No problem! If you change your mind or have any questions, I'm here 24/7. How else can I help you today?"
        
        # Default response for unrecognized input
        return (
            "Thanks for your message! I can help you with:\n\n"
            "📱 Getting started with RinglyPro\n"
            "💰 Pricing information\n"
            "🎯 Features overview\n"
            "📅 Scheduling a demo\n"
            "🛟 Technical support\n\n"
            "What interests you most?"
        )

# Initialize the AI responder
ai_responder = IntelligentResponder()

# ==========================================
# HELPER FUNCTIONS
# ==========================================

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

# ==========================================
# FLASK ROUTES
# ==========================================

@app.route('/')
def index():
    """Serve the main RCS client interface"""
    return render_template('rcs.html')

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint for monitoring"""
    return jsonify({
        'status': 'healthy', 
        'service': 'RinglyPro RCS Assistant with AI',
        'timestamp': datetime.now().isoformat(),
        'config': {
            'twilio_configured': bool(TWILIO_ACCOUNT_SID),
            'messaging_service': bool(TWILIO_MESSAGING_SERVICE_SID),
            'template_configured': bool(RCS_CARD_TEMPLATE_SID),
            'template_sid': RCS_CARD_TEMPLATE_SID[:10] + '...' if RCS_CARD_TEMPLATE_SID else None,
            'phone_number': TWILIO_PHONE_NUMBER,
            'ai_enabled': True
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
    """Handle incoming messages with AI intelligence"""
    try:
        # LOG ALL INCOMING DATA
        print("=" * 50)
        print("WEBHOOK TRIGGERED!")
        print("=" * 50)
        print(f"Request Method: {request.method}")
        print(f"Request Headers: {dict(request.headers)}")
        print(f"Form Data: {dict(request.form)}")
        print(f"JSON Data: {request.json if request.is_json else 'No JSON'}")
        print("=" * 50)
        
        # Get webhook data
        message_sid = request.form.get('MessageSid')
        from_number = request.form.get('From')
        to_number = request.form.get('To')
        button_payload = request.form.get('ButtonPayload')
        body = request.form.get('Body', '').strip()
        
        print(f"MessageSid: {message_sid}")
        print(f"From: {from_number}")
        print(f"To: {to_number}")
        print(f"Body: {body}")
        print(f"Button: {button_payload}")
        
        # Rest of your webhook code...
        
        response_text = ""
        
        # Handle button clicks
        if button_payload:
            button_lower = button_payload.lower()
            if 'website' in button_lower:
                response_text = "🌐 Visit us at ringlypro.com or let me know what specific information you're looking for!"
            elif button_lower in ['confirm', 'confirmed']:
                response_text = "✅ Perfect! Your appointment is confirmed. We'll send you a reminder 24 hours before."
            elif button_lower in ['reschedule']:
                response_text = "📅 No problem! When would work better for you? Reply with your preferred date and time."
            elif button_lower in ['call', 'call_us', 'call us']:
                response_text = "📞 Please call us at 1-888-610-3810. We're available Mon-Fri 9AM-5PM EST."
            else:
                response_text = ai_responder.get_response(button_payload, from_number)
        
        # Handle text messages with AI
        elif body:
            # Handle numbered responses (for SMS fallback)
            if body.strip() == '1':
                response_text = "✅ Perfect! Your appointment is confirmed. We'll see you soon!"
            elif body.strip() == '2':
                response_text = "📅 To reschedule, please call us at 1-888-610-3810 or reply with your preferred date and time."
            elif body.strip() == '3':
                response_text = "📞 Please call us at 1-888-610-3810. We're available Mon-Fri 9AM-5PM EST."
            else:
                # Get AI response
                response_text = ai_responder.get_response(body, from_number)
                
                # Log the conversation
                intent = ai_responder.detect_intent(body)
                log_conversation(from_number, body, response_text, str(intent))
        
        else:
            response_text = "Thanks for reaching out to RinglyPro! How can I help you today?"
        
        # Send the intelligent response
        if response_text and from_number:
            # For long responses, use RCS card
            if len(response_text) > 300 and RCS_CARD_TEMPLATE_SID:
                try:
                    twilio_client.messages.create(
                        messaging_service_sid=TWILIO_MESSAGING_SERVICE_SID,
                        to=from_number,
                        content_sid=RCS_CARD_TEMPLATE_SID,
                        content_variables=json.dumps({
                            "1": response_text
                        })
                    )
                except:
                    # Fallback to regular SMS
                    twilio_client.messages.create(
                        messaging_service_sid=TWILIO_MESSAGING_SERVICE_SID,
                        to=from_number,
                        body=response_text
                    )
            else:
                # Send as regular message
                twilio_client.messages.create(
                    messaging_service_sid=TWILIO_MESSAGING_SERVICE_SID,
                    to=from_number,
                    body=response_text
                )
            
            print(f"AI Response sent: {response_text[:100]}...")
        
        return '', 200
        
    except Exception as e:
        print(f"Webhook error: {str(e)}")
        traceback.print_exc()
        return '', 200

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

@app.route('/analytics', methods=['GET'])
def get_analytics():
    """Get AI conversation analytics"""
    try:
        conn = sqlite3.connect(DATABASE)
        c = conn.cursor()
        
        # Get intent distribution
        c.execute('''
            SELECT intent, COUNT(*) as count 
            FROM conversations 
            WHERE intent IS NOT NULL 
            GROUP BY intent
        ''')
        intent_rows = c.fetchall()
        intent_stats = dict(intent_rows) if intent_rows else {}
        
        # Get total conversations
        c.execute('SELECT COUNT(*) FROM conversations')
        total_result = c.fetchone()
        total_conversations = total_result[0] if total_result else 0
        
        # Get unique users
        c.execute('SELECT COUNT(DISTINCT phone_number) FROM conversations')
        unique_result = c.fetchone()
        unique_users = unique_result[0] if unique_result else 0
        
        # Get total messages sent
        c.execute('SELECT COUNT(*) FROM messages')
        messages_result = c.fetchone()
        total_messages = messages_result[0] if messages_result else 0
        
        conn.close()
        
        return jsonify({
            'total_conversations': total_conversations,
            'unique_users': unique_users,
            'total_messages_sent': total_messages,
            'intent_distribution': intent_stats,
            'ai_response_rate': '100%',
            'average_response_time': '<1 second'
        }), 200
        
    except Exception as e:
        print(f"Analytics error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/conversations', methods=['GET'])
def get_conversations():
    """Get conversation history with AI insights"""
    try:
        limit = request.args.get('limit', 50, type=int)
        phone = request.args.get('phone', None)
        
        conn = sqlite3.connect(DATABASE)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        
        if phone:
            c.execute('''
                SELECT * FROM conversations 
                WHERE phone_number = ?
                ORDER BY timestamp DESC 
                LIMIT ?
            ''', (phone, limit))
        else:
            c.execute('''
                SELECT * FROM conversations 
                ORDER BY timestamp DESC 
                LIMIT ?
            ''', (limit,))
        
        conversations = [dict(row) for row in c.fetchall()]
        conn.close()
        
        return jsonify(conversations), 200
        
    except Exception as e:
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

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    print("=" * 50)
    print("🤖 RINGLYPRO AI-POWERED RCS ASSISTANT")
    print("=" * 50)
    print(f"Port: {port}")
    print(f"Account SID: {'✓ Set' if TWILIO_ACCOUNT_SID else '✗ Not Set'}")
    print(f"Auth Token: {'✓ Set' if TWILIO_AUTH_TOKEN else '✗ Not Set'}")
    print(f"Messaging Service: {TWILIO_MESSAGING_SERVICE_SID if TWILIO_MESSAGING_SERVICE_SID else '✗ Not Set'}")
    print(f"RCS Template: {RCS_CARD_TEMPLATE_SID if RCS_CARD_TEMPLATE_SID else '✗ Not Set'}")
    print(f"Phone Number: {TWILIO_PHONE_NUMBER}")
    print(f"AI Responder: ✓ Active")
    print(f"Intent Detection: ✓ Ready")
    print(f"Conversation Tracking: ✓ Enabled")
    print("=" * 50)
    app.run(host='0.0.0.0', port=port, debug=False)
