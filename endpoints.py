import api 
from dotenv import load_dotenv
import os
from pymongo import MongoClient
import time
import asyncio
import json
import argparse
import signal
import sys
from flask import Flask, request, jsonify
from flask_cors import CORS, cross_origin
import threading
from flask_mail import Mail, Message
from email.message import EmailMessage

import re
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import anex  # Import the anex module
import random
try:
    import RMP   # Import the RMP module
    print("Successfully imported RMP module")
    RMP_AVAILABLE = True
except ImportError as e:
    print(f"ERROR importing RMP module: {e}")
    print("RateMyProfessor functionality will be disabled")
    RMP_AVAILABLE = False

print("ENDPOINTS.PY IS BEING USED")

load_dotenv()

sender_email = os.getenv('sender_email')
password = os.getenv('password')

# Debug missing credentials
print(f"Email credentials loaded - Sender: {sender_email}, Password: {'******' if password else None}")

mongo_uri = os.getenv('MONGO_URI')

api = api.Howdy_API()
client = MongoClient(mongo_uri)
db = client['AggieClassAlert']
collection = db['CRNS']
email_collection = db['Emails']  # New collection for emails
users_collection = db['Users']   # Collection for user accounts

# Create indexes for faster queries
try:
    # Email index for Users collection
    users_collection.create_index("email", unique=True)
    
    # Indexes for CRNS collection
    collection.create_index([("CRN", 1), ("Term", 1)])
    collection.create_index("email")
    
    print("Database indexes created successfully")
except Exception as e:
    print(f"Error creating indexes: {str(e)}")

# Global flag to control the main loop
running = True

# Create Flask app
app = Flask(__name__)
# Configure CORS properly to allow requests from localhost:3000
CORS(app, origins=["http://localhost:3001", "https://aggieclassalert.com"], supports_credentials=True, 
     allow_headers=["Content-Type", "Authorization"], methods=["GET", "POST", "OPTIONS", "DELETE"])

# Add OPTIONS routes for each endpoint for preflight requests
@app.route('/api/add-alert', methods=['OPTIONS'])
def handle_options():
    return '', 200

@app.route('/api/alerts', methods=['OPTIONS'])
def handle_alerts_options():
    return '', 200

@app.route('/api/sample-crns', methods=['OPTIONS'])
def handle_sample_crns_options():
    return '', 200

@app.route('/api/emails', methods=['OPTIONS'])
def handle_emails_options():
    return '', 200

@app.route('/api/alerts/by-email/<email>', methods=['OPTIONS'])
def handle_alerts_by_email_options(email):
    return '', 200

@app.route('/api/professors', methods=['OPTIONS'])
def handle_professors_options():
    return '', 200

def signal_handler(sig, frame):
    """Handle keyboard interrupts gracefully"""
    global running
    print('\nStopping the service gracefully...')
    running = False

# Register the signal handler
signal.signal(signal.SIGINT, signal_handler)

# Helper function to normalize email addresses
def normalize_email(email):
    """Normalize email addresses to ensure consistency"""
    if not email:
        return email
        
    email = email.strip().lower()
    return email

@app.route('/api/add-alert', methods=['POST'])
def add_alert():
    """API endpoint to add a new CRN to monitor"""
    data = request.json
    if not data or 'crn' not in data:
        return jsonify({'error': 'CRN is required'}), 400
    
    crn = str(data['crn'])
    term_code = str(data.get('term', '202531'))  # Default to Fall 2025 - College Station
    raw_email = data.get('email', '')
    use_phone = data.get('use_phone', False)  # New flag to determine if SMS notifications should be used
    
    # Get all the extended fields if they're provided
    phone_number = data.get('phone_number', None)
    phone_verified = data.get('phone_verified', False)
    phone_carrier = data.get('phone_carrier', None)
    timestamp = data.get('timestamp', time.time())
    active = data.get('active', True)
    status = data.get('status', False)
    notified = data.get('notified', False)
    notified_at = data.get('notified_at', None)
    notified_via_sms = data.get('notified_via_sms', False)
    last_checked = data.get('last_checked', time.time())
    original_email = data.get('original_email', raw_email)
    
    # Normalize the email if provided
    email = normalize_email(raw_email) if raw_email else ''
    print(f"Adding alert - CRN: {crn}, Term: {term_code}, Raw Email: {raw_email}, Normalized Email: {email}, Use Phone: {use_phone}")
    
    # Validate CRN format
    if not crn.isdigit():
        return jsonify({'error': 'CRN must contain only numbers'}), 400
    
    try:
        # Check if the CRN exists for this term
        if api and hasattr(api, 'classes') and term_code in api.classes:
            found = False
            for c in api.classes[term_code]:
                if c.get('SWV_CLASS_SEARCH_CRN') == crn:
                    found = True
                    break
            
            if not found:
                print(f"⚠️ WARNING: CRN {crn} was not found in term {term_code}.")
        
        # Skip the CRN validation for now since we're working with future terms
        """
        if not found:
            return jsonify({
                'error': f"CRN {crn} not found in term {term_code}. Please check the CRN and try again."
            }), 400
        """
        
        # First, handle the email
        user_phone_number = phone_number
        user_phone_verified = phone_verified
        user_phone_carrier = phone_carrier
        
        if email:
            # ALWAYS check if user exists in Users collection, create if not
            try:
                existing_user = users_collection.find_one({'email': email})
                print(f"Found user document: {existing_user is not None}")
                
                if existing_user:
                    print(f"User doc phone info: number={existing_user.get('phone_number')}, verified={existing_user.get('phone_verified')}, carrier={existing_user.get('phone_carrier')}")
                
                if not existing_user:
                    # Create new user record
                    user = {
                        'email': email,
                        'original_email': original_email,
                        'created_at': timestamp,
                        'last_login': timestamp,
                        'phone_number': user_phone_number,
                        'phone_verified': user_phone_verified,
                        'phone_carrier': user_phone_carrier
                    }
                    user_result = users_collection.insert_one(user)
                    print(f"✅ Added new user from alert: {email} (ID: {user_result.inserted_id})")
                else:
                    print(f"User already exists: {email}")
                    # Update with new phone information if provided
                    if user_phone_number and user_phone_verified and user_phone_carrier:
                        users_collection.update_one(
                            {'email': email},
                            {'$set': {
                                'phone_number': user_phone_number,
                                'phone_verified': user_phone_verified,
                                'phone_carrier': user_phone_carrier,
                                'last_login': timestamp
                            }}
                        )
                        print(f"Updated user phone data for {email}")
                    else:
                        # Get phone information from existing user if not provided
                        if not user_phone_number:
                            user_phone_number = existing_user.get('phone_number')
                        if not user_phone_verified:
                            user_phone_verified = existing_user.get('phone_verified', False)
                        if not user_phone_carrier:
                            user_phone_carrier = existing_user.get('phone_carrier')
                    
                    print(f"Phone info retrieved/updated - Number: {user_phone_number}, Verified: {user_phone_verified}, Carrier: {user_phone_carrier}")
                    
                    if use_phone and user_phone_number and user_phone_verified and user_phone_carrier:
                        print(f"User has verified phone and SMS is enabled: {user_phone_number}, Carrier: {user_phone_carrier}")
                    elif use_phone:
                        print(f"SMS is enabled but user does not have complete phone verification:")
                        print(f"- Phone number: {user_phone_number}")
                        print(f"- Phone verified: {user_phone_verified}")
                        print(f"- Phone carrier: {user_phone_carrier}")
            except Exception as user_err:
                print(f"Error handling user creation: {str(user_err)}")
                import traceback
                traceback.print_exc()
            
            # Also handle email collection
            try:
                existing_email = email_collection.find_one({'email': email})
                if not existing_email:
                    # Create new email record
                    email_doc = {
                        'email': email,
                        'original_email': original_email,
                        'created_at': timestamp,
                        'active': True
                    }
                    email_result = email_collection.insert_one(email_doc)
                    print(f"✅ Added new email: {email} (ID: {email_result.inserted_id})")
                else:
                    print(f"Email already exists: {email}")
            except Exception as email_err:
                print(f"Error handling email creation: {str(email_err)}")
                import traceback
                traceback.print_exc()
        
        # Check if this user already has an alert for this CRN
        if email:
            existing_user_alert = collection.find_one({
                'CRN': crn, 
                'Term': term_code, 
                'email': email,
                'active': True
            })
            
            if existing_user_alert:
                # Update all the fields if provided
                update_fields = {
                    'use_phone': use_phone,
                    'phone_number': user_phone_number,
                    'phone_verified': user_phone_verified,
                    'phone_carrier': user_phone_carrier
                }
                
                # Update additional fields if provided
                if 'status' in data:
                    update_fields['status'] = status
                if 'notified' in data:
                    update_fields['notified'] = notified
                if 'notified_at' in data:
                    update_fields['notified_at'] = notified_at
                if 'notified_via_sms' in data:
                    update_fields['notified_via_sms'] = notified_via_sms
                if 'last_checked' in data:
                    update_fields['last_checked'] = last_checked
                    
                collection.update_one(
                    {'_id': existing_user_alert['_id']},
                    {'$set': update_fields}
                )
                print(f"Updated existing alert with new settings")
                    
                return jsonify({
                    'message': 'You are already monitoring this CRN',
                    'crn': crn,
                    'term': term_code,
                    'use_phone': use_phone
                }), 200
        
        # Store in MongoDB - use all the provided fields
        alert = {
            'CRN': crn,
            'Term': term_code,
            'email': email,
            'original_email': original_email,
            'timestamp': timestamp,
            'active': active,
            'use_phone': use_phone,
            'phone_number': user_phone_number,
            'phone_verified': user_phone_verified,
            'phone_carrier': user_phone_carrier,
            'status': status,
            'notified': notified,
            'notified_at': notified_at,
            'notified_via_sms': notified_via_sms,
            'last_checked': last_checked
        }
        
        print(f"Creating new alert with provided data: {alert}")
        result = collection.insert_one(alert)
        
        # Double-check the alert was created with the right phone info
        created_alert = collection.find_one({'_id': result.inserted_id})
        
        if created_alert:
            print(f"Alert created successfully with settings:")
            print(f"- use_phone: {created_alert.get('use_phone')}")
            print(f"- phone_number: {created_alert.get('phone_number')}")
            print(f"- phone_verified: {created_alert.get('phone_verified')}")
            print(f"- phone_carrier: {created_alert.get('phone_carrier')}")
            print(f"- active: {created_alert.get('active')}")
            print(f"- status: {created_alert.get('status')}")
            print(f"- notified: {created_alert.get('notified')}")
        
        # Return the created alert ID and status
        return jsonify({
            'message': 'Alert added successfully', 
            'crn': crn, 
            'term': term_code,
            'use_phone': use_phone,
            'phone_available': bool(user_phone_number and user_phone_verified),
            'alert_id': str(result.inserted_id)
        }), 201
    except Exception as e:
        print(f"Error in add_alert: {str(e)}")
        return jsonify({'error': f"An error occurred: {str(e)}"}), 500

@app.route('/api/emails', methods=['GET'])
def get_emails():
    """API endpoint to get all registered emails"""
    emails = list(email_collection.find({'active': True}, {'_id': 0}))
    return jsonify(emails), 200

@app.route('/api/alerts/delete', methods=['DELETE'])
def delete_alert():
    '''API endpoint to permenantly delete a CRN alert.'''
    data = request.json
    if not data or 'crn' not in data or 'email' not in data:
        return jsonify({'error': 'CRN and Email are required'}), 400
    crn = str(data['crn'])
    term_code = str(data.get('term', '202531'))
    raw_email = data['email']
    clean_email = normalize_email(raw_email)
    print(crn, term_code, raw_email, clean_email)
    try:
        result = collection.delete_many({
            'CRN': crn,
            'Term': term_code,
            'email': clean_email
        })
        
        if result.deleted_count == 0:
            return jsonify({'message': 'No alert found to delete'}), 404
        return jsonify({'message': 'Alert permanently deleted'}), 200
    except Exception as e:
        print(f"Error in delete_alert_hard: {str(e)}")
        return jsonify({'error': f"An error occurred: {str(e)}"}), 500
        

@app.route('/api/alerts/by-email/<email>', methods=['GET'])
def get_alerts_by_email(email):
    """API endpoint to get all alerts for a specific email"""
    # Normalize the email
    normalized_email = normalize_email(email)
    print(f"Getting alerts for email - Raw: {email}, Normalized: {normalized_email}")
    
    alerts = list(collection.find({'email': normalized_email, 'active': True}, {'_id': 0}))
    print(f"Found {len(alerts)} alerts for {normalized_email}")
    return jsonify(alerts), 200

@app.route('/api/alerts', methods=['GET'])
def get_alerts():
    """API endpoint to get all active alerts"""
    alerts = list(collection.find({'active': True}, {'_id': 0}))
    return jsonify(alerts), 200

def run_flask():
    """Run the Flask API server"""
    app.run(host='0.0.0.0', port=5001, debug=False)

async def monitor_crns(interval=60):
    """
    Continuously monitor all CRNs in the database
    
    Args:
        interval: Time in seconds between checks
    """
    global running
    
    try:
        print(f"Starting continuous monitoring of all CRNs in database")
        print(f"Checking every {interval} seconds. Press Ctrl+C to stop.")
        
        # Track when we last fetched class data
        last_fetch_time = 0
        cached_availability = None
        
        while running:
            # Get all active CRNs from MongoDB
            active_alerts = list(collection.find({'active': True}))
            
            if not active_alerts:
                print("No active CRNs to monitor. Waiting...")
                await asyncio.sleep(interval)
                continue
            
            current_time = time.time()
            
            # Get the availability for all terms - only fetch new class data if it's been more than the interval time
            if current_time - last_fetch_time >= interval or cached_availability is None:
                print(f"Fetching fresh class data (interval: {interval}s)")
                cached_availability = api.get_availability()
                last_fetch_time = current_time
            else:
                print(f"Using cached class data ({int(current_time - last_fetch_time)}s since last fetch)")
            
            # Use the cached availability data
            availability = cached_availability
            timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
            
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
                previous_status = alert.get('status', False)
                
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
                            term_name = api.term_codes_to_desc.get(term, f"Term {term}")
                            body += f"CRN: {crn} (Term: {term_name}) is now AVAILABLE!\n"
                        
                        body += "\nPlease log in to register as soon as possible as spaces may fill quickly.\n\n"
                        body += "Thank you for using Aggie Class Alert!"
                        
                        # Look up user data to get phone details if available
                        user_data = None
                        try:
                            user_data = users_collection.find_one({'email': email})
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
                        
                        # SIMPLIFIED EMAIL SENDING
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
                            
                            # Send using SSL
                            smtp_server = "smtp.gmail.com"
                            port = 465  # Using SSL
                            
                            import smtplib
                            with smtplib.SMTP_SSL(smtp_server, port) as server:
                                server.login(sender_email, password)
                                server.send_message(msg)
                                
                                # If we have an SMS recipient, send a second email to the SMS gateway
                                if sms_recipient:
                                    # Create more concise content for SMS
                                    sms_content = "Aggie Class Alert: "
                                    
                                    # Add CRNs to the message
                                    crn_list = [alert['crn'] for alert in available_crns]
                                    if len(crn_list) == 1:
                                        sms_content += f"CRN {crn_list[0]} is available"
                                    else:
                                        # For multiple CRNs, list each one on a separate line
                                        sms_content += "\n".join([f"CRN {crn} is available" for crn in crn_list])
                                    
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

def run():
    # Set up command line arguments
    parser = argparse.ArgumentParser(description='Run the AggieClassAlert backend server.')
    parser.add_argument('--port', type=int, default=5001, help='Port to run the server on')
    parser.add_argument('--host', type=str, default='0.0.0.0', help='Host to run the server on')
    parser.add_argument('--debug', action='store_true', help='Run in debug mode')
    parser.add_argument('--no-monitor', action='store_true', help='Disable monitoring thread')
    args = parser.parse_args()
    
    # Print information
    print(f"Starting AggieClassAlert backend server on {args.host}:{args.port}")
    
    # Start monitoring thread if not disabled
    if not args.no_monitor:
        monitor_thread = threading.Thread(target=asyncio.run, args=(monitor_crns(),))
        monitor_thread.daemon = True
        monitor_thread.start()
        print("Monitoring thread started")
    
    # Print all registered routes
    print("\n===== REGISTERED ROUTES =====")
    for rule in app.url_map.iter_rules():
        print(f"{rule.endpoint}: {rule.methods} - {rule}")
    print("=============================\n")
    
    # Run Flask app
    app.run(host=args.host, port=args.port, debug=args.debug)

@app.route('/api/users/login', methods=['POST'])
def login_user():
    """API endpoint to login or register a user by email"""
    print("================================================")
    print("LOGIN ENDPOINT CALLED - " + time.strftime("%Y-%m-%d %H:%M:%S"))
    print("================================================")
    
    data = request.json
    print(f"Received data: {data}")
    
    if not data or 'email' not in data:
        print("Error: Email is required but not provided")
        return jsonify({'error': 'Email is required', 'success': False}), 400
    
    raw_email = data['email']
    is_google_auth = data.get('google_auth', False)
    google_user_data = data.get('user_data', {})
    original_email = data.get('original_email', raw_email)
    
    if is_google_auth:
        print(f"Google Auth login detected for {raw_email}")
    
    # Normalize the email address before processing
    email = normalize_email(raw_email)
    print(f"Raw email: {raw_email}")
    print(f"Original email: {original_email}")
    print(f"Normalized email: {email}")
    
    # Validate email format
    if '@' not in email:
        print("Error: Invalid email format")
        return jsonify({'error': 'Invalid email format', 'success': False}), 400
    
    try:
        print(f"Processing login for email: {email} (raw: {raw_email})")
        
        # Find or create user
        print(f"Checking if user exists in database with email: {email}")
        existing_users = list(users_collection.find({'email': email}))
        print(f"Found {len(existing_users)} matching users")
        
        user = users_collection.find_one({'email': email})
        
        if not user:
            # Create new user
            print(f"User not found, creating new user with email: {email}")
            user = {
                'email': email,
                'original_email': original_email,  # Store the original email for reference
                'created_at': time.time(),
                'last_login': time.time(),
                'is_google_auth': is_google_auth,
                'phone_number': None,  # Initialize phone fields
                'phone_verified': False,
                'phone_carrier': None,
                'phone_verified_at': None
            }
            
            # Add Google Auth data if available
            if is_google_auth and google_user_data:
                user['google_auth_data'] = google_user_data
                # Extract useful fields from Google data
                if 'name' in google_user_data:
                    user['name'] = google_user_data.get('name')
                if 'picture' in google_user_data:
                    user['profile_picture'] = google_user_data.get('picture')
            
            try:
                # Force insert
                users_collection.delete_one({'email': email})  # Delete any existing record (shouldn't exist)
                result = users_collection.insert_one(user)
                user_id = str(result.inserted_id)
                print(f"New user created successfully. Insert result: {user_id}")
            except Exception as insert_err:
                print(f"Error inserting new user: {str(insert_err)}")
                import traceback
                traceback.print_exc()
                
                # Don't raise the error, attempt to proceed anyway
                print("Continuing despite error...")
        else:
            # Update last login time
            print(f"User found, updating last login time for: {email}")
            try:
                update_data = {
                    'last_login': time.time(),
                }
                
                # Update original_email if it doesn't exist
                if 'original_email' not in user:
                    update_data['original_email'] = original_email
                
                # Ensure phone fields exist
                if 'phone_number' not in user:
                    update_data['phone_number'] = None
                if 'phone_verified' not in user:
                    update_data['phone_verified'] = False
                if 'phone_carrier' not in user:
                    update_data['phone_carrier'] = None
                if 'phone_verified_at' not in user:
                    update_data['phone_verified_at'] = None
                
                # Update Google Auth flags if applicable
                if is_google_auth:
                    update_data['is_google_auth'] = True
                    if google_user_data:
                        update_data['google_auth_data'] = google_user_data
                        # Extract useful fields from Google data
                        if 'name' in google_user_data:
                            update_data['name'] = google_user_data.get('name')
                        if 'picture' in google_user_data:
                            update_data['profile_picture'] = google_user_data.get('picture')
                
                result = users_collection.update_one(
                    {'email': email},
                    {'$set': update_data}
                )
                print(f"Update result: {result.modified_count} documents modified")
            except Exception as update_err:
                print(f"Error updating user: {str(update_err)}")
                import traceback
                traceback.print_exc()
                # Continue despite error
        
        # Get the most up-to-date user data
        current_user = users_collection.find_one({'email': email})
        print(f"Current user data: {current_user}")
        
        # Verify one last time
        all_users = list(users_collection.find({}))
        print(f"Total users in database: {len(all_users)}")
        
        # Also make sure this user is in the email collection for alerts
        try:
            email_doc = email_collection.find_one({'email': email})
            if not email_doc:
                email_collection.insert_one({
                    'email': email,
                    'original_email': original_email,
                    'created_at': time.time(),
                    'active': True,
                    'is_google_auth': is_google_auth
                })
                print(f"Added user to email collection: {email}")
        except Exception as email_err:
            print(f"Error adding to email collection: {str(email_err)}")
        
        # Include phone information in the response if available
        response_data = {
            'message': 'Login successful',
            'email': email,
            'original_email': original_email,
            'created_at': current_user.get('created_at') if current_user else time.time(),
            'is_google_auth': is_google_auth,
            'success': True
        }
        
        # Add phone verification status if available
        if current_user and current_user.get('phone_number'):
            response_data['phone_number'] = current_user.get('phone_number')
            response_data['phone_verified'] = current_user.get('phone_verified', False)
        
        print("Login successful!")
        return jsonify(response_data), 200
        
    except Exception as e:
        print(f"Error in login: {str(e)}")
        import traceback
        traceback.print_exc()
        
        # Try to create user one more time as a last resort
        try:
            emergency_user = {
                'email': email,
                'original_email': original_email,
                'created_at': time.time(),
                'last_login': time.time(),
                'emergency_creation': True,
                'is_google_auth': is_google_auth,
                'phone_number': None,
                'phone_verified': False,
                'phone_carrier': None,
                'phone_verified_at': None
            }
            users_collection.insert_one(emergency_user)
            print("Emergency user creation attempted")
            
            return jsonify({
                'message': 'Login successful (emergency mode)',
                'email': email,
                'original_email': original_email,
                'is_google_auth': is_google_auth,
                'success': True
            }), 200
            
        except Exception as emergency_err:
            print(f"Emergency user creation also failed: {str(emergency_err)}")
            return jsonify({'error': f"An error occurred: {str(e)}", 'success': False}), 500

@app.route('/api/users/check/<email>', methods=['GET'])
def check_user(email):
    """API endpoint to check if a user exists"""
    try:
        # Normalize the email before checking
        normalized_email = normalize_email(email)
        print(f"Checking if user exists - Raw: {email}, Normalized: {normalized_email}")
        
        user = users_collection.find_one({'email': normalized_email})
        if user:
            print(f"User found with email: {normalized_email}")
            return jsonify({
                'exists': True,
                'email': normalized_email,
                'original_email': user.get('original_email', normalized_email)
            }), 200
        else:
            print(f"User not found with email: {normalized_email}")
            return jsonify({
                'exists': False
            }), 200
    except Exception as e:
        print(f"Error checking user: {str(e)}")
        return jsonify({'error': f"An error occurred: {str(e)}"}), 500

# Handle OPTIONS requests for user endpoints
@app.route('/api/users/login', methods=['OPTIONS'])
def handle_login_options():
    return '', 200

@app.route('/api/users/check/<email>', methods=['OPTIONS'])
def handle_users_check_options(email):
    return '', 200

@app.route('/api/professors/search', methods=['GET'])
def search_professors():
    """API endpoint to search for professors with the best GPAs for a given department and course code"""
    department = request.args.get('department', '')
    course_code = request.args.get('course_code', '')
    
    # Print a clear header showing this endpoint was called
    print("\n\n")
    print("#" * 100)
    print("#" + " " * 98 + "#")
    print("#" + f" PROFESSOR SEARCH STARTED: {department} {course_code} - {time.strftime('%Y-%m-%d %H:%M:%S')}".center(98) + "#")
    print("#" + " " * 98 + "#")
    print("#" * 100)
    
    if not department or not course_code:
        return jsonify({'error': 'Department and course code are required'}), 400
    
    try:
        # Find Fall 2025 term code
        fall_term_code = None
        for term in api.terms:
            if "Fall" in term['STVTERM_DESC']:
                fall_term_code = term['STVTERM_CODE']
                print(f"Found Fall term: {term['STVTERM_DESC']} ({fall_term_code})")
                break
                
        if not fall_term_code:
            print("Warning: Could not find Fall term, using first available term")
            fall_term_code = api.terms[0]['STVTERM_CODE'] if api.terms else None
        
        # Use the anex module to find professors
        professors_data = anex.find_profs(department, course_code)
        
        # Helper function to extract last name properly
        def extract_last_name(name):
            # Handle special cases like "LAST F"
            if re.match(r'^[A-Z]+\s+[A-Z]$', name):
                # This matches the format "LAST F"
                return name.split()[0]
            
            # For other formats, get the last part of the name
            # Handle hyphenated last names by considering the entire last token
            parts = name.split()
            if parts:
                return parts[-1]
            return name

        # Extract all last names from historical professors data
        historical_last_names = {}
        for prof_name in professors_data.keys():
            last_name = extract_last_name(prof_name)
            historical_last_names[prof_name] = last_name.lower()  # Store lowercase for easier comparison
            print(f"Historical professor: {prof_name}, extracted last name: {last_name}")
        
        # Dictionary to track all instructors found in current sections
        current_instructors = {}
        
        # Ensure proper formatting with a space between department and course code
        course_string = f"{department} {course_code}"
        print(f"Using formatted course string: '{course_string}'")
        
        # Step 1: First extract all the instructors from sections
        if fall_term_code:
            try:
                print(f"Attempting to get sections for {course_string} in term {fall_term_code}")
                # Validate course format to ensure it matches the expected pattern
                if not re.match(r'^[A-Z]{2,4} \d{3}$', course_string):
                    print(f"⚠️ Warning: Course string '{course_string}' may not match expected format 'DEPT ###'")
                
                # Make sure the API is properly initialized for this term
                if hasattr(api, 'classes') and fall_term_code in api.classes and api.classes[fall_term_code]:
                    print(f"Using cached class data for term {fall_term_code}")
                else:
                    print(f"Loading classes for term {fall_term_code}")
                    # Ensure classes are loaded for this term
                    api.get_classes(fall_term_code)
                
                # Get filtered course sections
                sections = api.filter_by_course("202531", course_string)
                print(f"Found {len(sections)} sections for {course_string} in upcoming semester")
                
                # Simple, direct approach to extract instructors from each section
                print("\n===== DIRECT EXTRACTION OF INSTRUCTORS FROM SECTIONS =====")
                for section in sections:
                    section_number = section.get('SWV_CLASS_SEARCH_SECTION', '')
                    crn = section.get('SWV_CLASS_SEARCH_CRN', '')
                    
                    # Try to get instructor JSON
                    instructor_json_str = section.get('SWV_CLASS_SEARCH_INSTRCTR_JSON', None)
                    
                    if instructor_json_str:
                        print(f"Section {section_number} (CRN {crn}) - Found instructor JSON: {instructor_json_str}")
                        
                        # Try to extract with regex
                        if isinstance(instructor_json_str, str):
                            matches = re.findall(r'"NAME"\s*:\s*"([^"]+)"', instructor_json_str)
                            for match in matches:
                                full_name = match.replace(' (P)', '')
                                last_name = extract_last_name(full_name).lower()
                                
                                print(f"✓ Found instructor (via regex): {full_name}, Last name: {last_name}")
                                
                                # Add to current instructors
                                current_instructors[full_name] = {
                                    'full_name': full_name,
                                    'last_name': last_name,
                                    'section': section_number,
                                    'crn': crn,
                                    'term_code': fall_term_code,
                                    'term_desc': api.term_codes_to_desc.get(fall_term_code, '')
                                }
                
                print(f"\nExtracted {len(current_instructors)} instructors from {len(sections)} sections")
                
                # DIRECT DEBUG OUTPUT - Print every section with all fields to see the raw data
                print("\n===== RAW SECTION DATA DUMP (FIRST 3 SECTIONS) =====")
                for i, section in enumerate(sections[:3]):
                    print(f"SECTION {i+1}: CRN {section.get('SWV_CLASS_SEARCH_CRN', '')} - Section {section.get('SWV_CLASS_SEARCH_SECTION', '')}")
                    for key, value in sorted(section.items()):
                        if 'INSTRUCTOR' in key.upper() or 'FACULTY' in key.upper() or 'PROF' in key.upper() or 'TEACHER' in key.upper():
                            print(f"  !!! {key}: {value}")
                        else:
                            print(f"  {key}: {value}")
                
                # Add a detailed inspection of the first section to debug
                if sections and len(sections) > 0:
                    print("\n===== DETAILED SECTION DATA INSPECTION =====")
                    first_section = sections[0]
                    print(f"First section keys: {sorted(first_section.keys())}")
                    
                    # Check for instructor-related fields
                    instructor_related_keys = [key for key in first_section.keys() 
                                              if 'INSTRUCT' in key.upper() or 'FACULTY' in key.upper() or 'PROF' in key.upper()]
                    
                    if instructor_related_keys:
                        print(f"Found instructor-related fields: {instructor_related_keys}")
                        for key in instructor_related_keys:
                            print(f"  {key}: {first_section.get(key)}")
                    else:
                        print("No instructor-related fields found in section data")
                    
                    # Print all fields of the first section for detailed inspection
                    print("\nAll fields of first section:")
                    for key, value in sorted(first_section.items()):
                        print(f"  {key}: {value}")
                    print("=" * 40)
                
                # Process instructor information from sections
                for section in sections:
                    section_number = section.get('SWV_CLASS_SEARCH_SECTION', '')
                    crn = section.get('SWV_CLASS_SEARCH_CRN', '')
                    
                    # Try multiple possible field names for instructor data
                    instructor_json_str = None
                    tried_fields = []
                    
                    for field in ['SWV_CLASS_SEARCH_INSTRCTR_JSON', 'INSTRCTR_JSON', 'INSTRUCTOR_JSON', 'SWV_INSTRCTR', 'INSTRUCTOR']:
                        tried_fields.append(field)
                        if field in section and section[field]:
                            instructor_json_str = section[field]
                            print(f"Found instructor data in field '{field}' for section {section_number}")
                            break
                    
                    if not instructor_json_str:
                        print(f"No instructor data found in section {section_number} (CRN {crn}). Tried fields: {', '.join(tried_fields)}")
                        
                        # Fallback: Search through all fields for any value that looks like a person's name
                        print(f"Searching through all fields for potential instructor names in section {section_number}...")
                        
                        # Look for keys that have "instructor" or similar in their name
                        potential_instructor_fields = [k for k in section.keys() 
                                                     if ('INSTRUCT' in k.upper() or 'PROF' in k.upper() or 'FACULTY' in k.upper() or 'TEACHER' in k.upper())]
                        
                        # Look through all fields that contain text and have space and capitalization pattern of names
                        for field, value in section.items():
                            if isinstance(value, str) and ' ' in value:
                                # Check if it looks like a name (has multiple words with capital letters)
                                words = value.split()
                                if len(words) >= 2 and all(w[0].isupper() for w in words if w):
                                    print(f"Found potential instructor name in field '{field}': {value}")
                                    potential_instructor_fields.append(field)
                        
                        for field in potential_instructor_fields:
                            value = section.get(field)
                            if value and isinstance(value, str):
                                # Try to parse it as an instructor name
                                name = value.strip()
                                # Remove (P) designation if present
                                name = name.replace(' (P)', '')
                                
                                if name and ' ' in name:  # Must have at least two parts (first and last name)
                                    instructor_last_name = extract_last_name(name).lower()
                                    print(f"→ Section {section_number} (CRN {crn}): Extracted potential instructor '{name}' from field '{field}', last name: '{instructor_last_name}'")
                                    
                                    # Store in a dictionary for easy lookup
                                    current_instructors[name] = {
                                        'full_name': name,
                                        'last_name': instructor_last_name,
                                        'section': section_number,
                                        'crn': crn,
                                        'term_code': fall_term_code,
                                        'term_desc': api.term_codes_to_desc.get(fall_term_code, ''),
                                        'extraction_method': 'field_analysis',
                                        'source_field': field
                                    }
                        
                        # If we still didn't find anything, continue to the next section
                        if not instructor_json_str:
                            continue
                    
                    # If we have a JSON string to process, let's do that
                    try:
                        # Make sure we have proper JSON - handle both string and object
                        if isinstance(instructor_json_str, str):
                            try:
                                # For JSON strings like: "[{\"NAME\":\"Sandeep Kumar (P)\",\"MORE\":2938931,\"HAS_CV\":\"Y\"}]"
                                # Need to handle escaped quotes properly
                                instructor_json_str = instructor_json_str.replace('\\"', '"')
                                
                                # If the string is already wrapped in quotes from the API response, remove them
                                if instructor_json_str.startswith('"') and instructor_json_str.endswith('"'):
                                    instructor_json_str = instructor_json_str[1:-1]
                                    
                                print(f"Cleaned JSON string: {instructor_json_str}")
                                instructor_json = json.loads(instructor_json_str)
                                print(f"Successfully parsed JSON for Section {section_number}: {instructor_json}")
                            except json.JSONDecodeError as e:
                                print(f"ERROR parsing JSON for Section {section_number}: {e}")
                                print(f"Problematic JSON: {instructor_json_str}")
                                
                                # Try to directly extract instructor data from the string
                                # Looking for patterns like {"NAME":"David K. Houngninou (P)","MORE":939540,"HAS_CV":"Y"}
                                pattern = r'"NAME"\s*:\s*"([^"]+)"'
                                name_matches = re.findall(pattern, instructor_json_str)
                                
                                if name_matches:
                                    for raw_name in name_matches:
                                        print(f"Extracted instructor name from string: {raw_name}")
                                        
                                        # Remove (P) designation if present
                                        name = raw_name.replace(' (P)', '')
                                        
                                        if name:
                                            try:
                                                # Extract the last name from the instructor name
                                                instructor_last_name = extract_last_name(name).lower()
                                                
                                                print(f"→ Section {section_number} (CRN {crn}): Extracted instructor '{name}' from '{raw_name}', last name: '{instructor_last_name}'")
                                                
                                                # Store in a dictionary for easy lookup
                                                current_instructors[name] = {
                                                    'full_name': name,
                                                    'last_name': instructor_last_name,
                                                    'section': section_number,
                                                    'crn': crn,
                                                    'term_code': fall_term_code,
                                                    'term_desc': api.term_codes_to_desc.get(fall_term_code, ''),
                                                    'extraction_method': 'regex'
                                                }
                                            except Exception as e:
                                                print(f"Error processing instructor name '{name}': {e}")
                                instructor_json = []
                        else:
                            instructor_json = instructor_json_str
                        
                        # Debug - how many instructors found
                        print(f"Found {len(instructor_json)} instructors in section {section_number}")
                        
                        for i, instructor in enumerate(instructor_json):
                            # Debug - what's in each instructor object
                            print(f"Instructor {i+1} data: {instructor}")
                            
                            # Extract name and remove (P) designation if present
                            raw_name = instructor.get('NAME', '')
                            name = raw_name.replace(' (P)', '')
                            
                            if name:
                                # Extract the last name from the instructor name (format: "First Last")
                                instructor_last_name = extract_last_name(name).lower()
                                
                                print(f"→ Section {section_number} (CRN {crn}): Extracted instructor '{name}' from '{raw_name}', last name: '{instructor_last_name}'")
                                
                                # Store in a dictionary for easy lookup
                                current_instructors[name] = {
                                    'full_name': name,
                                    'last_name': instructor_last_name,
                                    'section': section_number,
                                    'crn': crn,
                                    'term_code': fall_term_code,
                                    'term_desc': api.term_codes_to_desc.get(fall_term_code, '')
                                }
                            else:
                                print(f"WARNING: Empty instructor name in section {section_number}")
                    except Exception as e:
                        print(f"Error processing instructor JSON for section {section_number}: {e}")
                        import traceback
                        traceback.print_exc()
            except Exception as e:
                print(f"Error getting current term sections: {e}")
        
        # Log all current instructors with a prominent indicator 
        print("\n")
        print("🔴🔴🔴 ALL LOGGED: ALL CURRENT INSTRUCTORS 🔴🔴🔴")
        print("=" * 80)
        print(f"Total current instructors found: {len(current_instructors)}")
        print(json.dumps({name: {"last_name": data['last_name'], "section": data['section'], "crn": data['crn']} 
                           for name, data in current_instructors.items()}, indent=2))
        print("=" * 80)
        print("🔴🔴🔴 END OF CURRENT INSTRUCTORS LOG 🔴🔴🔴\n")
        
        # Print a debug summary of the extracted names
        print("\n===== DEBUGGING NAME EXTRACTION =====")
        print(f"Historical professors last names ({len(historical_last_names)}):")
        for full_name, last_name in historical_last_names.items():
            print(f"  {full_name} -> {last_name}")
        
        print(f"\nCurrent section instructors ({len(current_instructors)}):")
        for full_name, data in current_instructors.items():
            print(f"  {full_name} -> {data['last_name']}")
 
        # Create simplified lists of just the last names for easier matching
        historical_last_names_list = list(set(last_name for _, last_name in historical_last_names.items()))
        current_last_names_list = list(set(data['last_name'] for _, data in current_instructors.items()))
        
        print(f"\nSimplified historical last names ({len(historical_last_names_list)}):")
        print(f"  {', '.join(sorted(historical_last_names_list))}")
        
        print(f"\nSimplified current last names ({len(current_last_names_list)}):")
        print(f"  {', '.join(sorted(current_last_names_list))}")
        
        # Step 2: Now do the matching between historical professors and current instructors
        matches = []
        print("\n===== CHECKING ALL POSSIBLE MATCHES =====")
        
        # Track which historical professors have been matched
        matched_historical_professors = set()
        
        # First check which historical last names match with any current last name
        matching_last_names = set()
        for hist_last in historical_last_names_list:
            matches_found = False
            for curr_last in current_last_names_list:
                if hist_last == curr_last:
                    matching_last_names.add(hist_last)
                    matches_found = True
            
            match_indicator = "✓" if matches_found else "❌"
            print(f"{match_indicator} Historical last name '{hist_last}' found in current instructors: {matches_found}")
        
        # Then match the specific professors
        for hist_name, hist_last in historical_last_names.items():
            # Check if this professor's last name is in the matching last names set
            if hist_last in matching_last_names:
                # Find all current instructors with this last name
                matching_instructors = [(curr_name, curr_data) for curr_name, curr_data in current_instructors.items() 
                                        if curr_data['last_name'] == hist_last]
                
                if matching_instructors:
                    matched_historical_professors.add(hist_name)
                    
                    for curr_name, curr_data in matching_instructors:
                        matches.append({
                            'historical_name': hist_name,
                            'historical_last': hist_last,
                            'current_name': curr_name, 
                            'current_last': curr_data['last_name'],
                            'section': curr_data['section'],
                            'crn': curr_data['crn']
                        })
                    
                    print(f"✓ {hist_name} ({hist_last}) matched with {len(matching_instructors)} current instructor(s)")
                    for curr_name, curr_data in matching_instructors:
                        print(f"   - {curr_name} ({curr_data['last_name']}) Section: {curr_data['section']}, CRN: {curr_data['crn']}")
                else:
                    print(f"⚠️ No instructors found with last name '{hist_last}' (unexpected)")
            else:
                print(f"❌ {hist_name} ({hist_last}) - No matching current instructors")
        
        # Log all matches with a prominent indicator
        print("\n")
        print("🔴🔴🔴 ALL LOGGED: INITIAL MATCHES ARRAY 🔴🔴🔴")
        print("=" * 80)
        print(f"Total matches: {len(matches)}")
        print(json.dumps(matches, indent=2))
        print("=" * 80)
        print("🔴🔴🔴 END OF MATCHES ARRAY LOG 🔴🔴🔴\n")
        
        # For debugging purposes, check which historical professors were not matched
        unmatched_professors = []
        for hist_name in historical_last_names:
            if hist_name not in matched_historical_professors:
                unmatched_professors.append(hist_name)
        
        if unmatched_professors:
            print(f"\n⚠️ The following {len(unmatched_professors)} historical professors weren't matched to any section:")
            for name in unmatched_professors:
                print(f"  - {name} (last name: {historical_last_names[name]})")
                
        print(f"Found {len(matches)} total matches out of {len(historical_last_names)} historical professors")
        print("=====================================\n")
        
        # Print a consolidated list of matched last names for easier debugging
        print("\n===== MATCHED LAST NAMES =====")
        matched_last_names = set()
        for match in matches:
            matched_last_names.add(match['historical_last'])
        
        print("List of last names that matched:")
        for last_name in sorted(matched_last_names):
            print(f"  - {last_name}")
            
        print("\nDetailed matches by last name:")
        for last_name in sorted(matched_last_names):
            print(f"  Last name: {last_name.upper()}")
            for match in matches:
                if match['historical_last'] == last_name:
                    print(f"    ✓ {match['historical_name']} <-> {match['current_name']} (Section {match['section']}, CRN {match['crn']})")
        
        # Log matched_historical_professors with a prominent indicator
        print("\n")
        print("🔴🔴🔴 ALL LOGGED: MATCHED HISTORICAL PROFESSORS 🔴🔴🔴")
        print("=" * 80)
        print(f"Total matched professors: {len(matched_historical_professors)}")
        print(json.dumps(list(matched_historical_professors), indent=2))
        print("=" * 80)
        print("🔴🔴🔴 END OF MATCHED PROFESSORS LOG 🔴🔴🔴\n")
        
        print("!" * 80)
        print("\n")
        
        # Format the data for frontend
        formatted_professors = []
        
        for prof_name, data in professors_data.items():
            overall_gpa = data['overall']
            regular_gpa = data['regular']
            honors_gpa = data['honors']
            #isGalveston
            
            # Check if professor is teaching in the upcoming semester
            # A professor is teaching if they're in the matched_historical_professors set
            teaching_next_term = prof_name in matched_historical_professors
            teaching_info = None
            matched_current_name = ""
            
            # Extract last name from historical data format
            hist_last_name = historical_last_names[prof_name]
            
            # If teaching next term, find the matching instructor information
            if teaching_next_term:
                # Store all matched current names to check multiple instructor variations
                matched_current_names = []
                
                # Look through all matches to find ALL matches for this professor
                for match in matches:
                    if match['historical_name'] == prof_name:
                        # Store every match we find, not just the first one
                        matched_current_names.append(match['current_name'])
                        # Still use the first one for the teaching_info field
                        if not teaching_info:
                            matched_current_name = match['current_name']
                            teaching_info = current_instructors[match['current_name']]
            
            # Get RateMyProfessor data
            rmp_data = {
                "overall_rating": None,
                "would_take_again": None, 
                "difficulty": None,
                "comments": {},
                "found": False
            }
            
            # Only check RMP for professors who are actually teaching next term
            if teaching_next_term and RMP_AVAILABLE:
                try:
                    print(f"\n===== GETTING RMP DATA for {prof_name} ({hist_last_name}) =====")
                    rmp_data = RMP.get_professor_rating(hist_last_name, department)
                    print(f"RMP data for {prof_name} ({hist_last_name}): {rmp_data}")
                except Exception as rmp_err:
                    print(f"Error getting RMP data for {prof_name}: {rmp_err}")
            elif not teaching_next_term:
                print(f"Skipping RMP data for {prof_name} - not teaching next term")
            else:
                print(f"Skipping RMP data for {prof_name} - module not available")
            
            professor = {
                'name': prof_name,
                'average_gpa': round(overall_gpa, 2),
                'regular_gpa': round(regular_gpa, 2) if data['has_regular'] else None,
                'honors_gpa': round(honors_gpa, 2) if data['has_honors'] else None,
                'has_regular': data['has_regular'],
                'has_honors': data['has_honors'],
                'regular_count': data['regular_count'],
                'honors_count': data['honors_count'],
                'department': department,
                'courses': [f"{department} {course_code}"],
                'teaching_next_term': teaching_next_term,
                'last_name': hist_last_name,
                'matched_with': matched_current_name if teaching_next_term else "",
                # Add RateMyProfessor data
                'rmp_rating': rmp_data['overall_rating'],
                'rmp_would_take_again': rmp_data['would_take_again'], 
                'rmp_difficulty': rmp_data['difficulty'],
                'rmp_comments': rmp_data['comments'],
                'rmp_found': rmp_data['found']
            }
            
            # Add teaching info if available
            if teaching_next_term and teaching_info:
                professor.update({
                    'section': teaching_info.get('section', ''),
                    'crn': teaching_info.get('crn', ''),
                    'term_code': teaching_info.get('term_code', ''),
                    'term_desc': teaching_info.get('term_desc', '')
                })
                
                # COLLECT ALL SECTIONS FOR THIS PROFESSOR
                # Start fresh with an empty array of sections
                professor_sections = []
                
                # First, gather the professor's last name(s) to check against all sections
                professor_last_names = set()
                professor_last_names.add(hist_last_name)  # Add the historical last name
                
                # Also add all last names from matched current instructors
                if matched_current_names:
                    for curr_name in matched_current_names:
                        if curr_name in current_instructors:
                            professor_last_names.add(current_instructors[curr_name]['last_name'])
                
                print(f"\n===== COLLECTING ALL SECTIONS FOR PROFESSOR: {prof_name} =====")
                print(f"Checking for sections with last names: {', '.join(sorted(professor_last_names))}")
                
                # DIRECT APPROACH: Check all sections from the API response
                if 'sections' in locals() and sections:
                    print("Checking all API sections for matching instructors...")
                    
                    for section in sections:
                        section_number = section.get('SWV_CLASS_SEARCH_SECTION', '')
                        crn = section.get('SWV_CLASS_SEARCH_CRN', '')
                        
                        # Skip if this section is already in our list
                        if any(ps['section'] == section_number for ps in professor_sections):
                            continue
                        
                        # Check if this section has our professor
                        instructor_json_str = section.get('SWV_CLASS_SEARCH_INSTRCTR_JSON', None)
                        if instructor_json_str:
                            instructor_found = False
                            
                            # Parse instructor JSON if needed
                            try:
                                # Handle both string and object formats
                                instructors = []
                                if isinstance(instructor_json_str, str):
                                    # Clean up JSON string and parse it
                                    cleaned_json = instructor_json_str.replace('\\"', '"')
                                    if cleaned_json.startswith('"') and cleaned_json.endswith('"'):
                                        cleaned_json = cleaned_json[1:-1]
                                    instructors = json.loads(cleaned_json)
                                    if not isinstance(instructors, list):
                                        instructors = [instructors]
                                else:
                                    # Direct object
                                    if isinstance(instructor_json_str, list):
                                        instructors = instructor_json_str
                                    else:
                                        instructors = [instructor_json_str]
                                
                                # Check each instructor in this section
                                for instructor in instructors:
                                    if 'NAME' in instructor:
                                        instructor_name = instructor['NAME'].replace(' (P)', '')
                                        instructor_last_name = extract_last_name(instructor_name).lower()
                                        
                                        # Check if this instructor matches our professor
                                        if instructor_last_name in professor_last_names:
                                            print(f"  ✓ Found match in section {section_number}: {instructor_name} (last name: {instructor_last_name})")
                                            
                                            # Extract meeting time information if available
                                            meeting_info = []
                                            try:
                                                if section.get('SWV_CLASS_SEARCH_JSON_CLOB'):
                                                    meeting_json = section.get('SWV_CLASS_SEARCH_JSON_CLOB')
                                                    if isinstance(meeting_json, str):
                                                        meeting_json = json.loads(meeting_json)
                                                    
                                                    if isinstance(meeting_json, list):
                                                        for meeting in meeting_json:
                                                            # Build day string
                                                            days = []
                                                            if meeting.get('SSRMEET_MON_DAY'): days.append('M')
                                                            if meeting.get('SSRMEET_TUE_DAY'): days.append('T')
                                                            if meeting.get('SSRMEET_WED_DAY'): days.append('W')
                                                            if meeting.get('SSRMEET_THU_DAY'): days.append('R')
                                                            if meeting.get('SSRMEET_FRI_DAY'): days.append('F')
                                                            if meeting.get('SSRMEET_SAT_DAY'): days.append('S')
                                                            if meeting.get('SSRMEET_SUN_DAY'): days.append('U')
                                                            
                                                            meeting_info.append({
                                                                'days': ''.join(days) if days else 'N/A',
                                                                'start_time': meeting.get('SSRMEET_BEGIN_TIME', 'N/A'),
                                                                'end_time': meeting.get('SSRMEET_END_TIME', 'N/A'),
                                                                'building': meeting.get('SSRMEET_BLDG_CODE', 'N/A'),
                                                                'room': meeting.get('SSRMEET_ROOM_CODE', 'N/A')
                                                            })
                                            except Exception as meeting_err:
                                                print(f"Error extracting meeting info for section {section_number}: {meeting_err}")
                                            
                                            section_info = {
                                                'section': section_number,
                                                'crn': crn,
                                                'meetings': meeting_info if meeting_info else None,
                                                'is_available': section.get('STUSEAT_OPEN', 'N') == 'Y'
                                            }
                                            
                                            professor_sections.append(section_info)
                                            instructor_found = True
                                            break
                            except Exception as e:
                                # Try regex as fallback if JSON parsing fails
                                try:
                                    pattern = r'"NAME"\s*:\s*"([^"]+)"'
                                    name_matches = re.findall(pattern, instructor_json_str if isinstance(instructor_json_str, str) else str(instructor_json_str))
                                    
                                    for raw_name in name_matches:
                                        instructor_name = raw_name.replace(' (P)', '')
                                        instructor_last_name = extract_last_name(instructor_name).lower()
                                        
                                        # Check if this instructor matches our professor
                                        if instructor_last_name in professor_last_names:
                                            print(f"  ✓ Found match in section {section_number} (via regex): {instructor_name} (last name: {instructor_last_name})")
                                            
                                            # Extract meeting time information if available
                                            meeting_info = []
                                            try:
                                                if section.get('SWV_CLASS_SEARCH_JSON_CLOB'):
                                                    meeting_json = section.get('SWV_CLASS_SEARCH_JSON_CLOB')
                                                    if isinstance(meeting_json, str):
                                                        meeting_json = json.loads(meeting_json)
                                                    
                                                    if isinstance(meeting_json, list):
                                                        for meeting in meeting_json:
                                                            # Build day string
                                                            days = []
                                                            if meeting.get('SSRMEET_MON_DAY'): days.append('M')
                                                            if meeting.get('SSRMEET_TUE_DAY'): days.append('T')
                                                            if meeting.get('SSRMEET_WED_DAY'): days.append('W')
                                                            if meeting.get('SSRMEET_THU_DAY'): days.append('R')
                                                            if meeting.get('SSRMEET_FRI_DAY'): days.append('F')
                                                            if meeting.get('SSRMEET_SAT_DAY'): days.append('S')
                                                            if meeting.get('SSRMEET_SUN_DAY'): days.append('U')
                                                            
                                                            meeting_info.append({
                                                                'days': ''.join(days) if days else 'N/A',
                                                                'start_time': meeting.get('SSRMEET_BEGIN_TIME', 'N/A'),
                                                                'end_time': meeting.get('SSRMEET_END_TIME', 'N/A'),
                                                                'building': meeting.get('SSRMEET_BLDG_CODE', 'N/A'),
                                                                'room': meeting.get('SSRMEET_ROOM_CODE', 'N/A')
                                                            })
                                            except Exception as meeting_err:
                                                print(f"Error extracting meeting info for section {section_number}: {meeting_err}")
                                            
                                            section_info = {
                                                'section': section_number,
                                                'crn': crn,
                                                'meetings': meeting_info if meeting_info else None,
                                                'is_available': section.get('STUSEAT_OPEN', 'N') == 'Y'
                                            }
                                            
                                            professor_sections.append(section_info)
                                            instructor_found = True
                                            break
                                            break
                                except Exception as regex_err:
                                    print(f"Error trying to extract instructor via regex: {regex_err}")
                
                # Log summary of all found sections
                print(f"\nFound {len(professor_sections)} total sections for {prof_name}:")
                for i, section in enumerate(professor_sections):
                    print(f"  [{i+1}] Section {section['section']} (CRN: {section['crn']})")
                locations = ['ONRP', 'ACAD', 'ADAM', 'AEPM', 'AESH', 'AGLS', 'AGRL', 'ALLN', 'EQNB', 'BPCC', 'ANTH', 'ARTF', 'ARCB', 'ARCC', 'RNCH', 'BEAS', 'BEUT', 'BICH', 'BCC', 'BSBE', 'BSBW', 'BIZL', 'BLOC', 'BLTN', 'SCIC', 'BRIG', 'HRBB', 'BFC', 'BMSB', 'BTLR', 'CAIN', 'CPAT', 'CMAT', 'CVLB', 'CEN', 'CUSE', 'CCPG', 'CUP', 'CHEM', 'CHAN', 'CE', 'CLEM', 'CEL', 'COKE', 'COMM', 'CSC', 'CONC', 'INSC', 'DAVI', 'DRTY', 'DLH', 'CSA', 'DCAN', 'DUNN', 'EBRF', 'ETB', 'ANIN', 'EIC', 'ERLB', 'EPPR', 'EQCT', 'ESTI', 'LIBR', 'FERM', 'FGGH', 'FSLB', 'FOUN', 'FOWL', 'FOOD', 'FREE', 'GAIN', 'GSC', 'BPLM', 'GGB', 'GOLF', 'ODM', 'HAAS', 'HGLR', 'HALB', 'HARL', 'HECC', 'EDCT', 'HARR', 'HART', 'HEAT', 'HPCT', 'HLB', 'HELD', 'HEND', 'HOBB', 'HRCT', 'HTGH', 'HFSB', 'HOTA', 'HUGH', 'ODP', 'ILSB', 'ILCB', 'ILSQ', 'CHEN', 'RICH', 'LIND', 'KEAT', 'KIES', 'KSWT', 'KLCT', 'JJKB', 'KRUE', 'KYLE', 'LARR', 'LACY', 'ARCA', 'LECH', 'LEGE', 'LEON', 'LAAH', 'CYCL', 'MCFA', 'MCNW', 'MEOB', 'MEDL', 'GLAS', 'MSC', 'MILS', 'MIST', 'MPHY', 'KAMU', 'MOSE', 'MOSH', 'MASS', 'NGLE', 'NCTM', 'NEEL', 'WIND', 'NSPG', 'NMR', 'NFFL', 'O&M','OTRC', 'E.D.', 'OLSN', 'WCTC', 'PAV', 'PRPV', 'PISC', 'PGBG', 'PETR', 'PPGM', 'PLNT', 'OBSV', 'PHRL', 'POSC', 'PSNP', 'FARM', 'PRES', 'HOBG', 'PSYC', 'PRCH', 'REED', 'RDMC', 'REPR', 'REYN', 'OBSR', 'MSTC', 'RUDD', 'RDER', 'SCCT', 'SBSA', 'SPHADM', 'SPHCLS', 'SPHLAB', 'SCHU', 'SCTS', 'OMAR', 'STL', 'SSPG', 'SPEN', 'STCH', 'SREC', 'West Campus', 'TEAS', 'TEAG', 'TEES', 'TEEX', 'ELTC', 'TIGM', 'TIPS A', 'TIPS B', 'TIPS C', 'TIPS', 'AMSB', 'VMDL', 'AGCT', 'VMTF', 'THOM', 'TICK', 'TTIHQ', 'TURF', 'VMB3', 'VMCA', 'VIV2', 'VMSB', 'UNDE', 'UCPG', 'USB', 'UTAY', 'UCO', 'UEOA', 'FSSB', 'VAPA', 'VLAH', 'VMS', 'VMA', 'VRB', 'VSAH', 'VTH', 'PRVP', 'VIV3', 'LFB', 'WALT', 'WWTP', 'WCBA', 'WELL', 'WCFL', 'WCG', 'WHIT', 'WHTE', 'WFES', 'CLAC', 'WEB', 'TPBB', 'TPDB', 'TPPP', 'TPSP', 'YMCA', 'ZACH']

                if len(professor_sections) > 0 and professor_sections[0]['meetings']:
                    # Check if any meeting is in a College Station building
                    is_college_station = False
                    for meeting in professor_sections[0]['meetings']:
                        if meeting['building'] in locations:
                            is_college_station = True
                            break
                    professor['isGalveston'] = not is_college_station
                else:
                    # Default to Galveston if no meeting info available
                    professor['isGalveston'] = False

                # Add highlighted summary of all sections
                print("\n" + "*" * 80)
                print(f"SECTION SUMMARY FOR PROFESSOR: {prof_name}")
                print(f"Total Sections Found: {len(professor_sections)}")
                print("Sections:")
                for i, section in enumerate(professor_sections):
                    print(f"  [{i+1}] Section {section['section']} (CRN: {section['crn']})")
                print("*" * 80 + "\n")
                
                # Log professor_sections with a prominent indicator
                print("\n")
                print(f"🔴🔴🔴 ALL LOGGED: SECTIONS FOR PROFESSOR {prof_name} 🔴🔴🔴")
                print("=" * 80)
                print(f"Professor: {prof_name}")
                print(f"Historical Last Name: {hist_last_name}")
                print(f"Teaching Next Term: {teaching_next_term}")
                print(f"Total Sections Found: {len(professor_sections)}")
                print(json.dumps(professor_sections, indent=2))
                print("=" * 80)
                print("🔴🔴🔴 END OF PROFESSOR SECTIONS LOG 🔴🔴🔴\n")
                
                if len(professor_sections) > 0:
                    professor['courses'] = professor_sections
                
                # Skip professors with isGalveston set to true
                if professor.get('isGalveston', False):
                    print(f"Skipping Galveston professor: {prof_name}")
                    continue
                
                formatted_professors.append(professor)
        
        return jsonify({
            'professors': formatted_professors
        }), 200
        
    except Exception as e:
        print(f"Error searching for professors: {str(e)}")
        return jsonify({'error': f"An error occurred: {str(e)}"}), 500

@app.route('/api/status', methods=['GET'])
def get_status():
    """API endpoint to get the status of various modules and services"""
    try:
        status = {
            'server': 'running',
            'rmp_available': RMP_AVAILABLE,
            'api_version': '1.0',
            'modules': {
                'anex': True,  # anex is always available
                'rmp': RMP_AVAILABLE
            }
        }
        
        return jsonify(status), 200
        
    except Exception as e:
        print(f"Error checking status: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/status', methods=['OPTIONS'])
def handle_status_options():
    return '', 200

@app.route('/api/verify-phone', methods=['POST'])
def verify_phone():
    """API endpoint to send a verification code to a phone number via SMS gateway"""
    data = request.json
    
    if not data or 'phoneNumber' not in data or 'carrier' not in data:
        return jsonify({'error': 'Phone number and carrier are required'}), 400
    
    phone_number = data['phoneNumber']
    carrier_id = data['carrier']
    user_email = data.get('email', '')  # Get the user's email if provided
    
    # Validate email if provided
    if user_email and '@' not in user_email:
        return jsonify({'error': 'Invalid email format'}), 400
    
    # Normalize email if provided
    normalized_email = normalize_email(user_email) if user_email else ''
    
    # Validate phone number format (simple validation)
    if not phone_number or len(phone_number.replace(' ', '').replace('-', '').replace('(', '').replace(')', '')) < 10:
        return jsonify({'error': 'Invalid phone number format'}), 400
    
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
    
    if carrier_id not in carrier_domains:
        return jsonify({'error': 'Invalid carrier selected'}), 400
    
    try:
        # Generate a random 5-character verification code
        characters = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
        verification_code = ''.join(random.choice(characters) for _ in range(5))
        
        # Format phone number to extract exactly 10 digits, removing all non-digit characters
        digits_only = ''.join(char for char in phone_number if char.isdigit())
        
        # Ensure we have exactly 10 digits
        if len(digits_only) < 10:
            return jsonify({'error': 'Phone number must contain at least 10 digits'}), 400
        
        # Take only the last 10 digits if there are more (handles country codes)
        formatted_phone = digits_only[-10:]
        
        # Create email gateway address - exactly 10 digits @ carrier domain
        sms_email = f"{formatted_phone}{carrier_domains[carrier_id]}"
        
        print(f"Sending SMS to: {formatted_phone} via {carrier_id} gateway ({sms_email})")
        
        # Create email content
        subject = "Verification Code"
        body = f"{verification_code}"
        
        # Create the email message
        #message = MIMEMultipart()
        message = EmailMessage()
        message['From'] = sender_email
        message['To'] = sms_email
        message['Subject'] = subject
        message.set_content(body)
        # Attach the body with the msg instance
        #message.attach(MIMEText(body, 'plain'))
        
        # Print debug info
        print(f"Sending verification code {verification_code} to {sms_email}")
        
        # Send the email via SMTP
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(sender_email, password)
            server.send_message(message)
            #server.sendmail(sender_email, sms_email, message.as_string())
            print(f"Verification code sent successfully to {sms_email}")
        
        # Store the verification details in the session or a temporary database
        verification_data = {
            'phone_number': formatted_phone,
            'carrier': carrier_id,
            'code': verification_code,
            'timestamp': time.time(),
            'verified': False,
            'email': normalized_email
        }
        
        # If you have a temporary verification collection, you could store it there
        # This could be useful for expiring codes after a certain time
        if 'verification_collection' in globals():
            # First remove any existing verification for this phone number
            verification_collection.delete_many({'phone_number': formatted_phone})
            # Then insert the new verification
            verification_collection.insert_one(verification_data)
            print(f"Stored verification data in database for {formatted_phone}")
        
        # Return success response with the verification code
        # In production, you might not return the code in the response
        return jsonify({
            'success': True,
            'message': 'Verification code sent successfully',
            'code': verification_code,  # Only for testing - would be removed in production
            'phone_formatted': formatted_phone,  # Return the formatted phone for confirmation
            'carrier': carrier_id,
            'email': normalized_email
        }), 200
        
    except Exception as e:
        print(f"Error sending verification code: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': f'Failed to send verification code: {str(e)}'}), 500

@app.route('/api/verify-phone', methods=['OPTIONS'])
def handle_verify_phone_options():
    return '', 200

@app.route('/api/verify-phone/confirm', methods=['POST'])
def confirm_phone():
    """API endpoint to confirm a phone verification code and associate the phone with a user"""
    data = request.json
    
    print(f"============= PHONE VERIFICATION CONFIRM =============")
    print(f"Received verification confirmation request: {json.dumps(data, indent=2)}")
    
    if not data or 'code' not in data or 'phoneNumber' not in data:
        return jsonify({'error': 'Verification code and phone number are required'}), 400
    
    entered_code = data['code'].upper()  # Convert to uppercase for case-insensitive comparison
    phone_number = data['phoneNumber']
    email = data.get('email', '')
    carrier = data.get('carrier', '')
    
    # Format phone number to extract exactly 10 digits
    formatted_phone = ''.join(char for char in phone_number if char.isdigit())[-10:]
    
    print(f"Confirming verification code '{entered_code}' for phone {formatted_phone}")
    print(f"Email from request: '{email}'")
    print(f"Carrier: {carrier}")
    
    try:
        # Verify the code
        expected_code = data.get('expectedCode', '')
        
        if not expected_code:
            return jsonify({'error': 'Verification failed - no expected code provided'}), 400
        
        if entered_code != expected_code:
            return jsonify({'error': 'Invalid verification code. Please try again.'}), 400
        
        # Code is valid - proceed with user lookup and update
        print(f"✅ Verification code is valid")
        
        # If we have an email, try to find the user first (most likely scenario for logged-in users)
        user_found = False
        user_id = None
        
        if email:
            # Normalize the email for consistency
            normalized_email = normalize_email(email)
            print(f"Looking for user with email: {normalized_email}")
            
            # Find the user by email
            user = users_collection.find_one({'email': normalized_email})
            if user:
                user_found = True
                user_id = user.get('_id')
                print(f"Found existing user with ID: {user_id}")
                
                # Update phone information
                update_result = users_collection.update_one(
                    {'_id': user_id},
                    {'$set': {
                        'phone_number': formatted_phone,
                        'phone_verified': True,
                        'phone_carrier': carrier,
                        'phone_verified_at': time.time()
                    }}
                )
                
                print(f"Update result: matched={update_result.matched_count}, modified={update_result.modified_count}")
                
                # Verify the update
                updated_user = users_collection.find_one({'_id': user_id})
                phone_updated = (
                    updated_user and 
                    updated_user.get('phone_number') == formatted_phone and
                    updated_user.get('phone_verified') == True
                )
                
                if phone_updated:
                    print(f"✅ Successfully updated phone information for existing user")
                    return jsonify({
                        'success': True,
                        'message': 'Phone number verified and linked to your account',
                        'phone_number': formatted_phone,
                        'phone_verified': True,
                        'phone_carrier': carrier,
                        'associated_with_email': True,
                        'email': normalized_email
                    }), 200
        
        # If no email provided or user not found with email, check for existing phone
        if not user_found:
            # Check if there's already a user with this phone number
            existing_with_phone = users_collection.find_one({'phone_number': formatted_phone})
            if existing_with_phone:
                user_found = True
                user_id = existing_with_phone.get('_id')
                print(f"Found user with this phone number: {formatted_phone}, ID: {user_id}")
                
                # Update the verification status
                update_result = users_collection.update_one(
                    {'_id': user_id},
                    {'$set': {
                        'phone_verified': True,
                        'phone_carrier': carrier,
                        'phone_verified_at': time.time()
                    }}
                )
                
                print(f"Update result: matched={update_result.matched_count}, modified={update_result.modified_count}")
                
                # If we have an email and the existing user doesn't, add it
                existing_email = existing_with_phone.get('email')
                if email and not existing_email:
                    normalized_email = normalize_email(email)
                    email_update = users_collection.update_one(
                        {'_id': user_id},
                        {'$set': {
                            'email': normalized_email,
                            'original_email': email
                        }}
                    )
                    print(f"Added email to existing phone record: {email_update.modified_count} modified")
                    existing_email = normalized_email
                
                return jsonify({
                    'success': True,
                    'message': 'Phone number verification updated successfully',
                    'phone_number': formatted_phone, 
                    'phone_verified': True,
                    'phone_carrier': carrier,
                    'associated_with_email': bool(existing_email),
                    'email': existing_email or ''
                }), 200
        
        # If we reach here, we need to create a new user or update an existing one
        # Let's check once more for blank email users that could be updated
        if not user_found:
            blank_email_user = users_collection.find_one({'email': ''})
            if blank_email_user:
                user_id = blank_email_user.get('_id')
                print(f"Found existing document with blank email, ID: {user_id}")
                
                # Update data
                update_data = {
                    'phone_number': formatted_phone,
                    'phone_verified': True,
                    'phone_carrier': carrier,
                    'phone_verified_at': time.time()
                }
                
                # Add email if provided
                if email:
                    normalized_email = normalize_email(email) 
                    update_data['email'] = normalized_email
                    update_data['original_email'] = email
                
                update_result = users_collection.update_one(
                    {'_id': user_id},
                    {'$set': update_data}
                )
                
                print(f"Update result: matched={update_result.matched_count}, modified={update_result.modified_count}")
                
                return jsonify({
                    'success': True,
                    'message': 'Phone number verified successfully',
                    'phone_number': formatted_phone,
                    'phone_verified': True, 
                    'phone_carrier': carrier,
                    'associated_with_email': bool(email),
                    'email': normalized_email if email else ''
                }), 200
            
            # Last resort: create a new user document
            print(f"No existing user found, creating new user with phone: {formatted_phone}")
            
            # Normalize email if provided
            normalized_email = normalize_email(email) if email else ''
            
            # Create new user document
            new_user = {
                'email': normalized_email,  # This will be blank if no email provided
                'original_email': email,
                'phone_number': formatted_phone,
                'phone_verified': True,
                'phone_carrier': carrier,
                'phone_verified_at': time.time(),
                'created_at': time.time(),
                'last_login': time.time()
            }
            
            insert_result = users_collection.insert_one(new_user)
            user_id = insert_result.inserted_id
            
            print(f"Created new user with ID: {user_id}")
            
            return jsonify({
                'success': True,
                'message': 'Phone number verified and ' + ('linked to your account' if email else 'new account created'),
                'phone_number': formatted_phone,
                'phone_verified': True,
                'phone_carrier': carrier,
                'associated_with_email': bool(email),
                'email': normalized_email or '',
                'new_account': True
            }), 200
            
    except Exception as e:
        print(f"Error in phone verification: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': f'Failed to complete phone verification: {str(e)}'}), 500

@app.route('/api/verify-phone/confirm', methods=['OPTIONS'])
def handle_verify_phone_confirm_options():
    return '', 200

@app.route('/api/users/profile', methods=['GET'])
def get_user_profile():
    """API endpoint to get a user's profile information including phone details"""
    email = request.args.get('email', '')
    phone_number = request.args.get('phone', '')
    
    print(f"Getting user profile - Email: '{email}', Phone: '{phone_number}'")
    
    # Special case for empty email string - empty email is valid for looking up users who
    # may have verified phone numbers without associating an email
    if email == '' and not phone_number:
        try:
            # Look for user with blank email
            print(f"Looking for user with blank email")
            user = users_collection.find_one({'email': ''})
            
            if user:
                # Convert MongoDB _id to string if it exists
                if '_id' in user:
                    user['_id'] = str(user['_id'])
                
                print(f"Found user with blank email: {json.dumps({k: str(v) if k == '_id' else v for k, v in user.items()}, default=str)}")
                
                # Include only the necessary fields for the frontend
                user_profile = {
                    'email': user.get('email', ''),
                    'phone_number': user.get('phone_number'),
                    'phone_verified': user.get('phone_verified', False),
                    'phone_carrier': user.get('phone_carrier'),
                    'phone_verified_at': user.get('phone_verified_at'),
                    'is_google_auth': user.get('is_google_auth', False),
                    'name': user.get('name'),
                    'profile_picture': user.get('profile_picture'),
                    'created_at': user.get('created_at')
                }
                
                return jsonify(user_profile), 200
            else:
                print(f"No user found with blank email")
                return jsonify({'error': 'User not found with blank email'}), 404
        except Exception as e:
            print(f"Error getting user profile with blank email: {str(e)}")
            import traceback
            traceback.print_exc()
            return jsonify({'error': f'An error occurred: {str(e)}'}), 500
    
    # Need at least one identifier - either email or phone
    if not email and not phone_number:
        return jsonify({'error': 'Email or phone number is required'}), 400
    
    try:
        # First, try to find by email if provided
        user = None
        if email:
            # Normalize the email before lookup
            normalized_email = normalize_email(email)
            print(f"Looking for user by email: '{normalized_email}'")
            user = users_collection.find_one({'email': normalized_email})
            
            # Try with blank email as fallback for users who verified phone without email
            if not user and email.strip() == '':
                print(f"Looking for user with blank email")
                user = users_collection.find_one({'email': ''})
        
        # If not found by email or email not provided, try phone
        if not user and phone_number:
            # Format phone number (extract digits only)
            formatted_phone = ''.join(char for char in phone_number if char.isdigit())
            if len(formatted_phone) >= 10:
                # Take last 10 digits
                formatted_phone = formatted_phone[-10:]
                print(f"Looking for user by phone number: {formatted_phone}")
                user = users_collection.find_one({'phone_number': formatted_phone})
        
        # Check if user was found by either method
        if not user:
            message = "User not found"
            if email and phone_number:
                message += f" with email '{email}' or phone '{phone_number}'"
            elif email:
                message += f" with email '{email}'"
            else:
                message += f" with phone '{phone_number}'"
            print(message)
            return jsonify({'error': message}), 404
        
        # User found - Convert MongoDB _id to string if it exists
        if '_id' in user:
            user['_id'] = str(user['_id'])
        
        print(f"Found user: {json.dumps({k: str(v) if k == '_id' else v for k, v in user.items()}, default=str)}")
        
        # Include only the necessary fields for the frontend
        user_profile = {
            'email': user.get('email'),
            'phone_number': user.get('phone_number'),
            'phone_verified': user.get('phone_verified', False),
            'phone_carrier': user.get('phone_carrier'),
            'phone_verified_at': user.get('phone_verified_at'),
            'is_google_auth': user.get('is_google_auth', False),
            'name': user.get('name'),
            'profile_picture': user.get('profile_picture'),
            'created_at': user.get('created_at')
        }
        
        return jsonify(user_profile), 200
        
    except Exception as e:
        print(f"Error getting user profile: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': f'An error occurred: {str(e)}'}), 500

@app.route('/api/users/profile', methods=['OPTIONS'])
def handle_user_profile_options():
    return '', 200

@app.route('/api/send-sms', methods=['OPTIONS'])
def handle_send_sms_options():
    return '', 200

@app.route('/api/send-sms', methods=['POST'])
def send_sms():
    """API endpoint to send an SMS notification using email-to-SMS gateway"""
    try:
        print("\n===== SEND SMS ENDPOINT CALLED =====")
        data = request.json
        print(f"Request data received: {data}")
        
        if not data:
            print("ERROR: Invalid request format - no data")
            return jsonify({'error': 'Invalid request format'}), 400
        
        # Get required fields
        phone_number = data.get('phone_number')
        carrier = data.get('carrier')
        message = data.get('message')
        email = data.get('email')  # Optional: if we want to lookup user by email
        
        print(f"Received parameters: phone={phone_number}, carrier={carrier}, message={message}, email={email}")
        
        # If email is provided, try to lookup user in MongoDB
        if email and not (phone_number and carrier):
            print(f"Email provided but missing phone details. Looking up user: {email}")
            user_data = users_collection.find_one({'email': email})
            
            if user_data and user_data.get('phone_verified') and user_data.get('phone_number') and user_data.get('phone_carrier'):
                phone_number = user_data.get('phone_number')
                carrier = user_data.get('phone_carrier')
                print(f"Retrieved verified phone from user document: {phone_number}, Carrier: {carrier}")
            else:
                print(f"ERROR: User does not have complete verified phone details: {user_data}")
                return jsonify({'error': 'User does not have a verified phone number'}), 400
        
        # Validate required fields
        if not phone_number:
            print("ERROR: Phone number is required")
            return jsonify({'error': 'Phone number is required'}), 400
        if not carrier:
            print("ERROR: Carrier is required")
            return jsonify({'error': 'Carrier is required'}), 400
        if not message:
            print("ERROR: Message is required")
            return jsonify({'error': 'Message is required'}), 400
        
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
        
        # Format phone number to extract exactly 10 digits, removing all non-digit characters
        digits_only = ''.join(char for char in phone_number if char.isdigit())
        
        # Ensure we have exactly 10 digits
        if len(digits_only) < 10:
            print(f"ERROR: Phone number must contain at least 10 digits: {phone_number}")
            return jsonify({'error': 'Phone number must contain at least 10 digits'}), 400
        
        # Take only the last 10 digits if there are more (handles country codes)
        formatted_phone = digits_only[-10:]
        print(f"Formatted phone number: {formatted_phone}")
        
        # Verify carrier is valid
        carrier_key = carrier.lower()
        if carrier_key not in carrier_domains:
            print(f"ERROR: Invalid carrier: {carrier}")
            return jsonify({'error': 'Invalid carrier selected'}), 400
        
        # Create email gateway address - exactly 10 digits @ carrier domain
        sms_email = f"{formatted_phone}{carrier_domains[carrier_key]}"
        print(f"Sending SMS to: {formatted_phone} via {carrier} gateway ({sms_email})")
        
        # Create email content
        subject = ""  # No subject for SMS
        body = message
        
        # Create the email message
        message_obj = EmailMessage()
        message_obj['From'] = sender_email
        message_obj['To'] = sms_email
        message_obj['Subject'] = subject
        
        # Attach the body with the msg instance
        message_obj.set_content(body)
        
        # Debug email credentials
        print(f"Using email credentials - From: {sender_email}, Password length: {len(password) if password else 0}")
        
        # Send the email via SMTP_SSL
        try:
            print(f"Connecting to SMTP server: smtp.gmail.com:465")
            with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
                print("SMTP_SSL connection established")
                print(f"Attempting login with email: {sender_email}")
                server.login(sender_email, password)
                print("SMTP login successful")
                
                print(f"Sending message to: {sms_email}")
                server.send_message(message_obj)
                #server.sendmail(sender_email, sms_email, message_obj.as_string())
                print("Message sent successfully")
        except Exception as smtp_error:
            print(f"SMTP ERROR: {str(smtp_error)}")
            raise smtp_error
        
        print(f"SMS sent successfully to {formatted_phone}")
        
        # Log the notification
        if 'Notifications' not in db.list_collection_names():
            db.create_collection('Notifications')
            
        notification_log = {
            'email': email,
            'phone_number': formatted_phone,
            'timestamp': time.time(),
            'notification_type': 'direct_sms',
            'message': body
        }
        db['Notifications'].insert_one(notification_log)
        print("Notification logged in database")
        
        print("===== SEND SMS ENDPOINT COMPLETED SUCCESSFULLY =====\n")
        return jsonify({'success': True, 'message': f'SMS sent to {formatted_phone}'}), 200
    
    except Exception as e:
        print(f"ERROR in send_sms: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': f'Failed to send SMS: {str(e)}'}), 500

if __name__ == "__main__":
    run()

