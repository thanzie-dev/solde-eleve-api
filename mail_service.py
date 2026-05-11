import os
import smtplib

from email.message import EmailMessage


def envoyer_mail(destinataire, copie, sujet, message):

    try:

        email_sender = os.getenv("MAIL_USERNAME")
        email_password = os.getenv("MAIL_PASSWORD")

        msg = EmailMessage()

        msg["Subject"] = sujet
        msg["From"] = email_sender
        msg["To"] = destinataire

        # =========================
        # GESTION CC
        # =========================
        liste_cc = []

        if copie:

            liste_cc = [
                x.strip()
                for x in copie.replace(";", ",").split(",")
                if x.strip() != ""
            ]

            msg["Cc"] = ", ".join(liste_cc)

        msg.set_content(message)

        # =========================
        # LISTE DESTINATAIRES
        # =========================
        tous_destinataires = [destinataire] + liste_cc

        # =========================
        # SMTP GMAIL
        # =========================
        with smtplib.SMTP("smtp.gmail.com", 587) as smtp:

            smtp.starttls()

            smtp.login(email_sender, email_password)

            smtp.send_message(
                msg,
                from_addr=email_sender,
                to_addrs=tous_destinataires
            )

        return True, "Mail envoyé"

    except Exception as e:

        print("❌ ERREUR SMTP :", e)

        return False, str(e)