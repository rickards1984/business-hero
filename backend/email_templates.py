"""Email templates for invoice chasing."""
from typing import Optional


def get_chase_email_template(stage: int, invoice: dict, business_name: str, user_name: Optional[str] = None) -> dict:
    """
    Get email subject and body for a given chase stage.
    
    Args:
        stage: Chase stage (1-4)
        invoice: Invoice dict with customer_name, invoice_number, amount, due_date
        business_name: Name of the business sending the chase
        user_name: Name of the sender (for signature)
    
    Returns:
        dict with 'subject' and 'body' keys
    """
    customer_name = invoice.get('customer_name', 'Customer')
    invoice_number = invoice.get('invoice_number', 'N/A')
    amount = invoice.get('amount', 0)
    due_date = invoice.get('due_date', 'N/A')
    currency = invoice.get('currency', '£')
    
    # Format amount with 2 decimal places
    try:
        amount_formatted = f"{float(amount):.2f}"
    except (ValueError, TypeError):
        amount_formatted = str(amount)
    
    signature = f"\n\nBest regards,\n{user_name or business_name}"
    
    templates = {
        1: {
            "subject": f"Friendly Reminder: Invoice {invoice_number} Payment Due",
            "body": f"""Dear {customer_name},

I hope this message finds you well. This is a friendly reminder that invoice {invoice_number} for {currency}{amount_formatted} was due on {due_date}.

If you've already made the payment, please disregard this message. Otherwise, we would appreciate it if you could arrange payment at your earliest convenience.

If you have any questions about this invoice or need to discuss payment arrangements, please don't hesitate to get in touch.

Thank you for your continued business.{signature}"""
        },
        
        2: {
            "subject": f"Second Notice: Invoice {invoice_number} Now Overdue",
            "body": f"""Dear {customer_name},

I am writing to follow up on invoice {invoice_number} for {currency}{amount_formatted}, which was due on {due_date} and remains unpaid.

We understand that oversights can happen, but we would appreciate your prompt attention to this matter. Please arrange payment within the next 7 days.

If there are any issues preventing payment or if you wish to discuss a payment plan, please contact us immediately so we can work together to resolve this.

Thank you for your cooperation.{signature}"""
        },
        
        3: {
            "subject": f"URGENT: Final Notice Before Action - Invoice {invoice_number}",
            "body": f"""Dear {customer_name},

Despite our previous reminders, invoice {invoice_number} for {currency}{amount_formatted} (due {due_date}) remains outstanding.

This is our final notice before we are compelled to take further action to recover this debt. Please make payment within the next 7 days to avoid additional collection measures.

We strongly urge you to contact us immediately if you are experiencing difficulties. We would prefer to resolve this matter amicably.

This is a serious matter that requires your immediate attention.{signature}"""
        },
        
        4: {
            "subject": f"FINAL DEMAND: Invoice {invoice_number} - Legal Action Pending",
            "body": f"""Dear {customer_name},

FORMAL NOTICE OF INTENT TO PURSUE LEGAL ACTION

Invoice Number: {invoice_number}
Amount Outstanding: {currency}{amount_formatted}
Original Due Date: {due_date}

Despite multiple attempts to contact you regarding this outstanding debt, we have received no payment or communication from you.

We hereby give you formal notice that unless full payment is received within 7 DAYS from the date of this letter, we will have no alternative but to:

1. Refer this matter to our debt collection agency
2. Consider initiating legal proceedings to recover the debt plus interest and costs
3. Report the debt to credit reference agencies

This action will result in additional costs being added to the amount owed and may affect your credit rating.

To avoid these consequences, please make payment immediately or contact us to discuss this matter urgently.

This is not a decision we take lightly, but we must protect our business interests.{signature}

---
This communication is a formal demand for payment. Please treat it with the utmost urgency."""
        }
    }
    
    return templates.get(stage, templates[1])


def get_stage_description(stage: int) -> str:
    """Get human-readable description of each stage."""
    descriptions = {
        1: "Friendly Reminder",
        2: "Second Notice", 
        3: "Final Warning",
        4: "Legal Action Notice"
    }
    return descriptions.get(stage, "Reminder")


def get_stage_color(stage: int) -> str:
    """Get color for stage (for UI purposes)."""
    colors = {
        1: "primary",
        2: "primary",
        3: "warning",
        4: "error"
    }
    return colors.get(stage, "default")
