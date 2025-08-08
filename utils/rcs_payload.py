"""
RCS Payload Utility Functions
Handles RCS message formatting and SMS fallback
"""

import json
from typing import List, Dict, Optional


def create_rcs_payload(
    message_body: str,
    image_url: Optional[str] = None,
    quick_replies: Optional[List[str]] = None,
    rich_card: Optional[Dict] = None
) -> Dict:
    """
    Create a properly formatted RCS payload for Twilio
    
    Args:
        message_body: The main text message
        image_url: Optional image URL to include
        quick_replies: List of quick reply button texts
        rich_card: Optional rich card configuration
    
    Returns:
        Formatted RCS payload dictionary
    """
    payload = {
        "body": message_body,
        "contentType": "text/plain"
    }
    
    # Add media if provided
    if image_url:
        payload["media"] = {
            "contentType": "image",
            "url": image_url,
            "height": "MEDIUM"  # Can be SHORT, MEDIUM, or TALL
        }
    
    # Add quick reply suggestions
    if quick_replies:
        suggestions = []
        for reply_text in quick_replies[:11]:  # RCS supports max 11 suggestions
            suggestions.append({
                "type": "reply",
                "text": reply_text,
                "postbackData": reply_text
            })
        payload["suggestions"] = suggestions
    
    # Add rich card if provided
    if rich_card:
        payload["richCard"] = format_rich_card(rich_card)
    
    return payload


def format_rich_card(card_config: Dict) -> Dict:
    """
    Format a rich card for RCS
    
    Args:
        card_config: Configuration for the rich card
    
    Returns:
        Formatted rich card dictionary
    """
    rich_card = {
        "orientation": card_config.get("orientation", "VERTICAL"),
        "content": []
    }
    
    # Add card content
    if "title" in card_config:
        content_item = {
            "title": card_config["title"],
            "description": card_config.get("description", ""),
        }
        
        if "image_url" in card_config:
            content_item["media"] = {
                "contentType": "image",
                "url": card_config["image_url"],
                "height": card_config.get("image_height", "MEDIUM")
            }
        
        if "suggestions" in card_config:
            content_item["suggestions"] = []
            for suggestion in card_config["suggestions"]:
                if isinstance(suggestion, str):
                    content_item["suggestions"].append({
                        "type": "reply",
                        "text": suggestion,
                        "postbackData": suggestion
                    })
                elif isinstance(suggestion, dict):
                    content_item["suggestions"].append(suggestion)
        
        rich_card["content"].append(content_item)
    
    return rich_card


def create_carousel_cards(cards: List[Dict]) -> Dict:
    """
    Create a carousel of rich cards for RCS
    
    Args:
        cards: List of card configurations
    
    Returns:
        Formatted carousel payload
    """
    carousel = {
        "orientation": "HORIZONTAL",
        "width": "MEDIUM",
        "content": []
    }
    
    for card in cards[:10]:  # RCS supports max 10 cards in carousel
        card_item = {
            "title": card.get("title", ""),
            "description": card.get("description", ""),
        }
        
        if "image_url" in card:
            card_item["media"] = {
                "contentType": "image",
                "url": card["image_url"],
                "height": "MEDIUM"
            }
        
        if "button_text" in card and "button_url" in card:
            card_item["suggestions"] = [{
                "type": "openUrl",
                "text": card["button_text"],
                "url": card["button_url"]
            }]
        
        carousel["content"].append(card_item)
    
    return {"richCard": carousel}


def create_sms_fallback(
    message_body: str,
    quick_replies: Optional[List[str]] = None
) -> str:
    """
    Create SMS fallback message when RCS is unavailable
    
    Args:
        message_body: The main text message
        quick_replies: List of quick reply options
    
    Returns:
        Formatted SMS message string
    """
    sms_message = message_body
    
    # Add quick reply options as numbered list for SMS
    if quick_replies:
        sms_message += "\n\nReply with:"
        for idx, reply in enumerate(quick_replies[:9], 1):
            sms_message += f"\n{idx}. {reply}"
    
    return sms_message


def validate_phone_number(phone: str) -> str:
    """
    Validate and format phone number for Twilio
    
    Args:
        phone: Input phone number
    
    Returns:
        Formatted phone number with country code
    
    Raises:
        ValueError: If phone number is invalid
    """
    # Remove all non-numeric characters except +
    cleaned = ''.join(c for c in phone if c.isdigit() or c == '+')
    
    # Ensure it starts with +
    if not cleaned.startswith('+'):
        # Assume US number if no country code
        if len(cleaned) == 10:
            cleaned = '+1' + cleaned
        else:
            cleaned = '+' + cleaned
    
    # Basic validation
    if len(cleaned) < 11 or len(cleaned) > 16:
        raise ValueError(f"Invalid phone number: {phone}")
    
    return cleaned


# Example RCS message templates
TEMPLATES = {
    "appointment_reminder": {
        "body": "Hi {name}, this is a reminder about your appointment on {date} at {time}.",
        "quick_replies": ["✅ Confirm", "🔄 Reschedule", "❌ Cancel", "📞 Call Us"]
    },
    "order_update": {
        "body": "Your order #{order_id} has been {status}!",
        "image_url": "https://example.com/order-status.jpg",
        "quick_replies": ["📦 Track Order", "❓ Get Help", "🛍️ Order Again"]
    },
    "promotional": {
        "body": "🎉 Special Offer: {offer_text}",
        "rich_card": {
            "title": "Limited Time Offer",
            "description": "Save up to 50% on selected items",
            "image_url": "https://example.com/promo.jpg",
            "suggestions": ["Shop Now", "View Details", "Save for Later"]
        }
    },
    "survey": {
        "body": "How was your recent experience with us?",
        "quick_replies": ["⭐⭐⭐⭐⭐ Excellent", "⭐⭐⭐⭐ Good", "⭐⭐⭐ Average", "⭐⭐ Poor", "⭐ Very Poor"]
    }
}


def get_template(template_name: str, **kwargs) -> Dict:
    """
    Get a pre-defined RCS message template
    
    Args:
        template_name: Name of the template
        **kwargs: Variables to fill in the template
    
    Returns:
        Formatted RCS payload
    """
    if template_name not in TEMPLATES:
        raise ValueError(f"Template '{template_name}' not found")
    
    template = TEMPLATES[template_name].copy()
    
    # Replace variables in body
    if "body" in template and kwargs:
        template["body"] = template["body"].format(**kwargs)
    
    # Create RCS payload from template
    return create_rcs_payload(
        message_body=template.get("body", ""),
        image_url=template.get("image_url"),
        quick_replies=template.get("quick_replies"),
        rich_card=template.get("rich_card")
    )