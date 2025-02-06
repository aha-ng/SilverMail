import os
import random
import string
import subprocess
import shutil
import mailbox
from datetime import datetime
from flask import Flask, render_template, session, redirect, url_for, jsonify, request

app = Flask(__name__)
app.secret_key = os.urandom(24)
app.config['PERMANENT_SESSION_LIFETIME'] = 3600  # 1 jam

# Konfigurasi
DOMAIN = "waifu.eula.my.id"
MAIL_DIR = "/var/mail/vhosts/waifu.eula.my.id"
POSTFIX_VIRTUAL_MAILBOX = "/etc/postfix/virtual_mailbox"
POSTFIX_VIRTUAL_ALIAS = "/etc/postfix/virtual_alias"

class EmailManager:
    def __init__(self):
        self.current_email = None
        self.mailbox_path = None

    def generate_username(self, length=12):
        chars = string.ascii_lowercase + string.digits
        return ''.join(random.choice(chars) for _ in range(length))

    def cleanup_previous_email(self):
        if self.current_email:
            try:
                # Hapus konfigurasi Postfix
                subprocess.run(f"sudo sed -i '/^{self.current_email}/d' {POSTFIX_VIRTUAL_MAILBOX}", 
                             shell=True, check=True)
                subprocess.run(f"sudo sed -i '/^{self.current_email}/d' {POSTFIX_VIRTUAL_ALIAS}", 
                             shell=True, check=True)
                
                # Update Postfix
                subprocess.run("sudo postmap " + POSTFIX_VIRTUAL_MAILBOX, shell=True, check=True)
                subprocess.run("sudo postmap " + POSTFIX_VIRTUAL_ALIAS, shell=True, check=True)
                subprocess.run("sudo systemctl reload postfix", shell=True, check=True)
                
            except subprocess.CalledProcessError as e:
                app.logger.error(f"Cleanup error: {str(e)}")

    def create_new_email(self):
        username = self.generate_username()
        new_email = f"{username}@{DOMAIN}"
        self.mailbox_path = f"{MAIL_DIR}/{username}"
        
        try:
            # Buat direktori email
            os.makedirs(f"{self.mailbox_path}/new", exist_ok=True)
            os.makedirs(f"{self.mailbox_path}/cur", exist_ok=True)
            subprocess.run(f"sudo chown -R vmail:vmail {self.mailbox_path}", 
                         shell=True, check=True)
            subprocess.run(f"sudo chmod -R 700 {self.mailbox_path}", 
                         shell=True, check=True)
            
            # Update konfigurasi Postfix
            with open(POSTFIX_VIRTUAL_MAILBOX, "a") as f:
                f.write(f"{new_email}    {DOMAIN}/{username}/\n")
            with open(POSTFIX_VIRTUAL_ALIAS, "a") as f:
                f.write(f"{new_email}    {username}\n")
            
            # Update Postfix
            subprocess.run(f"sudo postmap {POSTFIX_VIRTUAL_MAILBOX}", shell=True, check=True)
            subprocess.run(f"sudo postmap {POSTFIX_VIRTUAL_ALIAS}", shell=True, check=True)
            subprocess.run("sudo systemctl reload postfix", shell=True, check=True)
            
            return new_email
            
        except Exception as e:
            app.logger.error(f"Generation error: {str(e)}")
            raise

email_manager = EmailManager()

@app.route('/')
def index():
    return render_template('index.html', 
                         email=session.get('current_email'),
                         generated_time=session.get('generated_time'))

@app.route('/generate', methods=['POST'])
def generate_email():
    # Bersihkan email sebelumnya
    if 'current_email' in session:
        email_manager.current_email = session['current_email']
        email_manager.cleanup_previous_email()
    
    try:
        new_email = email_manager.create_new_email()
        session['current_email'] = new_email
        session['generated_time'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        session['email_counter'] = 0  # Reset counter
        return jsonify({"email": new_email})
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/emails')
def get_emails():
    if 'current_email' not in session:
        return jsonify([])
    
    try:
        username = session['current_email'].split('@')[0]
        mail_path = f"{MAIL_DIR}/{username}"
        
        mbox = mailbox.Maildir(mail_path, factory=lambda f: mailbox.MaildirMessage(f))
        emails = []
        counter = session.get('email_counter', 0)
        
        for key in mbox.keys()[counter:]:
            msg = mbox[key]
            body = extract_body(msg)  # Perubahan disini
            
            emails.append({
                'id': key,
                'from': msg['from'],
                'subject': msg['subject'] or "No Subject",
                'date': msg['date'],
                'body': body
            })
            counter += 1
        
        session['email_counter'] = counter
        return jsonify(emails)
    
    except Exception as e:
        app.logger.error(f"Mailbox error: {str(e)}")
        return jsonify([])

# Fungsi extract_body yang diperbaiki
def extract_body(msg):  # Tanpa parameter self
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == 'text/plain':
                body = part.get_payload(decode=True).decode(errors='replace')
                break
    else:
        body = msg.get_payload(decode=True).decode(errors='replace')
    return body

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=80, debug=True)