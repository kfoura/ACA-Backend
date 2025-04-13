import asyncio
import time
import os
import json
import requests
from dotenv import load_dotenv
from pymongo import MongoClient
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

print("MONITOR_FUNCTION.PY IS BEING USED")

load_dotenv()
mongo_uri = os.getenv('MONGO_URI')
sender_email = os.getenv('sender_email')
password = os.getenv('password')

# Strip whitespace from password
password = password.strip() if password else ""

# Debug missing credentials
print(f"Email credentials loaded - Sender: {sender_email}, Password length: {len(password)}")

client = MongoClient(mongo_uri)
db = client['AggieClassAlert']
collection = db['CRNS']
email_collection = db['Emails']

running = True

async def monitor_crns(interval=60):
    """
    Background task to continuously monitor CRNs in the database.
    
    This function:
    1. Checks the availability of all CRNs in the database
    2. Updates their status in the database
    3. Sends notifications (email and SMS) when a CRN becomes available
    4. Deactivates alerts after notifications are sent
    
    Args:
        interval (int): Number of seconds to wait between checks
    """
    global running
    
    try:
        print(f"Starting continuous monitoring of all CRNs in database")
        print(f"Checking every {interval} seconds. Press Ctrl+C to stop.")
        
        # Import here to avoid circular imports
        import api
        howdy_api = api.Howdy_API()
        
        while running:
            # Get all active CRNs from MongoDB
            active_alerts = list(collection.find({'active': True}))
            
            if not active_alerts:
                print("No active CRNs to monitor. Waiting...")
                await asyncio.sleep(interval)
                continue
            
            # Get the availability for all terms
            availability = howdy_api.get_availability()
            timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
            
            print(f"\n---------- ALERT PROCESSING CYCLE: {timestamp} ----------")
            print(f"Processing {len(active_alerts)} active alerts")
            
            # Count alerts with SMS enabled
            sms_enabled_alerts = [alert for alert in active_alerts if alert.get('use_phone', False)]
            print(f"Found {len(sms_enabled_alerts)} alerts with SMS notifications enabled")
            
            # Group alerts by email for more efficient notifications
            alerts_by_email = {}
            
            # Print phone fields for each alert
            for alert in active_alerts:
                use_phone = alert.get('use_phone', False)
                if use_phone:
                    print(f"\nSMS-enabled alert: CRN {alert.get('CRN')} (Term {alert.get('Term')})")
                    print(f"- Email: {alert.get('email')}")
                    print(f"- Phone number: {alert.get('phone_number')}")
                    print(f"- Phone verified: {alert.get('phone_verified')}")
                    print(f"- Phone carrier: {alert.get('phone_carrier')}")
            
            # Check each CRN
            for alert in active_alerts:
                crn = alert['CRN']
                term_code = alert['Term']
                email = alert.get('email', '')
                
                # Phone notification settings
                use_phone = alert.get('use_phone', False)
                
                if term_code in availability and crn in availability[term_code]:
                    status = availability[term_code][crn]
                    print(f"[{timestamp}] CRN {crn} (Term {term_code}): {'Available' if status else 'Not available'}")
                    
                    # Update the status in the database
                    collection.update_one(
                        {'CRN': crn, 'Term': term_code, 'active': True},
                        {'$set': {'status': status, 'last_checked': time.time()}}
                    )
                    
                    # Group by email for notifications - send email when course is available
                    if email and status:
                        if email not in alerts_by_email:
                            alerts_by_email[email] = []
                        
                        alerts_by_email[email].append({
                            'crn': crn,
                            'term': term_code,
                            'status': status
                        })
                else:
                    print(f"[{timestamp}] CRN {crn} (Term {term_code}): Not found")
            
            # Send notifications grouped by email
            if alerts_by_email:
                print(f"\n----- SENDING EMAIL NOTIFICATIONS -----")
                for email, alerts in alerts_by_email.items():
                    available_crns = [alert for alert in alerts if alert['status']]
                    if available_crns:
                        print(f"\nSending notification to {email} about {len(available_crns)} available CRNs")
                        
                        try:
                            # Create email content
                            subject = "Class Availability Alert"
                            body = f"Hello,\n\nOne or more of your course alerts are now available:\n\n"
                            
                            for alert in available_crns:
                                crn = alert['crn']
                                term = alert['term']
                                term_name = howdy_api.term_codes_to_desc.get(term, f"Term {term}")
                                body += f"CRN: {crn} (Term: {term_name}) is now AVAILABLE!\n"
                            
                            body += "\nPlease log in to register as soon as possible as spaces may fill quickly.\n\n"
                            body += "Thank you for using Aggie Class Alert!"
                            
                            # Look up user data to get phone details if available
                            user_data = None
                            try:
                                user_data = db['Users'].find_one({'email': email})
                                if user_data:
                                    print(f"Found user data for {email}: phone_number={user_data.get('phone_number')}, phone_carrier={user_data.get('phone_carrier')}, phone_verified={user_data.get('phone_verified')}")
                                else:
                                    print(f"No user data found for {email}")
                            except Exception as user_err:
                                print(f"Error looking up user data: {str(user_err)}")
                            
                            # Check if user has verified phone for also sending SMS via email
                            sms_recipient = None
                            if user_data and user_data.get('phone_verified') and user_data.get('phone_number') and user_data.get('phone_carrier'):
                                # Define carrier domains
                                carrier_domains = {
                                    'verizon': '@vtext.com',
                                    'att': '@txt.att.net',
                                    'tmobile': '@tmomail.net',
                                    'sprint': '@messaging.sprintpcs.com',
                                    'cricket': '@mms.cricketwireless.net',
                                    'boost': '@sms.myboostmobile.com',
                                    'uscellular': '@email.uscc.net',
                                    'metro': '@mymetropcs.com',
                                }
                                
                                # Format phone number and get carrier
                                phone_number = user_data.get('phone_number')
                                carrier = user_data.get('phone_carrier')
                                
                                # Extract exactly 10 digits
                                digits_only = ''.join(char for char in phone_number if char.isdigit())
                                if len(digits_only) >= 10:
                                    formatted_phone = digits_only[-10:]  # Take the last 10 digits
                                    
                                    # Get carrier domain
                                    carrier_key = carrier.lower()
                                    if carrier_key in carrier_domains:
                                        carrier_domain = carrier_domains[carrier_key]
                                        sms_recipient = f"{formatted_phone}{carrier_domain}"
                                        print(f"Will also send SMS to: {sms_recipient}")
                                    else:
                                        print(f"Unknown carrier: {carrier}, cannot create SMS recipient")
                                else:
                                    print(f"Phone number doesn't have enough digits: {phone_number}")
                            
                            # SIMPLIFIED EMAIL SENDING - using same approach as phone verification
                            try:
                                # Create simple message
                                from email.message import EmailMessage
                                msg = EmailMessage()
                                msg.set_content(body)
                                msg["Subject"] = subject
                                msg["From"] = sender_email
                                msg["To"] = email
                                
                                # Print debug info
                                print(f"Preparing to send email to {email}")
                                print(f"Subject: {subject}")
                                print(f"Body (preview): {body[:100]}...")
                                
                                # Send using basic settings
                                smtp_server = "smtp.gmail.com"
                                port = 587  # Using TLS instead of SSL for better compatibility
                                
                                import smtplib
                                server = smtplib.SMTP(smtp_server, port)
                                server.ehlo()  # Can be omitted
                                server.starttls()  # Secure the connection
                                server.ehlo()  # Can be omitted
                                server.login(sender_email, password)
                                server.send_message(msg)
                                
                                # If we have an SMS recipient, send a second email to the SMS gateway
                                if sms_recipient:
                                    # Create more concise content for SMS
                                    sms_content = ""
                                    
                                    # Add CRNs to the message
                                    crn_list = [alert['crn'] for alert in available_crns]
                                    
                                    # Create SMS message
                                    sms_msg = EmailMessage()
                                    
                                    # Simplify SMS content to be just "CRN [number] is available"
                                    if len(crn_list) == 1:
                                        sms_content = f"CRN {crn_list[0]} is available"
                                    else:
                                        # For multiple CRNs, list each one on a separate line
                                        sms_content = "\n".join([f"CRN {crn} is available" for crn in crn_list])
                                    
                                    sms_msg.set_content(sms_content)
                                    sms_msg["Subject"] = "Aggie Class Alert"  # Set subject as requested
                                    sms_msg["From"] = sender_email
                                    sms_msg["To"] = sms_recipient
                                    
                                    print(f"Also sending SMS to {sms_recipient}")
                                    print(f"SMS subject: Aggie Class Alert")
                                    print(f"SMS content: {sms_content}")
                                    
                                    # Send the SMS message
                                    server.send_message(sms_msg)
                                    print(f"✅ SMS sent successfully to {sms_recipient}!")
                                
                                server.quit()
                                print(f"✅ Email sent successfully to {email}!")
                                
                                # Deactivate alerts after successful notification
                                for alert in available_crns:
                                    crn = alert['crn']
                                    term = alert['term']
                                    result = collection.update_one(
                                        {'CRN': crn, 'Term': term, 'email': email, 'active': True},
                                        {'$set': {'active': False, 'notified': True, 'notified_at': time.time(), 'notified_via_sms': sms_recipient is not None}}
                                    )
                                    print(f"Deactivated alert for CRN {crn} (Term {term}) for {email} - Modified: {result.modified_count}")
                                    
                            except Exception as e:
                                print(f"❌ Failed to send email: {str(e)}")
                                import traceback
                                traceback.print_exc()
                        except Exception as e:
                            print(f"❌ Failed to send email to {email}: {e}")
            else:
                print("No email notifications to send.")
            
            # Wait for the next check
            print(f"\nWaiting {interval} seconds until next check...")
            await asyncio.sleep(interval)
    except Exception as e:
        print(f"An error occurred in monitor_crns: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print("Monitoring stopped.") 