# ===============================================================
# server_flask.py — Version PRO 4.0
# Aligné avec la base PRO 7.0 (import_excel.py)
# ===============================================================

from flask import Flask, jsonify, send_file, request, render_template_string, redirect, url_for, session
import import_excel
import sqlite3
import pandas as pd
import re
import os
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

#la clé secrète + le mot de passe admin :
app = Flask(__name__)
app.secret_key = "BJ2KEL24"  # clé pour sécuriser la session (tu peux la changer)
DB_PATH = "thz.db"

ADMIN_PASSWORD = "1971celeste"  # Ton mot de passe admin


# Mois officiels
MOIS_SCOLAIRE = [
    "Sept", "Oct", "Nov", "Dec", "Janv", "Fevr",
    "Mars", "Avr", "Mai", "Juin"
]

#décorateur pour protéger les routes admin
from functools import wraps

def login_required(f):
    """Décorateur pour protéger les routes admin."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("admin_logged"):
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return decorated_function


# ===============================================================
# 🔵 1. Détermination FIP mensuel selon classe
# ===============================================================

def get_fip_par_classe(classe):
    if not classe:
        return 0

    c = str(classe).strip().replace("°", "").upper()

    groupe_40 = ["1M", "2M", "3M", "1P", "2P", "3P", "4P", "5P", "6P"]
    groupe_45 = ["7EB", "8EB", "1HP", "1LIT", "1SC",
                 "2HP", "2LIT", "2SC",
                 "3HP", "3LIT", "3SC"]
    groupe_55 = ["1CG", "1MG", "1TCC", "1EL", "1ELECTRO", "1CONST",
                 "2CG", "2MG", "2TCC", "2EL",
                 "3CG", "3MG", "3TCC", "3EL"]
    groupe_80 = ["4CG", "4MG", "4TCC", "4EL","4HP","4SC","4LIT"]

    if c in groupe_40:
        return 40
    elif c in groupe_45:
        return 45
    elif c in groupe_55:
        return 55
    elif c in groupe_80:
        return 80

    return 0


# ===============================================================
# 🔵 2. Normalisation des mois (Ac., Sld., etc.)
# ===============================================================

def canonical_month(m_raw):
    if pd.isna(m_raw):
        return None

    s = str(m_raw).strip().lower()

    # Retire Ac., Sld., Ac-, Ac/, etc.
    s = re.sub(r'^(ac|sld)[\.\-\s/]*', '', s)

    mapping = {
        "sept": "Sept", "oct": "Oct", "nov": "Nov", "dec": "Dec",
        "janv": "Janv", "jan": "Janv",
        "fev": "Fevr", "fév": "Fevr", "févr": "Fevr",
        "mars": "Mars", "avr": "Avr", "mai": "Mai",
        "juin": "Juin",
    }

    for k, v in mapping.items():
        if k in s:
            return v

    return None


# ===============================================================
# 🔵 3. Fonction utilitaire : calcul FIP pour un élève
# ===============================================================

def calcul_fip_eleve(matricule: str, conn: sqlite3.Connection):
    """
    Retourne un dict avec toutes les infos FIP d'un élève :
    - nom, classe, section, categorie, téléphone
    - fip_mensuel, fip_total, total_attendu_fip, solde_fip
    - mois_payes, mois_non_payes
    """
    eleve_df = pd.read_sql_query(
        "SELECT * FROM eleves WHERE LOWER(matricule)=LOWER(?)",
        conn, params=(matricule,)
    )

    if eleve_df.empty:
        return None  # élève introuvable

    eleve = eleve_df.iloc[0].to_dict()

    # On accepte "nom" ou "nom_postnom" selon la colonne que tu as
    nom = eleve.get("nom") or eleve.get("nom_postnom") or "Non renseigné"
    classe = eleve.get("classe", "")
    fip_mensuel = get_fip_par_classe(classe)
    total_attendu = fip_mensuel * len(MOIS_SCOLAIRE)

    # Paiements
    pay_df = pd.read_sql_query("""
        SELECT mois, fip, numrecu
        FROM paiements p
        JOIN eleves e ON p.eleve_id = e.id
        WHERE LOWER(e.matricule)=LOWER(?)
    """, conn, params=(matricule,))

    if pay_df.empty:
        return {
            "nom": nom,
            "matricule": matricule,
            "sexe": eleve.get("sexe", ""),
            "classe": classe,
            "section": eleve.get("section", ""),
            "categorie": eleve.get("categorie", ""),
            "telephone": eleve.get("telephone", ""),
            "fip_mensuel": fip_mensuel,
            "fip_total": 0.0,
            "total_attendu_fip": total_attendu,
            "solde_fip": total_attendu,
            "mois_payes": [],
            "mois_non_payes": MOIS_SCOLAIRE,
        }

    # Anti-doublon numrecu
    pay_df = pay_df.drop_duplicates(subset=["numrecu"], keep="first")

    pay_df["mois_norm"] = pay_df["mois"].apply(canonical_month)
    pay_df["fip"] = pd.to_numeric(pay_df["fip"], errors="coerce").fillna(0)

    pay_df = pay_df[
        pay_df["mois_norm"].notna() &
        (pay_df["fip"] > 0)
    ]

    pay_group = pay_df.groupby("mois_norm")["fip"].sum().to_dict()

    mois_payes = []
    mois_non_payes = []
    total_paye = 0.0

    for m in MOIS_SCOLAIRE:
        montant = float(pay_group.get(m, 0))

        if montant == 0:
            mois_non_payes.append(m)
            continue

        total_paye += montant

        if montant < fip_mensuel:
            mois_payes.append(f"Ac.{m}")
        else:
            mois_payes.append(m)

    solde_fip = total_attendu - total_paye

    return {
        "nom": nom,
        "matricule": matricule,
        "sexe": eleve.get("sexe", ""),
        "classe": classe,
        "section": eleve.get("section", ""),
        "categorie": eleve.get("categorie", ""),
        "telephone": eleve.get("telephone", ""),
        "fip_mensuel": fip_mensuel,
        "fip_total": round(total_paye, 2),
        "total_attendu_fip": total_attendu,
        "solde_fip": round(solde_fip, 2),
        "mois_payes": mois_payes,
        "mois_non_payes": mois_non_payes,
    }


# ===============================================================
# 🔵 4. ROUTES API DE BASE
# ===============================================================

@app.route("/")
def home():
    return jsonify({"status": "ok", "message": "API Solde Élève opérationnelle."})


@app.route("/api/ping")
def ping():
    return jsonify({"message": "API en ligne"})


# ===============================================================
# 🔵 5. /api/eleve/<matricule> — Version complète (WEB)
# ===============================================================

@app.route("/api/eleve/<matricule>")
def api_eleve(matricule):
    try:
        conn = sqlite3.connect(DB_PATH)
        data = calcul_fip_eleve(matricule, conn)
        conn.close()

        if data is None:
            return jsonify({"error": f"Aucun élève trouvé pour {matricule}"}), 404

        return jsonify(data)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ===============================================================
# 🔵 6. /api/mobile/eleve/<matricule> — Version allégée (Mobile)
# ===============================================================

@app.route("/api/mobile/eleve/<matricule>")
def api_mobile_eleve(matricule):
    try:
        conn = sqlite3.connect(DB_PATH)
        data = calcul_fip_eleve(matricule, conn)
        conn.close()

        if data is None:
            return jsonify({"error": f"Aucun élève trouvé pour {matricule}"}), 404

        # On renvoie seulement l'essentiel pour le mobile
        mobile_data = {
            "nom": data["nom"],
            "matricule": data["matricule"],
            "classe": data["classe"],
            "section": data["section"],
            "categorie": data["categorie"],
            "fip_mensuel": data["fip_mensuel"],
            "fip_total": data["fip_total"],
            "solde_fip": data["solde_fip"],
            "mois_payes": data["mois_payes"],
            "mois_non_payes": data["mois_non_payes"],
        }

        return jsonify(mobile_data)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ===============================================================
# 🔵 7. /api/dashboard — Statistiques globales
# ===============================================================

@app.route("/api/dashboard")
def api_dashboard():
    try:
        conn = sqlite3.connect(DB_PATH)

        nb_eleves = pd.read_sql_query("SELECT COUNT(*) AS n FROM eleves;", conn)["n"][0]
        nb_paiements = pd.read_sql_query("SELECT COUNT(*) AS n FROM paiements;", conn)["n"][0]

        # Total FIP payé
        total_fip = pd.read_sql_query("SELECT SUM(fip) AS s FROM paiements;", conn)["s"][0]
        total_fip = float(total_fip or 0.0)

        # Exemple : compter les classes distinctes
        nb_classes = pd.read_sql_query(
            "SELECT COUNT(DISTINCT classe) AS n FROM eleves WHERE classe IS NOT NULL;",
            conn
        )["n"][0]

        conn.close()

        return jsonify({
            "nb_eleves": int(nb_eleves),
            "nb_paiements": int(nb_paiements),
            "nb_classes": int(nb_classes),
            "total_fip_paye": round(total_fip, 2)
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ===============================================================
# 🔵 8. /api/classe/<classe> — Infos par classe
# ===============================================================

@app.route("/api/classe/<classe>")
def api_classe(classe):
    try:
        conn = sqlite3.connect(DB_PATH)

        # Liste des élèves de la classe
        eleves_df = pd.read_sql_query(
            "SELECT * FROM eleves WHERE LOWER(classe)=LOWER(?)",
            conn, params=(classe,)
        )

        if eleves_df.empty:
            conn.close()
            return jsonify({"error": f"Aucun élève trouvé pour la classe {classe}"}), 404

        result = []
        for _, row in eleves_df.iterrows():
            mat = row["matricule"]
            data = calcul_fip_eleve(mat, conn)
            result.append(data)

        conn.close()

        # Petites stats pour la classe
        total_attendu = sum(e["total_attendu_fip"] for e in result)
        total_paye = sum(e["fip_total"] for e in result)
        solde_total = sum(e["solde_fip"] for e in result)

        return jsonify({
            "classe": classe,
            "nb_eleves": len(result),
            "total_attendu_fip": round(total_attendu, 2),
            "total_paye_fip": round(total_paye, 2),
            "solde_total_fip": round(solde_total, 2),
            "eleves": result
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ===============================================================
# 🔵 9. /api/audit — Anomalies de base
# ===============================================================

@app.route("/api/audit")
def api_audit():
    """
    Audit simple :
    - NumRecu dupliqués dans paiements
    - Paiements avec fip <= 0
    - Elèves sans classe
    """
    try:
        conn = sqlite3.connect(DB_PATH)

        # 1) NumRecu dupliqués
        dups = pd.read_sql_query("""
            SELECT numrecu, COUNT(*) as cnt
            FROM paiements
            WHERE numrecu IS NOT NULL
            GROUP BY numrecu
            HAVING cnt > 1
        """, conn)

        # 2) FIP <= 0
        fip_zero = pd.read_sql_query("""
            SELECT *
            FROM paiements
            WHERE fip <= 0 OR fip IS NULL
        """, conn)

        # 3) Élèves sans classe
        eleves_sans_classe = pd.read_sql_query("""
            SELECT *
            FROM eleves
            WHERE classe IS NULL OR TRIM(classe)=''
        """, conn)

        conn.close()

        return jsonify({
            "numrecu_dupliques": dups.to_dict(orient="records"),
            "paiements_fip_anormaux": fip_zero.to_dict(orient="records"),
            "eleves_sans_classe": eleves_sans_classe.to_dict(orient="records")
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ===============================================================
# 🔵 🔟 /api/rapport_classe/<classe> — PDF par classe
# ===============================================================

@app.route("/api/rapport_classe/<classe>")
def api_rapport_classe(classe):
    """
    Génère un PDF de la classe avec :
    - liste des élèves
    - total FIP attendu / payé / solde
    Retourne le fichier PDF.
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        eleves_df = pd.read_sql_query(
            "SELECT * FROM eleves WHERE LOWER(classe)=LOWER(?)",
            conn, params=(classe,)
        )

        if eleves_df.empty:
            conn.close()
            return jsonify({"error": f"Aucun élève trouvé pour la classe {classe}"}), 404

        eleves_data = []
        for _, row in eleves_df.iterrows():
            mat = row["matricule"]
            data = calcul_fip_eleve(mat, conn)
            eleves_data.append(data)

        conn.close()

        # Génération du PDF
        pdf_name = f"rapport_classe_{classe}.pdf"
        c = canvas.Canvas(pdf_name, pagesize=A4)
        width, height = A4

        y = height - 50
        c.setFont("Helvetica-Bold", 16)
        c.drawString(50, y, f"Rapport FIP - Classe {classe}")
        y -= 30
        c.setFont("Helvetica", 10)
        c.drawString(50, y, f"Date : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        y -= 20

        # En-têtes de colonnes
        c.setFont("Helvetica-Bold", 9)
        c.drawString(50, y, "Matricule")
        c.drawString(130, y, "Nom")
        c.drawString(320, y, "FIP Payé")
        c.drawString(390, y, "Attendu")
        c.drawString(460, y, "Solde")
        y -= 15
        c.setFont("Helvetica", 8)

        total_attendu = 0.0
        total_paye = 0.0
        total_solde = 0.0

        for e in eleves_data:
            if y < 60:  # nouvelle page
                c.showPage()
                y = height - 50
                c.setFont("Helvetica-Bold", 16)
                c.drawString(50, y, f"Rapport FIP - Classe {classe} (suite)")
                y -= 30
                c.setFont("Helvetica-Bold", 9)
                c.drawString(50, y, "Matricule")
                c.drawString(130, y, "Nom")
                c.drawString(320, y, "FIP Payé")
                c.drawString(390, y, "Attendu")
                c.drawString(460, y, "Solde")
                y -= 15
                c.setFont("Helvetica", 8)

            c.drawString(50, y, str(e["matricule"]))
            c.drawString(130, y, str(e["nom"])[:28])
            c.drawRightString(360, y, f"{e['fip_total']:.2f}")
            c.drawRightString(430, y, f"{e['total_attendu_fip']:.2f}")
            c.drawRightString(500, y, f"{e['solde_fip']:.2f}")

            total_attendu += e["total_attendu_fip"]
            total_paye += e["fip_total"]
            total_solde += e["solde_fip"]

            y -= 12

        # Totaux
        y -= 10
        c.setFont("Helvetica-Bold", 10)
        c.drawString(50, y, "TOTAUX :")
        c.drawRightString(360, y, f"{total_paye:.2f}")
        c.drawRightString(430, y, f"{total_attendu:.2f}")
        c.drawRightString(500, y, f"{total_solde:.2f}")

        c.showPage()
        c.save()

        return send_file(pdf_name, as_attachment=True)

    except Exception as e:
        return jsonify({"error": str(e)}), 500
        
        
  # ===============================================================
# 🔵 11 bis. Authentification ADMIN
# ===============================================================

LOGIN_FORM_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Connexion Admin — Solde Élève</title>
</head>
<body style="font-family:Arial; margin:40px;">
    <h2>🔐 Connexion Administrateur</h2>

    {% if error %}
        <p style="color:red;">{{ error }}</p>
    {% endif %}

    <form method="POST">
        <p>Mot de passe :</p>
        <input type="password" name="password" required>
        <br><br>
        <button type="submit" style="padding:8px 16px;">Se connecter</button>
    </form>

    <p style="margin-top:20px;">
        <a href="/">Retour à l'API</a>
    </p>
</body>
</html>
"""

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    """Page de login admin."""
    error = None
    if request.method == "POST":
        pwd = request.form.get("password")
        if pwd == ADMIN_PASSWORD:
            session["admin_logged"] = True
            return redirect(url_for("admin_upload_form"))
        else:
            error = "Mot de passe incorrect."

    return render_template_string(LOGIN_FORM_HTML, error=error)


@app.route("/admin/logout")
def admin_logout():
    """Déconnexion de l'admin."""
    session.pop("admin_logged", None)
    return redirect(url_for("admin_login"))
      

# ===============================================================
# 🔵 12. Interface d'import Excel
# ===============================================================

UPLOAD_FORM_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Import Excel — Solde Élève</title>
</head>
<body style="font-family:Arial; margin:40px;">
    <h2>📊 Importation du fichier Excel</h2>

    <form action="/admin/upload_excel" method="POST" enctype="multipart/form-data">
        <p><b>Sélectionnez le fichier Excel :</b></p>
        <input type="file" name="excel_file" accept=".xlsx" required>
        <br><br>
        <button type="submit" style="padding:10px 20px;">Importer</button>
    </form>

    <p style="margin-top:30px;">
        <a href="/">Retour API</a>
    </p>
</body>
</html>
"""

@app.route("/admin/upload_excel", methods=["GET"])
@login_required
def admin_upload_form():
    """Affiche le formulaire HTML."""
    return render_template_string(UPLOAD_FORM_HTML)


@app.route("/admin/upload_excel", methods=["POST"])
@login_required
def admin_upload_excel():
    """Reçoit un fichier Excel, le sauvegarde et relance l'import."""
    if "excel_file" not in request.files:
        return jsonify({"error": "Aucun fichier reçu"}), 400
    
    f = request.files["excel_file"]

    if f.filename == "":
        return jsonify({"error": "Nom de fichier vide"}), 400

    # On remplace l'ancien Excel par le nouveau
    excel_path = "THZBD2526GA.xlsx"
    f.save(excel_path)

    try:
        # Exécution PRO : reconstruit thz.db
        stats = import_excel.run_import()

        return jsonify({
            "status": "ok",
            "message": "Importation réussie",
            "stats": stats
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ===============================================================
# 🔵 11. Lancement local
# ===============================================================
if __name__ == "__main__":
    print("🚀 API en mode LOCAL : http://127.0.0.1:5000")
    app.run(host="0.0.0.0", port=5000, debug=True)
