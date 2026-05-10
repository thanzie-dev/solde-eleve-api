import os
import smtplib

from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart


def envoyer_mail(destinataire, copies, sujet, message):

    smtp_server = "smtp.gmail.com"
    smtp_port = 587

    username = os.getenv("MAIL_USERNAME")
    password = os.getenv("MAIL_PASSWORD")

    msg = MIMEMultipart()

    msg["From"] = username
    msg["To"] = destinataire
    msg["Subject"] = sujet

    if copies:
        msg["Cc"] = copies

    msg.attach(MIMEText(message, "plain", "utf-8"))

    tous_destinataires = [destinataire]

    if copies:
        tous_destinataires += copies.split(";")

    try:

        server = smtplib.SMTP(smtp_server, smtp_port)

        server.starttls()

        server.login(username, password)

        server.sendmail(
            username,
            tous_destinataires,
            msg.as_string()
        )

        server.quit()

        return True, "Mail envoyé"

    except Exception as e:
        print("❌ ERREUR SMTP :", e)
        return False, str(e)