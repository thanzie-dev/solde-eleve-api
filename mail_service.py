import os
import smtplib

from email.message import EmailMessage


def envoyer_mail(destinataire,
                 copie,
                 sujet,
                 message,
                 fichier=None):

    try:

        email_sender = os.getenv("MAIL_USERNAME")
        email_password = os.getenv("MAIL_PASSWORD")

        # =====================================================
        # VALIDATION CONFIGURATION
        # =====================================================

        if not email_sender or not email_password:

            return False, "Configuration mail manquante"

        # =====================================================
        # CREATION MESSAGE
        # =====================================================

        msg = EmailMessage()

        msg["Subject"] = sujet
        msg["From"] = email_sender

        # =====================================================
        # DESTINATAIRES PRINCIPAUX (TO)
        # =====================================================

        liste_to = []

        if destinataire:

            liste_to = [
                x.strip()
                for x in destinataire.replace(";", ",").split(",")
                if x.strip() != ""
            ]

            msg["To"] = ", ".join(liste_to)

        # =====================================================
        # DESTINATAIRES COPIE (CC)
        # =====================================================

        liste_cc = []

        if copie:

            liste_cc = [
                x.strip()
                for x in copie.replace(";", ",").split(",")
                if x.strip() != ""
            ]

            msg["Cc"] = ", ".join(liste_cc)

        # =====================================================
        # VERIFICATION DESTINATAIRES
        # =====================================================

        tous_destinataires = liste_to + liste_cc

        if len(tous_destinataires) == 0:

            return False, "Aucun destinataire valide"

        # =====================================================
        # CONTENU MESSAGE
        # =====================================================

        msg.set_content(message)

        # =====================================================
        # AJOUT PDF SI FOURNI
        # =====================================================

        if fichier:

            fichier_data = fichier.read()

            msg.add_attachment(
                fichier_data,
                maintype="application",
                subtype="pdf",
                filename=fichier.filename
            )

            print("📎 PDF ajouté :", fichier.filename)

        else:

            print("⚠ Aucun PDF joint")

        # =====================================================
        # CONNEXION SMTP GMAIL
        # =====================================================

        with smtplib.SMTP(
                "smtp.gmail.com",
                587,
                timeout=30
        ) as smtp:

            # Initialisation SMTP
            smtp.ehlo()

            # Activation TLS
            smtp.starttls()

            # Réinitialisation EHLO après TLS
            smtp.ehlo()

            # Authentification Gmail
            smtp.login(
                email_sender,
                email_password
            )

            # =================================================
            # ENVOI EMAIL
            # =================================================

            smtp.send_message(
                msg,
                from_addr=email_sender,
                to_addrs=tous_destinataires
            )

        print("✅ MAIL ENVOYÉ :", tous_destinataires)

        return True, "Mail envoyé avec succès"

    except Exception as e:

        print("❌ ERREUR SMTP :", e)

        return False, str(e)