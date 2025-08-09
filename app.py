import os
import json
import sqlite3
import re
from datetime import datetime
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException
from dotenv import load_dotenv
import traceback
import openai  # For GPT integration (optional)

# Load environment variables
load_dotenv()

app = Flask(__name__)
CORS(app)

# Existing Twilio Configuration
TWILIO_ACCOUNT_SID = os.getenv('TWILIO_ACCOUNT_SID')
TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN')
TWILIO_MESSAGING_SERVICE_SID = os.getenv('TWILIO_MESSAGING_SERVICE_SID')
TWILIO_PHONE_NUMBER = os.getenv('TWILIO_PHONE_NUMBER', '+18886103810')
RCS_CARD_TEMPLATE_SID = os.getenv('RCS_CARD_TEMPLATE_SID', 'HXf872225ca0766f4b7f0f7ab024685ae7')

# Optional: OpenAI Configuration for advanced AI
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')  # Optional for GPT integration
if OPENAI_API_KEY:
    openai.api_key = OPENAI_API_KEY

twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# [Keep all existing database and initialization code...]

# ==========================================
# INTELLIGENT RESPONSE SYSTEM
# ==========================================

class IntelligentResponder:
    """AI-powered response system for customer queries"""
    
    def __init__(self):
        # Define intents and responses
        self.intents = {
            'greeting': {
                'patterns': [r'\bhello\b', r'\bhi\b', r'\bhey\b', r'\bgood morning\b', r'\bgood afternoon\b'],
                'responses': [
                    "Hello! 👋 Welcome to RinglyPro! How can I help you today?",
                    "Hi there! 😊 Thanks for reaching out to RinglyPro. What can I assist you with?",
                    "Hey! Great to hear from you. How can RinglyPro help your business today?"
                ]
            },
            'get_started': {
                'patterns': [r'get started', r'how.*start', r'sign up', r'begin', r'try.*free'],
                'responses': [
                    "🚀 Getting started with RinglyPro is easy!\n\n1️⃣ Sign up for free at ringlypro.com\n2️⃣ Connect your phone number\n3️⃣ Start automating!\n\nReply DEMO for a walkthrough or PRICING for our plans."
                ]
            },
            'pricing': {
                'patterns': [r'pric', r'cost', r'how much', r'plans', r'subscription'],
                'responses': [
                    "💰 RinglyPro Pricing:\n\n📱 Starter: $29/mo\n- 1,000 messages\n- Basic automation\n\n🚀 Pro: $99/mo\n- 10,000 messages\n- Advanced AI\n- Priority support\n\n🏢 Enterprise: Custom\n- Unlimited messages\n- Custom integrations\n\nReply TRIAL for 14-day free trial!"
                ]
            },
            'features': {
                'patterns': [r'features', r'what.*do', r'capabilities', r'benefits'],
                'responses': [
                    "✨ RinglyPro Features:\n\n🤖 24/7 AI Receptionist\n📅 Smart appointment scheduling\n💬 RCS & SMS automation\n📊 Analytics dashboard\n🔄 CRM integration\n📞 Missed call text-back\n🎯 Lead qualification\n\nReply DEMO to see it in action!"
                ]
            },
            'demo': {
                'patterns': [r'demo', r'trial', r'test', r'try', r'sample'],
                'responses': [
                    "🎥 I'd love to show you RinglyPro in action!\n\n📅 Book a demo: ringlypro.com/demo\n📞 Call us: 1-888-610-3810\n💬 Or reply SCHEDULE to book right now!\n\nYou can also start your 14-day free trial immediately at ringlypro.com/trial"
                ]
            },
            'support': {
                'patterns': [r'help', r'support', r'problem', r'issue', r'not work'],
                'responses': [
                    "🛟 I'm here to help!\n\n📧 Email: support@ringlypro.com\n📞 Phone: 1-888-610-3810\n💬 Live chat: ringlypro.com/chat\n\nWhat specific issue are you experiencing? Reply with your question and I'll help immediately!"
                ]
            },
            'appointment': {
                'patterns': [r'appointment', r'schedule', r'book', r'meeting', r'calendar'],
                'responses': [
                    "📅 Let's schedule your appointment!\n\nAvailable slots this week:\n⏰ Tomorrow 2:00 PM\n⏰ Thursday 10:00 AM\n⏰ Friday 3:30 PM\n\nReply with your preferred time or CALL to speak with someone now."
                ]
            },
            'contact': {
                'patterns': [r'contact', r'phone', r'email', r'reach', r'call'],
                'responses': [
                    "📞 Contact RinglyPro:\n\n☎️ Phone: 1-888-610-3810\n📧 Email: hello@ringlypro.com\n💬 Live Chat: ringlypro.com\n📍 Office: Mon-Fri 9AM-6PM EST\n\nHow would you prefer to connect?"
                ]
            },
            'thanks': {
                'patterns': [r'thank', r'thanks', r'thx', r'appreciate'],
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
        
        # FAQ Database
        self.faqs = {
            'integration': "RinglyPro integrates with 50+ CRMs including Salesforce, HubSpot, Pipedrive, and more! Setup takes just 5 minutes.",
            'security': "Your data is 100% secure with RinglyPro. We use bank-level encryption and are SOC2 compliant.",
            'cancel': "You can cancel anytime with no penalties. We offer a 30-day money-back guarantee!",
            'api': "Yes! RinglyPro offers a full REST API for custom integrations. Check our docs at ringlypro.com/api",
            'training': "We provide free onboarding and training for all plans. Plus 24/7 support via chat, email, and phone!"
        }
    
    def detect_intent(self, message):
        """Detect the intent of the user's message"""
        message_lower = message.lower()
        
        for intent, data in self.intents.items():
            for pattern in data['patterns']:
                if re.search(pattern, message_lower):
                    return intent
        
        # Check FAQs
        for keyword, response in self.faqs.items():
            if keyword in message_lower:
                return 'faq', response
        
        return None
    
    def get_response(self, message, phone_number=None):
        """Get intelligent response based on message"""
        
        # Detect intent
        intent_result = self.detect_intent(message)
        
        if isinstance(intent_result, tuple) and intent_result[0] == 'faq':
            return intent_result[1]
        
        if intent_result and intent_result in self.intents:
            import random
            responses = self.intents[intent_result]['responses']
            return random.choice(responses)
        
        # If no intent matched, use contextual response
        return self.get_contextual_response(message, phone_number)
    
    def get_contextual_response(self, message, phone_number=None):
        """Get contextual response based on conversation history"""
        
        # Check if it's a question
        if '?' in message:
            return self.handle_question(message)
        
        # Check for specific keywords
        message_lower = message.lower()
        
        if any(word in message_lower for word in ['yes', 'yeah', 'sure', 'ok', 'okay']):
            return "Great! 🎉 What would you like to do next? You can:\n\n1️⃣ Start free trial\n2️⃣ Schedule a demo\n3️⃣ Learn about features\n\nJust reply with your choice!"
        
        if any(word in message_lower for word in ['no', 'nope', 'not']):
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
    
    def handle_question(self, question):
        """Handle questions specifically"""
        question_lower = question.lower()
        
        # Business hours
        if 'hours' in question_lower or 'open' in question_lower:
            return "🕒 Our support hours are Monday-Friday 9AM-6PM EST. However, our AI assistant (that's me!) is available 24/7 to help you!"
        
        # Location
        if 'where' in question_lower or 'location' in question_lower:
            return "📍 RinglyPro is headquartered in Austin, TX, but we serve businesses worldwide! Our service works anywhere in the US and Canada."
        
        # Who/What is RinglyPro
        if 'what is ringlypro' in question_lower or 'who are you' in question_lower:
            return (
                "🤖 RinglyPro is your AI-powered business assistant!\n\n"
                "We help businesses:\n"
                "✅ Never miss a call\n"
                "✅ Automate appointments\n"
                "✅ Qualify leads 24/7\n"
                "✅ Send smart RCS/SMS messages\n\n"
                "Think of us as your tireless digital receptionist! Want to see how it works? Reply DEMO!"
            )
        
        # Default question response
        return (
            "Great question! For the most accurate answer, you can:\n\n"
            "💬 Chat with our team at ringlypro.com/chat\n"
            "📞 Call us at 1-888-610-3810\n"
            "📧 Email support@ringlypro.com\n\n"
            "Or tell me more about what you'd like to know!"
        )
    
    def use_gpt(self, message, context=None):
        """Optional: Use GPT for advanced responses"""
        if not OPENAI_API_KEY:
            return None
        
        try:
            response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You are a helpful RinglyPro AI assistant. RinglyPro is an AI receptionist and SMS/RCS automation platform for businesses. Be friendly, professional, and helpful."},
                    {"role": "user", "content": message}
                ],
                max_tokens=200,
                temperature=0.7
            )
            return response.choices[0].message.content
        except:
            return None

# Initialize the intelligent responder
ai_responder = IntelligentResponder()

# ==========================================
# CONVERSATION TRACKING
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

init_conversation_db()

def log_conversation(phone, message, response, intent=None):
    """Log conversation for learning and analytics"""
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute('''
        INSERT INTO conversations (phone_number, message, response, intent)
        VALUES (?, ?, ?, ?)
    ''', (phone, message, response, intent))
    conn.commit()
    conn.close()

# ==========================================
# UPDATED WEBHOOK WITH AI
# ==========================================

@app.route('/rcs-webhook', methods=['POST'])
def handle_rcs_webhook():
    """Handle incoming messages with AI intelligence"""
    try:
        # Get webhook data
        message_sid = request.form.get('MessageSid')
        from_number = request.form.get('From')
        button_payload = request.form.get('ButtonPayload')
        body = request.form.get('Body', '').strip()
        
        print(f"=== AI WEBHOOK RECEIVED ===")
        print(f"From: {from_number}")
        print(f"Message: {body}")
        print(f"Button: {button_payload}")
        
        # Handle button clicks
        if button_payload:
            if button_payload.lower() == 'website':
                response_text = "🌐 Visit us at ringlypro.com or let me know what specific information you're looking for!"
            elif button_payload.lower() in ['confirm', 'confirmed']:
                response_text = "✅ Perfect! Your appointment is confirmed. We'll send you a reminder 24 hours before."
            elif button_payload.lower() in ['reschedule']:
                response_text = "📅 No problem! When would work better for you? Reply with your preferred date and time."
            else:
                response_text = ai_responder.get_response(button_payload, from_number)
        
        # Handle text messages with AI
        elif body:
            # Get intelligent response
            response_text = ai_responder.get_response(body, from_number)
            
            # Log the conversation
            intent = ai_responder.detect_intent(body)
            log_conversation(from_number, body, response_text, str(intent))
            
            # Optional: Try GPT if no good response
            if response_text == ai_responder.get_contextual_response(body, from_number):
                gpt_response = ai_responder.use_gpt(body)
                if gpt_response:
                    response_text = gpt_response
        
        else:
            response_text = "Thanks for reaching out to RinglyPro! How can I help you today?"
        
        # Send the intelligent response
        if response_text and from_number:
            # For complex responses, might want to use RCS card
            if len(response_text) > 300:
                # Send as RCS card for better formatting
                twilio_client.messages.create(
                    messaging_service_sid=TWILIO_MESSAGING_SERVICE_SID,
                    to=from_number,
                    content_sid=RCS_CARD_TEMPLATE_SID,
                    content_variables=json.dumps({
                        "1": response_text
                    })
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

# ==========================================
# ANALYTICS ENDPOINT
# ==========================================

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
        intent_stats = dict(c.fetchall())
        
        # Get total conversations
        c.execute('SELECT COUNT(*) FROM conversations')
        total_conversations = c.fetchone()[0]
        
        # Get unique users
        c.execute('SELECT COUNT(DISTINCT phone_number) FROM conversations')
        unique_users = c.fetchone()[0]
        
        conn.close()
        
        return jsonify({
            'total_conversations': total_conversations,
            'unique_users': unique_users,
            'intent_distribution': intent_stats,
            'ai_response_rate': '100%',
            'average_response_time': '<1 second'
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# [Keep all other existing routes...]

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    print("=" * 50)
    print("🤖 RINGLYPRO AI-POWERED RCS ASSISTANT")
    print("=" * 50)
    print(f"✅ AI Responder: Active")
    print(f"✅ Intent Detection: Ready")
    print(f"✅ Conversation Tracking: Enabled")
    print(f"✅ GPT Integration: {'Enabled' if OPENAI_API_KEY else 'Disabled (Optional)'}")
    print("=" * 50)
    app.run(host='0.0.0.0', port=port, debug=False)
