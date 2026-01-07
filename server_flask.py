
# ===============================================================
# server_flask.py — Version PRO 4.1 (mise à jour avec FIP mensuel)
# ===============================================================

from flask import (
    Flask,
    jsonify,
    send_file,
    request,
    render_template_string,
    redirect,
    url_for,
    session
)

from functools import wraps
import os
import re
try:
    import pandas as pd
except ImportError:
    pd = None

import psycopg        # ✅ OBLIGATOIRE
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
#import import_excel_pg as import_excel


from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle,
    Paragraph, Image, Spacer
)
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm




# ===============================================================
# 🔹 Configuration générale
# ===============================================================

app = Flask(__name__)

# 🔐 Clé de session (Render-safe)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "BJ2KEL24")

ADMIN_PASSWORDS = [
    pwd.strip()
    for pwd in os.environ.get("ADMIN_PASSWORDS", "").split(",")
    if pwd.strip()
]
# mots de passe admin




# Mois officiels
MOIS_SCOLAIRE = [
    "Sept", "Oct", "Nov", "Dec", "Janv", "Fevr",
    "Mars", "Avr", "Mai", "Juin"
]

# Décorateur pour protéger les routes admin
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("admin_logged"):
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return decorated_function


# ===============================================================
# 🔹 Connexion base de données (SQLite / PostgreSQL auto)
# ===============================================================

DATABASE_URL = os.environ.get("DATABASE_URL")
def get_db_connection():
    if not DATABASE_URL:
        raise RuntimeError("❌ DATABASE_URL manquant")

    return psycopg.connect(
        DATABASE_URL,
        sslmode="require" if "render.com" in DATABASE_URL else "disable"
    )



# ===============================================================
# 🔵 1. Détermination FIP mensuel selon classe
# ===============================================================
def get_fip_par_classe(classe):
    if not classe:
        return 0

    # 🔹 Normalisation robuste (Excel sale, caractères invisibles)
    c = str(classe).upper()
    c = re.sub(r"[^A-Z0-9]", "", c)

    groupe_40 = ["1M", "2M", "3M", "1P", "2P", "3P", "4P", "5P", "6P"]
    groupe_45 = [
        "7EB", "8EB",
        "1HP", "1LIT", "1SC",
        "2HP", "2LIT", "2SC",
        "3HP", "3LIT", "3SC"
    ]
    groupe_55 = [
        "1CG", "1MG", "1TCC", "1EL", "1ELECTRO", "1CONST",
        "2CG", "2MG", "2TCC", "2EL",
        "3CG", "3MG", "3TCC", "3EL"
    ]
    groupe_80 = ["4CG", "4MG", "4TCC", "4EL", "4HP", "4SC", "4LIT"]

    if c in groupe_40:
        return 40
    elif c in groupe_45:
        return 45
    elif c in groupe_55:
        return 55
    elif c in groupe_80:
        return 80
    else:
        return 0


# ===============================================================
# 🔵 2. Normalisation des mois
# ===============================================================
def canonical_month(m_raw):
    if pd.isna(m_raw):
        return None

    s = str(m_raw).strip().lower()
    s = re.sub(r'^(ac|sld)[\.\-\s/]*', '', s)
    s = s.replace(".", "").replace(",", "").strip()

    mapping = {
        "sept": "Sept",
        "oct": "Oct",
        "nov": "Nov",
        "dec": "Dec",
        "janv": "Janv",
        "fev": "Fevr",
        "fév": "Fevr",
        "févr": "Fevr",
        "mars": "Mars",
        "avr": "Avr",
        "mai": "Mai",
        "juin": "Juin",
    }

    for k, v in mapping.items():
        if k in s:
            return v

    return None


# ===============================================================
# 🔵 3. Calcul FIP pour un élève
# ===============================================================
def calcul_fip_eleve(matricule: str, conn):

    # ==========================================================
    # 1️⃣ RÉCUPÉRATION DE L'ÉLÈVE
    # ==========================================================
    query_eleve = """
        SELECT *
        FROM eleves
        WHERE LOWER(matricule) = LOWER(%s)
    """

    eleve_df = pd.read_sql_query(query_eleve, conn, params=(matricule,))

    if eleve_df.empty:
        return None

    eleve = eleve_df.iloc[0].to_dict()

    matricule = eleve["matricule"]
    nom = eleve["nom"]
    sexe = eleve["sexe"]
    classe = eleve["classe"]
    section = eleve["section"]
    categorie = eleve["categorie"]
    telephone = eleve["telephone"]

    # ==========================================================
    # 2️⃣ CALCUL FIP ATTENDU
    # ==========================================================
    fip_mensuel = get_fip_par_classe(classe)
    total_attendu = fip_mensuel * len(MOIS_SCOLAIRE)

    # ==========================================================
    # 3️⃣ RÉCUPÉRATION DES PAIEMENTS
    # ==========================================================
    query_paiements = """
        SELECT p.mois, p.fip, p.numrecu
        FROM paiements p
        JOIN eleves e ON p.eleve_id = e.id
        WHERE LOWER(e.matricule) = LOWER(%s)
    """

    pay_df = pd.read_sql_query(query_paiements, conn, params=(matricule,))

    # ==========================================================
    # 4️⃣ AUCUN PAIEMENT
    # ==========================================================
    if pay_df.empty:
        return {
            "nom": nom,
            "matricule": matricule,
            "sexe": sexe,
            "classe": classe,
            "section": section,
            "categorie": categorie,
            "telephone": telephone,
            "fip_mensuel": fip_mensuel,
            "fip_total": 0.0,
            "total_attendu_fip": total_attendu,
            "solde_fip": total_attendu,
            "mois_payes": [],
            "mois_non_payes": MOIS_SCOLAIRE
        }

    # ==========================================================
    # 5️⃣ TRAITEMENT DES PAIEMENTS
    # ==========================================================
    pay_df = pay_df.drop_duplicates(subset=["numrecu"], keep="first")

    pay_df["mois_norm"] = pay_df["mois"].apply(canonical_month)
    pay_df["fip"] = pd.to_numeric(pay_df["fip"], errors="coerce").fillna(0)

    pay_df = pay_df[
        (pay_df["mois_norm"].notna()) &
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
        else:
            total_paye += montant
            if montant >= fip_mensuel:
                mois_payes.append(m)
            else:
                mois_payes.append(f"Ac.{m}")

    solde_fip = total_attendu - total_paye

    # ==========================================================
    # 6️⃣ RÉSULTAT FINAL
    # ==========================================================
    return {
        "nom": nom,
        "matricule": matricule,
        "sexe": sexe,
        "classe": classe,
        "section": section,
        "categorie": categorie,
        "telephone": telephone,
        "fip_mensuel": fip_mensuel,
        "fip_total": round(total_paye, 2),
        "total_attendu_fip": total_attendu,
        "solde_fip": round(solde_fip, 2),
        "mois_payes": mois_payes,
        "mois_non_payes": mois_non_payes
    }

# ===============================================================
# 🔵 3bis. Fonctions utilitaires pour FIP par section et par mois
# ===============================================================

def calcul_fip_cumul_section(section: str, mois: str = None):
    mois_cible = canonical_month(mois) if mois else None
    conn = get_db_connection()

    query = (
        """
        SELECT p.mois, SUM(p.fip) AS total_fip
        FROM paiements p
        JOIN eleves e ON p.eleve_id = e.id
        WHERE LOWER(e.section)=LOWER(%s)
        GROUP BY p.mois
        """
        if DATABASE_URL
        else
        """
        SELECT p.mois, SUM(p.fip) AS total_fip
        FROM paiements p
        JOIN eleves e ON p.eleve_id = e.id
        WHERE LOWER(e.section)=LOWER(?)
        GROUP BY p.mois
        """
    )

    df = pd.read_sql_query(query, conn, params=(section,))
    conn.close()

    df["mois_norm"] = df["mois"].apply(canonical_month)
    df = df[df["mois_norm"].notna()]

    if mois_cible:
        mois_index = MOIS_SCOLAIRE.index(mois_cible) + 1
        df = df[df["mois_norm"].apply(lambda m: MOIS_SCOLAIRE.index(m) < mois_index)]

    total_paye = df["total_fip"].sum()
    mois_cumul = df["mois_norm"].unique().tolist()

    return {
        "section": section,
        "mois_cumul": mois_cumul,
        "total_paye": round(float(total_paye), 2)
    }


def calcul_fip_total_par_mois(mois: str):
    mois_cible = canonical_month(mois)
    if not mois_cible:
        raise ValueError(f"Mois invalide : {mois}")

    conn = get_db_connection()

    query = """
        SELECT e.section, p.mois, p.fip
        FROM paiements p
        JOIN eleves e ON p.eleve_id = e.id
    """

    df = pd.read_sql_query(query, conn)
    conn.close()

    df["mois_norm"] = df["mois"].apply(canonical_month)
    df["fip"] = pd.to_numeric(df["fip"], errors="coerce").fillna(0)

    df = df[df["mois_norm"] == mois_cible]

    if df.empty:
        return {
            "mois": mois_cible,
            "total_general": 0.0,
            "details_sections": {}
        }

    group = df.groupby("section")["fip"].sum()

    total_general = group.sum()
    details_sections = {sec: round(float(val), 2) for sec, val in group.items()}

    return {
        "mois": mois_cible,
        "total_general": round(float(total_general), 2),
        "details_sections": details_sections
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


@app.route("/api/eleve/<matricule>")
def api_eleve(matricule):
    conn = None
    try:
        conn = get_db_connection()

        # 🔴 TEST DIRECT BASE (SANS calcul_fip_eleve)
        query = """
            SELECT
                matricule,
                nom,
                sexe,
                classe,
                section,
                categorie,
                telephone
            FROM eleves
            WHERE LOWER(matricule) = LOWER(%s)
        """

        df = pd.read_sql_query(query, conn, params=(matricule,))

        if df.empty:
            return jsonify({"error": "Élève introuvable"}), 404

        # 🔥 ON RENVOIE CE QUE LA BASE CONTIENT, BRUT
        return jsonify(df.iloc[0].to_dict()), 200

    except Exception as e:
        print("❌ ERREUR TEST BRUT :", e)
        return jsonify({"error": str(e)}), 500

    finally:
        if conn:
            conn.close()




@app.route("/api/mobile/eleve/<matricule>")
def api_mobile_eleve(matricule):
    conn = None
    try:
        conn = get_db_connection()
        data = calcul_fip_eleve(matricule, conn)

        if data is None:
            return jsonify({"error": f"Aucun élève trouvé pour {matricule}"}), 404

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
            "mois_non_payes": data["mois_non_payes"]
        }
        return jsonify(mobile_data)

    except Exception as e:
        return jsonify({"error": str(e)}), 500

    finally:
        if conn:
            conn.close()


@app.route("/api/dashboard")
def api_dashboard():
    conn = None
    try:
        conn = get_db_connection()

        nb_eleves = pd.read_sql_query(
            "SELECT COUNT(*) AS n FROM eleves;", conn
        )["n"][0]

        nb_paiements = pd.read_sql_query(
            "SELECT COUNT(*) AS n FROM paiements;", conn
        )["n"][0]

        total_fip = float(
            pd.read_sql_query(
                "SELECT SUM(fip) AS s FROM paiements;", conn
            )["s"][0] or 0.0
        )

        nb_classes = pd.read_sql_query(
            "SELECT COUNT(DISTINCT classe) AS n FROM eleves WHERE classe IS NOT NULL;",
            conn
        )["n"][0]

        return jsonify({
            "nb_eleves": int(nb_eleves),
            "nb_paiements": int(nb_paiements),
            "nb_classes": int(nb_classes),
            "total_fip_paye": round(total_fip, 2)
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500

    finally:
        if conn:
            conn.close()


# ===============================================================
# 🔵 18. PDF par Classe (étape 1)
# ===============================================================
PDF_CLASSE_HTML = """
<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<title>PDF par Classe</title>

<style>
body {
    font-family: "Bookman Old Style", serif;
    background: linear-gradient(to right, #e3f2fd, #ffffff);
    margin: 0;
    padding: 0;
}

.container {
    display: flex;
    justify-content: center;
    margin-top: 90px;
}

.card {
    background: #ffffff;
    width: 420px;
    padding: 30px 35px;
    border-radius: 16px;
    box-shadow: 0 10px 30px rgba(0,0,0,0.15);
    text-align: center;
}

.card h2 {
    margin: 0;
    margin-bottom: 12px;
    color: #0d47a1;
    font-size: 20px;
    letter-spacing: 1px;
}

.marquee {
    background: #e3f2fd;
    border-radius: 8px;
    padding: 8px;
    margin-bottom: 20px;
    overflow: hidden;
    white-space: nowrap;
}

.marquee span {
    display: inline-block;
    animation: defilement 14s linear infinite;
    color: #1565c0;
    font-size: 14px;
}

@keyframes defilement {
    0%   { transform: translateX(100%); }
    100% { transform: translateX(-100%); }
}

input[type=text] {
    width: 100%;
    padding: 12px;
    border-radius: 10px;
    border: 1px solid #bbb;
    margin-bottom: 20px;
    font-size: 15px;
}

.btn {
    display: block;
    width: 100%;
    padding: 13px;
    margin-bottom: 12px;
    border: none;
    border-radius: 10px;
    background: #1976d2;
    color: white;
    font-size: 15px;
    cursor: pointer;
}

.btn:hover {
    background: #0d47a1;
}

.btn-secondary {
    background: #2e7d32;
}

.btn-secondary:hover {
    background: #1b5e20;
}

.back {
    margin-top: 15px;
    display: inline-block;
    text-decoration: none;
    color: #444;
    font-size: 14px;
}
</style>
</head>

<body>

<div class="container">
    <div class="card">
        <h2>PDF PAR CLASSE</h2>

        <div class="marquee">
            <span>📄 Générez les rapports PDF par classe – Montants payés ou mois non payés</span>
        </div>

        <form method="GET" action="/admin/pdf_classe_choix">
            <input type="text" name="classe" placeholder="Exemple : 6P, 4CG, 2HP" required>

            <button class="btn" name="type" value="paye">
                📄 PDF – Montants payés
            </button>

            <button class="btn btn-secondary" name="type" value="non_paye">
                📄 PDF – Mois non payés
            </button>
        </form>

        <a href="/admin/dashboard" class="back">← Retour au menu</a>
    </div>
</div>

</body>
</html>
"""
@app.route("/admin/pdf_classe")
@login_required
def admin_pdf_classe():
    return render_template_string(PDF_CLASSE_HTML)


@app.route("/admin/pdf_classe_choix")
@login_required
def admin_pdf_classe_choix():
    classe = request.args.get("classe", "").strip()

    if not classe:
        return "Classe manquante", 400

    html = f"""
    <!DOCTYPE html>
    <html lang="fr">
    <head>
        <meta charset="UTF-8">
        <title>Choix PDF</title>

        <style>
            body {{
                font-family: "Bookman Old Style", serif;
                background: linear-gradient(to right, #f1f8ff, #ffffff);
                margin: 0;
                padding: 0;
            }}

            .container {{
                display: flex;
                justify-content: center;
                margin-top: 100px;
            }}

            .box {{
                background: white;
                width: 420px;
                padding: 30px;
                border-radius: 16px;
                box-shadow: 0 10px 25px rgba(0,0,0,0.15);
                text-align: center;
            }}

            h2 {{
                color: #0d47a1;
                margin-bottom: 20px;
            }}

            .btn {{
                display: block;
                margin: 15px 0;
                padding: 14px;
                background: #1976d2;
                color: white;
                text-decoration: none;
                border-radius: 10px;
                font-size: 16px;
            }}

            .btn:hover {{
                background: #0d47a1;
            }}

            .btn.impaye {{
                background: #c62828;
            }}

            .btn.impaye:hover {{
                background: #8e0000;
            }}

            .back {{
                margin-top: 20px;
                display: block;
                text-decoration: none;
                color: #555;
            }}
        </style>
    </head>

    <body>

        <div class="container">
            <div class="box">

                <h2>Classe {classe}</h2>

                <a class="btn" href="/api/rapport_classe/{classe}">
                    📊 PDF des montants payés
                </a>

                <a class="btn impaye" href="/api/rapport_classe/{classe}?type=impaye">
                    📆 PDF des mois non payés
                </a>

                <a href="/admin/pdf_classe" class="back">← Retour</a>

            </div>
        </div>

    </body>
    </html>
    """
    return html
    

@app.route("/api/classe/<classe>")
def api_classe(classe):
    conn = None
    try:
        conn = get_db_connection()

        query = (
            "SELECT * FROM eleves WHERE LOWER(classe)=LOWER(%s)"
            if DATABASE_URL
            else "SELECT * FROM eleves WHERE LOWER(classe)=LOWER(?)"
        )

        eleves_df = pd.read_sql_query(query, conn, params=(classe,))

        if eleves_df.empty:
            return jsonify({"error": f"Aucun élève trouvé pour la classe {classe}"}), 404

        result = [
            calcul_fip_eleve(row["matricule"], conn)
            for _, row in eleves_df.iterrows()
        ]

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

    finally:
        if conn:
            conn.close()



# ===============================================================
# 🔵 13. /api/fip_section/<section> — Cumul FIP par section
# ===============================================================
@app.route("/api/fip_section/<section>")
def api_fip_section(section):
    mois = request.args.get("mois", None)
    try:
        result = calcul_fip_cumul_section(section, mois)
        return jsonify(result)
    except Exception as e:
        # Utile pour PostgreSQL / Render (logs)
        print("❌ Erreur api_fip_section :", e)
        return jsonify({"error": str(e)}), 500


# ===============================================================
# 🔵 14. /api/fip_mois/<mois> — Total FIP par mois
# ===============================================================
@app.route("/api/fip_mois/<mois>")
def api_fip_mois(mois):
    try:
        result = calcul_fip_total_par_mois(mois)
        return jsonify(result)
    except Exception as e:
        # Log utile pour Render / PostgreSQL
        print("❌ Erreur api_fip_mois :", e)
        return jsonify({"error": str(e)}), 500


# ===============================================================
# 🔵 11 bis. Authentification ADMIN
# ===============================================================
LOGIN_FORM_HTML = """
<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<title>Connexion Administrative - CS THZ</title>

<style>

body {
    font-family: "Bookman Old Style", serif;
    background: linear-gradient(to right, #e3f2fd, #f9fbff);
    margin: 0;
    padding: 0;
}

/* 🔷 En-tête */
.header {
    display: flex;
    align-items: center;
    padding: 20px 30px;
}

.header img {
    height: 110px;
    margin-right: 15px;
}

.header p {
    font-size: 24px;
    color: #333;
    max-width: 650px;
}

/* 🔷 Conteneur principal */
.container {
    display: flex;
    justify-content: center;
    margin-top: 40px;
}

/* 🔷 Carte de connexion */
.login-card {
    background: white;
    width: 380px;
    padding: 30px 35px;
    border-radius: 16px;
    box-shadow: 0 12px 25px rgba(0,0,0,0.18);
    text-align: center;
}

/* 🔷 Titre */
.login-card h2 {
    border: 2px solid #1565c0;
    padding: 12px;
    border-radius: 12px;
    background: linear-gradient(to right, #1976d2, #42a5f5);
    color: white;
    margin-bottom: 25px;
    font-size: 18px;
    letter-spacing: 1px;
}

/* 🔷 Champs */
.login-card input[type="password"] {
    width: 90%;
    padding: 12px;
    font-size: 14px;
    border-radius: 8px;
    border: 1px solid #bbb;
    margin-bottom: 18px;
}

/* 🔷 Bouton */
.login-card button {
    width: 95%;
    padding: 12px;
    background: #1976d2;
    color: white;
    font-size: 15px;
    border: none;
    border-radius: 10px;
    cursor: pointer;
    transition: background 0.3s, transform 0.2s;
}

.login-card button:hover {
    background: #0d47a1;
    transform: scale(1.03);
}

/* 🔷 Message erreur */
.error {
    color: #c62828;
    font-size: 14px;
    margin-bottom: 10px;
}

@keyframes defilement-admin {
    0%   { transform: translateX(0); }
    100% { transform: translateX(-100%); }
}


/* 🔹 Bloc informatif sous le formulaire */
.info-login {
    width: 500px;
    margin: 15px auto 0 auto;
    background: #f5faff;
    border: 1px solid #bbdefb;
    border-radius: 10px;
    padding: 12px;
    font-size: 18px;
    color: #333;
    line-height: 1.6;
    text-align: center;
}


</style>

</head>

<body>

<!-- 🔷 ENTÊTE -->
<div class="header">
    <img src="{{ url_for('static', filename='images/logo_csnst.png') }}" alt="Logo CS THZ">
    <p>
       COMPLEXE SCOLAIRE NSANGA LE THANZIE.
    </p>
</div>

<!-- 🔷 FORMULAIRE -->

<div class="container">
      
         
    <div class="login-card">
    
     <!-- 🔔 TEXTE DÉFILANT ADMIN (AU-DESSUS DU FORMULAIRE) -->
                   <div style="
                      width:100%;
                      background:#e3f2fd;
                      border-top:2px solid #90caf9;
                      border-bottom:2px solid #90caf9;
                      padding:10px 0;
                      overflow:hidden;
                      white-space:nowrap;
                    ">
                       <div style="
                          display:inline-block;
                          padding-left:100%;
                          animation:defilement-admin 20s linear infinite;
                          font-size:18px;
                          font-weight:bold;
                          color:#0d47a1;
                       ">
                           🔐 L’administrateur système joue un rôle clé dans la sécurité,
                              la fiabilité des données et la bonne gouvernance du système scolaire.
                     </div>
                 </div>
    
    
      <h2>CONNEXION ADMINISTRATEUR</h2>

        {% if error %}
            <div class="error">{{ error }}</div>
        {% endif %}

        <form method="POST">
            <input type="password" name="password" placeholder="Mot de passe administrateur" required>
            <button type="submit">Se connecter</button>
        </form>
        
        <a href="/admin1/panel"
           style="
                 display:block;
                 margin-top:15px;
                 padding:12px;
                 background:#c62828;
                 color:white;
                 text-decoration:none;
                 border-radius:10px;
                 font-size:15px;
                 
          ">
          ← Retour au panel
        </a>

    </div>
</div>

<div class="container">
<div class="info-login">
    Accès réservé à l’administration du système de gestion des soldes élèves.
    Toute tentative d’accès non autorisée est strictement interdite.
</div>
</div>

</body>
</html>
"""


@app.route("/admin/login", methods=["GET","POST"])
def admin_login():
    error = None

    if request.method == "POST":
        pwd = request.form.get("password", "").strip()

        # 🔐 Vérification des deux mots de passe autorisés
        if pwd in ADMIN_PASSWORDS:
            session["admin_logged"] = True
            return redirect(url_for("admin_dashboard"))
        else:
            error = "Mot de passe incorrect."

    return render_template_string(LOGIN_FORM_HTML, error=error)


@app.route("/admin/logout")
@login_required
def admin_logout():
    session.pop("admin_logged", None)
    return redirect(url_for("admin1_panel"))


# ===============================================================
# 🔵 12. Interface et routes upload Excel
# ===============================================================

UPLOAD_FORM_HTML = """
<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <title>Importation du fichier mensuel</title>
    <style>
        body {
            font-family: "Bookman Old Style", serif;
            background: linear-gradient(to right, #f0f4ff, #e6ecff);
        }
        .box {
            width: 520px;
            margin: 80px auto;
            padding: 30px;
            background: #ffffff;
            border-radius: 12px;
            box-shadow: 0 0 15px rgba(0,0,0,0.15);
            text-align: center;
            border: 3px solid #2b4eff;
        }
        h2 {
            color: #2b4eff;
            margin-bottom: 25px;
        }
        input[type="file"] {
            margin: 20px 0;
        }
        button {
            padding: 12px 22px;
            font-size: 16px;
            background-color: #2b4eff;
            color: white;
            border: none;
            border-radius: 6px;
            cursor: pointer;
        }
        button:hover {
            background-color: #1f37b8;
        }
        .back-btn {
            display: inline-block;
            margin-top: 25px;
            text-decoration: none;
            color: #2b4eff;
            font-weight: bold;
        }
        .back-btn:hover {
            text-decoration: underline;
        }
    </style>
</head>
<body>

<div class="box">
    <h2>📥 Importation du fichier Excel mensuel</h2>

    <form method="POST" enctype="multipart/form-data">
        <input type="file" name="excel_file" accept=".xlsx" required><br>
        <button type="submit">Importer le fichier</button>
    </form>

    <a href="/admin/dashboard" class="back-btn">⬅ Retour au menu principal</a>
</div>

</body>
</html>
"""


@app.route("/admin/upload_excel", methods=["GET"])
@login_required
def admin_upload_form():
    return render_template_string(UPLOAD_FORM_HTML)

@app.route("/admin/upload_excel", methods=["POST"])
@login_required
def admin_upload_excel():
    if "excel_file" not in request.files:
        return jsonify({"error": "Aucun fichier reçu"}), 400

    f = request.files["excel_file"]
    if f.filename == "":
        return jsonify({"error": "Nom de fichier vide"}), 400

    # 📁 Dossier temporaire sûr (Render-compatible)
    os.makedirs("temp", exist_ok=True)
    excel_path = os.path.join("temp", "THZBD2526GA.xlsx")

    try:
        f.save(excel_path)

        # ⚠️ import_excel doit lire ce fichier
        stats = import_excel.run_import()

        return jsonify({
            "status": "ok",
            "message": "Importation réussie",
            "stats": stats
        })

    except Exception as e:
        # Log critique pour PostgreSQL / Render
        print("❌ Erreur import Excel :", e)
        return jsonify({"error": str(e)}), 500


# ===============================================================
# 🔵 15. Interface admin pour calcul FIP mensuel
# ===============================================================
FIP_FORM_HTML = """
<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<title>Calcul FIP Mensuel — CS THZ</title>

<style>
body {
    font-family: "Bookman Old Style", serif;
    background: linear-gradient(to right, #eef5ff, #ffffff);
    margin: 0;
    padding: 0;
}

/* 🔷 EN-TÊTE */
.header {
    display: flex;
    align-items: center;
    padding: 18px 40px;
}

.header img {
    height: 55px;
    margin-right: 15px;
}

.header h1 {
    font-size: 22px;
    color: #0d47a1;
    margin: 0;
}

/* 🔷 CONTENEUR */
.container {
    display: flex;
    justify-content: center;
    margin-top: 50px;
}

/* 🔷 CARTE */
.card {
    background: white;
    padding: 30px 40px;
    border-radius: 14px;
    width: 480px;
    box-shadow: 0 8px 22px rgba(0,0,0,0.15);
    text-align: center;
}

.card h2 {
    color: #0d47a1;
    margin-bottom: 12px;
}

/* 🔷 TEXTE DÉFILANT */
.marquee-box {
    overflow: hidden;
    background: #e3f2fd;
    border-radius: 8px;
    padding: 8px;
    margin-bottom: 22px;
    border: 1px solid #90caf9;
}

.marquee {
    display: inline-block;
    white-space: nowrap;
    animation: scroll-left 15s linear infinite;
    color: #1565c0;
    font-size: 14px;
}

@keyframes scroll-left {
    0% { transform: translateX(100%); }
    100% { transform: translateX(-100%); }
}

/* 🔷 FORMULAIRES */
form {
    margin-bottom: 25px;
}

input {
    padding: 8px;
    width: 85%;
    border-radius: 6px;
    border: 1px solid #90caf9;
    font-family: "Bookman Old Style", serif;
}

button {
    margin-top: 10px;
    padding: 10px;
    width: 90%;
    border: none;
    border-radius: 8px;
    font-size: 15px;
    background: #1976d2;
    color: white;
    cursor: pointer;
    transition: background 0.3s;
}

button:hover {
    background: #0d47a1;
}

/* 🔷 BOUTON RETOUR */
.back-btn {
    display: block;
    margin-top: 20px;
    padding: 10px;
    background: #2e7d32;
    color: white;
    border-radius: 8px;
    text-decoration: none;
    transition: background 0.3s;
}

.back-btn:hover {
    background: #1b5e20;
}
</style>
</head>

<body>

<!-- 🔷 EN-TÊTE -->
<div class="header">
    <img src="{{ url_for('static', filename='images/logo_csnst.png') }}">
    <h1>COMPLEXE SCOLAIRE THZ</h1>
</div>

<!-- 🔷 CONTENU -->
<div class="container">
    <div class="card">

        <h2>📅 CALCUL FIP MENSUEL</h2>

        <div class="marquee-box">
            <div class="marquee">
                Suivi financier intelligent — Transparence, rigueur et maîtrise des paiements scolaires
            </div>
        </div>

        <h3>1️⃣ Total payé par section</h3>
        <form method="GET" action="/admin/fip_section_result">
            <input type="text" name="section" placeholder="Ex : EB, HP, CG..." required><br>
            <input type="text" name="mois" placeholder="Mois (optionnel)"><br>
            <button type="submit">Calculer</button>
        </form>

        <h3>2️⃣ Total payé par mois (toutes sections)</h3>
        <form method="GET" action="/admin/fip_mois_result">
            <input type="text" name="mois" placeholder="Ex : Sept, Oct, Nov..." required><br>
            <button type="submit">Calculer</button>
        </form>

        <a href="/admin/dashboard" class="back-btn">← Retour Menu</a>

    </div>
</div>

</body>
</html>
"""

@app.route("/admin/fip", methods=["GET"])
@login_required
def admin_fip_form():
    return render_template_string(FIP_FORM_HTML)
 
 #==============================================
#        Route  FIP SECTION  RESULTAT
#=============================================

@app.route("/admin/fip_section_result", methods=["GET"])
@login_required
def admin_fip_section_result():
    section = request.args.get("section", "")
    mois = request.args.get("mois", None)

    if not section:
        return "Section manquante.", 400

    try:
        result = calcul_fip_cumul_section(section, mois)

        mois_html = ", ".join(result["mois_cumul"]) if result["mois_cumul"] else "Aucun"

        html = f"""
        <!DOCTYPE html>
        <html lang="fr">
        <head>
        <meta charset="UTF-8">
        <title>Résultat FIP Section</title>
        <!-- styles inchangés -->
        </head>
        <body>
        <div class="container">
            <div class="marquee">
                <marquee behavior="scroll" direction="left">
                    📈 Analyse financière par section — Une vision claire pour une gestion efficace
                </marquee>
            </div>

            <h2>📊 FIP – SECTION : {result['section']}</h2>

            <div class="info"><b>Mois cumulés :</b> {mois_html}</div>

            <div class="total">
                TOTAL PAYÉ : {result['total_paye']}
            </div>

            <a href="/admin/dashboard" class="btn">← Retour au Menu</a>
        </div>
        </body>
        </html>
        """
        return html

    except Exception as e:
        # Log utile pour PostgreSQL / Render
        print("❌ Erreur admin_fip_section_result :", e)
        return f"Erreur : {str(e)}", 500


 #==============================================
#        Route  FIP MOIS   RESULTAT
#============================================   

@app.route("/admin/fip_mois_result", methods=["GET"])
@login_required
def admin_fip_mois_result():
    mois = request.args.get("mois", "")
    if not mois:
        return "Mois manquant.", 400

    try:
        result = calcul_fip_total_par_mois(mois)

        rows_html = ""
        for section, montant in result["details_sections"].items():
            rows_html += f"""
            <tr>
                <td>{section}</td>
                <td>{montant}</td>
            </tr>
            """

        html = f"""
        <!DOCTYPE html>
        <html lang="fr">
        <head>
            <meta charset="UTF-8">
            <title>Calcul Mensuel FIP</title>

            <style>
                body {{
                    font-family: "Bookman Old Style", serif;
                    background: linear-gradient(to right, #e3f2fd, #ffffff);
                    margin: 0;
                    padding: 0;
                }}

                .container {{
                    width: 75%;
                    margin: 60px auto;
                    background: white;
                    border-radius: 14px;
                    box-shadow: 0 10px 30px rgba(0,0,0,0.15);
                    padding: 30px 40px;
                    text-align: center;
                }}

                .marquee {{
                    background: #0d47a1;
                    color: white;
                    padding: 10px;
                    border-radius: 8px;
                    margin-bottom: 25px;
                    font-size: 14px;
                    font-weight: bold;
                }}

                h2 {{
                    color: #0d47a1;
                    margin-bottom: 20px;
                    letter-spacing: 1px;
                }}

                table {{
                    width: 100%;
                    border-collapse: collapse;
                    margin-top: 20px;
                }}

                th, td {{
                    border: 1px solid #ccc;
                    padding: 10px;
                    text-align: center;
                }}

                th {{
                    background: #1976d2;
                    color: white;
                }}

                tr:nth-child(even) {{
                    background: #f5faff;
                }}

                .total {{
                    margin-top: 25px;
                    font-size: 18px;
                    font-weight: bold;
                    color: #1b5e20;
                }}

                .btn {{
                    display: inline-block;
                    margin-top: 30px;
                    padding: 12px 25px;
                    background: #0d47a1;
                    color: white;
                    text-decoration: none;
                    border-radius: 10px;
                    transition: background 0.3s;
                }}

                .btn:hover {{
                    background: #002171;
                }}
            </style>
        </head>

        <body>

            <div class="container">

                <div class="marquee">
                    <marquee behavior="scroll" direction="left">
                        📊 Suivi mensuel intelligent du FIP — Transparence • Rigueur • Gestion moderne
                    </marquee>
                </div>

                <h2>📅 TOTAL REÇU POUR LE MOIS DE : {result["mois"]}</h2>

                <table>
                    <tr>
                        <th>Section</th>
                        <th>Montant Total</th>
                    </tr>
                    {rows_html}
                </table>

                <div class="total">
                    💰 TOTAL GÉNÉRAL : {result["total_general"]}
                </div>

                <a href="/admin/dashboard" class="btn">← Retour au Menu Principal</a>

            </div>

        </body>
        </html>
        """

        return html

    except Exception as e:
        return f"Erreur : {str(e)}", 500



# ==================================================================================================
# 🔵 MENU PRINCIPAL ADMIN (TABLEAU DE BORD)  HTML + CSS (à intégrer dans ton ADMIN_DASHBOARD_HTML)
# ==================================================================================================

# ===============================================================
# 🔵 Interface Dashboard ADMIN (MENU)
# ===============================================================

DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<title>Admin Dashboard - CS THZ</title>

<style>
body {
    font-family: "Bookman Old Style", serif;
    background: linear-gradient(135deg, #e3f2fd, #ffffff);
    margin: 0;
    padding: 0;
}

/* ===== ENTÊTE ===== */
.header {
    display: flex;
    align-items: center;
    padding: 20px 40px;
}

.header img {
    height: 60px;
    margin-right: 20px;
}

.header h1 {
    font-size: 24px;
    color: #0d47a1;
    margin: 0;
    font-weight: bold;
}

/* ===== TEXTE DÉFILANT ===== */
.marquee-box {
    width: 100%;
    background: #0d47a1;
    color: white;
    padding: 10px 0;
    font-size: 14px;
    letter-spacing: 1px;
    overflow: hidden;
}

.marquee-box marquee {
    font-weight: bold;
}

/* ===== MENU ===== */
.menu-container {
    display: flex;
    justify-content: center;
    margin-top: 40px;
}

.menu {
    background: white;
    padding: 28px 40px;
    border-radius: 14px;
    box-shadow: 0 8px 20px rgba(0,0,0,0.15);
    text-align: center;
    width: 360px;
}

.menu h2 {
    margin-bottom: 18px;
    color: #0d47a1;
    font-size: 17px;
    letter-spacing: 1.5px;
    border-bottom: 2px solid #e3f2fd;
    padding-bottom: 10px;
}

.menu-btn {
    display: block;
    margin: 10px 0;
    padding: 12px;
    background: #1976d2;
    color: white;
    text-decoration: none;
    border-radius: 10px;
    font-size: 15px;
    transition: all 0.35s ease;
}

.menu-btn:nth-child(2):hover {
    background: linear-gradient(to right, #1e88e5, #42a5f5);
}

.menu-btn:nth-child(3):hover {
    background: linear-gradient(to right, #43a047, #66bb6a);
}

.menu-btn:nth-child(4):hover {
    background: linear-gradient(to right, #fb8c00, #ffb74d);
}

.menu-btn:nth-child(5):hover {
    background: linear-gradient(to right, #6a1b9a, #ab47bc);
}

.menu-btn:hover {
    transform: scale(1.03);
    background: linear-gradient(to right, #0d47a1, #08306b);
}

.menu-btn.logout {
    background: #c62828;
}

.menu-btn.logout:hover {
    background: linear-gradient(to right, #b71c1c, #e53935);
}

/* ===== FOOTER INFO ===== */
.footer-info {
    margin-top: 18px;
    font-size: 12px;
    color: #444;
    line-height: 1.6;
    border-top: 1px solid #e3f2fd;
    padding-top: 12px;
}
</style>
</head>

<body>

<!-- ENTÊTE -->
<div class="header">
    <img src="{{ url_for('static', filename='images/logo_csnst.png') }}">
    <h1>COMPLEXE SCOLAIRE NSANGA LE THANZIE</h1>
</div>

<!-- TEXTE DÉFILANT -->
<div class="marquee-box">
    <marquee direction="left">
        Plateforme numérique de gestion scolaire — Transparence • Rigueur • Excellence administrative
    </marquee>
</div>

<!-- MENU -->
<div class="menu-container">
    <div class="menu">
        <h2>MENU ADMINISTRATEUR</h2>

        <a href="/admin/fip_eleve" class="menu-btn">📊 Calcul FIP Élève</a>
        <a href="/admin/pdf_classe" class="menu-btn">📄 PDF par Classe</a>
        <a href="/admin/fip" class="menu-btn">📅 Calcul FIP Mensuel</a>
        <a href="/admin/confirm_import" class="menu-btn">📥 Import Excel</a>
        <a href="/admin/journal" class="menu-btn">📘 Journal des paiements</a>
        <a href="/admin/logout" class="menu-btn logout">🚪 Déconnexion</a>
        

        <!-- INFOS -->
        <div class="footer-info">
            Adresse : 165 Av Kasangulu, croisement des Églises,<br>
            Q/Gambela 2, C/Lubumbashi, Ville de Lubumbashi, RDC<br>
            Téléphone : <b>+243 974 773 760</b>
        </div>
    </div>
</div>

</body>
</html>
"""

@app.route("/admin/dashboard")
@login_required
def admin_dashboard():
    return render_template_string(DASHBOARD_HTML)




@app.route("/api/rapport_classe/<classe>")
@login_required
def rapport_pdf_classe(classe):

    type_pdf = request.args.get("type", "paye")
    conn = get_db_connection()

    # ===============================
    # 1️⃣ DONNÉES
    # ===============================
    query = """
        SELECT matricule, nom
        FROM eleves
        WHERE LOWER(classe) = LOWER(%s)
        ORDER BY nom
    """
    df = pd.read_sql_query(query, conn, params=(classe,))

    if df.empty:
        conn.close()
        return f"Aucun élève trouvé pour la classe {classe}", 404

    lignes = []
    for _, row in df.iterrows():
        data = calcul_fip_eleve(row["matricule"], conn)
        valeur = (
            ", ".join(data["mois_non_payes"])
            if type_pdf == "impaye"
            else str(data["fip_total"])
        )
        lignes.append([row["matricule"], row["nom"], valeur])

    conn.close()

    # ===============================
    # 2️⃣ PDF
    # ===============================
    os.makedirs("temp", exist_ok=True)
    path = os.path.join("temp", f"rapport_{classe}_{type_pdf}.pdf")

    doc = SimpleDocTemplate(
        path,
        pagesize=A4,
        rightMargin=2*cm,
        leftMargin=2*cm,
        topMargin=2*cm,
        bottomMargin=2*cm
    )

    elements = []

    # ===============================
    # 3️⃣ LOGO
    # ===============================
    logo_path = "static/images/logo_csnst.png"
    if os.path.exists(logo_path):
        logo = Image(logo_path, 2.5*cm, 2.5*cm)
        logo.hAlign = "LEFT"
        elements.append(logo)

    # ===============================
    # 4️⃣ TITRES
    # ===============================
    elements.append(Paragraph(
        "<b>COMPLEXE SCOLAIRE NSANGA LE THANZIE</b>",
        ParagraphStyle(
            "title",
            fontName="Times-Roman",
            fontSize=14,
            alignment=1
        )
    ))

    elements.append(Paragraph(
        "Adresse : 165 Av. Kasangulu, Q/Gambela 2, C/Lubumbashi – RDC",
        ParagraphStyle(
            "addr",
            fontName="Times-Roman",
            fontSize=10,
            alignment=1
        )
    ))

    elements.append(Spacer(1, 0.4*cm))

    titre = (
        "RAPPORT DES MONTANTS PAYÉS"
        if type_pdf == "paye"
        else "RAPPORT DES MOIS NON PAYÉS"
    )

    elements.append(Paragraph(
        f"{titre} – Classe : {classe}",
        ParagraphStyle(
            "subtitle",
            fontName="Times-Roman",
            fontSize=12,
            alignment=0
        )
    ))

    elements.append(Spacer(1, 1.5*cm))

    # ===============================
    # 5️⃣ TABLEAU
    # ===============================
    table_data = [["Matricule", "Nom de l'élève", "Valeur"]] + lignes

    table = Table(
        table_data,
        colWidths=[2.5*cm, 6*cm, 7.5*cm]
    )

    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 1, colors.black),
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("FONT", (0, 0), (-1, -1), "Times-Roman"),
        ("FONTSIZE", (0, 0), (-1, -1), 12),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))

    elements.append(table)

    # ===============================
    # 6️⃣ BAS DE PAGE
    # ===============================
    elements.append(Spacer(1, 1*cm))

    elements.append(Paragraph(
        "Document généré par le service de comptabilité du<br/>"
        "Complexe Scolaire Nsanga le Thanzie",
        ParagraphStyle(
            "footer",
            fontName="Times-Roman",
            fontSize=10,
            alignment=1
        )
    ))

    elements.append(Paragraph(
        f"Date : {datetime.now().strftime('%d/%m/%Y %H:%M')}",
        ParagraphStyle(
            "footer2",
            fontName="Times-Roman",
            fontSize=10,
            alignment=1
        )
    ))

    doc.build(elements)

    return send_file(path, as_attachment=True)


    
 #==========================================
 #  HTML de confirmation
 #==========================================

CONFIRM_IMPORT_HTML = """
<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<title>Confirmation Import Excel</title>
<style>
body{
    font-family:"Bookman Old Style", serif;
    background: linear-gradient(to right, #e3f2fd, #f8fbff);
}
.box{
    width:360px;
    margin:120px auto;
    background:white;
    padding:30px;
    border-radius:14px;
    box-shadow:0 8px 20px rgba(0,0,0,0.2);
    text-align:center;
}
h2{
    color:#0d47a1;
    margin-bottom:20px;
}
input{
    width:100%;
    padding:10px;
    margin-top:10px;
    border-radius:8px;
    border:1px solid #ccc;
}
button{
    margin-top:20px;
    padding:10px;
    width:100%;
    border:none;
    border-radius:8px;
    background:#1976d2;
    color:white;
    font-size:15px;
    cursor:pointer;
}
button:hover{
    background:#0d47a1;
}
.error{
    color:red;
    margin-top:15px;
}
a{
    display:block;
    margin-top:20px;
    color:#555;
    text-decoration:none;
}
</style>
</head>

<body>
<div class="box">
<h2>🔐 Confirmation Import Excel</h2>
<p>Veuillez saisir le mot de passe administrateur</p>

{% if error %}
<p class="error">{{ error }}</p>
{% endif %}

<form method="POST">
    <input type="password" name="password" placeholder="Mot de passe" required>
    <button type="submit">Valider</button>
</form>

<a href="/admin/dashboard">← Retour au menu</a>
</div>
</body>
</html>
"""

@app.route("/admin/confirm_import", methods=["GET", "POST"])
@login_required
def admin_confirm_import():
    error = None

    if request.method == "POST":
        pwd = request.form.get("password", "").strip()

        # 🔐 mêmes mots de passe que /admin/login
        if pwd in ADMIN_PASSWORDS:
            return redirect(url_for("admin_upload_form"))
        else:
            error = "❌ Mot de passe incorrect."

    return render_template_string(CONFIRM_IMPORT_HTML, error=error)


 # ===============================================================
# 🔵 17. Calcul FIP par Élève (recherche matricule)
# ===============================================================
# ===============================================================
# 🔵 Page CALCUL FIP ÉLÈVE (FORMULAIRE)
# ===============================================================
FIP_ELEVE_FORM_HTML = """
<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<title>Calcul FIP Élève</title>

<style>
body {
    font-family: "Bookman Old Style", serif;
    background: linear-gradient(to right, #e3f2fd, #f8fbff);
    margin: 0;
    padding: 0;
}

.container {
    display: flex;
    justify-content: center;
    margin-top: 100px;
}

.card {
    background: white;
    padding: 35px 45px;
    border-radius: 16px;
    width: 420px;
    box-shadow: 0 10px 25px rgba(0,0,0,0.15);
    text-align: center;
}

h2 {
    color: #0d47a1;
    margin-bottom: 25px;
}

input {
    width: 100%;
    padding: 12px;
    font-size: 15px;
    margin-bottom: 20px;
    border-radius: 8px;
    border: 1px solid #bbb;
}

button {
    width: 100%;
    padding: 12px;
    font-size: 16px;
    background: #1976d2;
    color: white;
    border: none;
    border-radius: 10px;
    cursor: pointer;
}

button:hover {
    background: #0d47a1;
}

a {
    display: block;
    margin-top: 20px;
    color: #1976d2;
    text-decoration: none;
}
</style>
</head>

<body>

<div class="container">
    <div class="card">
        <h2>📊 Calcul FIP Élève</h2>

        <form method="GET" action="/admin/fip_eleve_result">
            <input type="text" name="matricule" placeholder="Numéro matricule de l'élève" required>
            <button type="submit">Afficher le FIP</button>
        </form>

        <a href="/admin/dashboard">← Retour au menu</a>
    </div>
</div>

</body>
</html>
"""

@app.route("/admin/fip_eleve")
@login_required
def admin_fip_eleve():
    return render_template_string(FIP_ELEVE_FORM_HTML)


 
#==============================================
#RESULTAT ELEVE (Recherche par Numéro Matricule
#============================================== 

# ===============================================================
# 🔵 RÉSULTAT CALCUL FIP ÉLÈVE
# ===============================================================
@app.route("/admin/fip_eleve_result")
@login_required
def admin_fip_eleve_result():
    matricule = request.args.get("matricule", "").strip()
    if not matricule:
        return "Matricule manquant", 400

    conn = get_db_connection()
    data = calcul_fip_eleve(matricule, conn)
    conn.close()

    if not data:
        return "Élève introuvable", 404

    html = f"""
<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<title>Résultat FIP Élève</title>

<style>
body {{
    font-family: "Bookman Old Style", serif;
    background: linear-gradient(to right, #f1f8ff, #ffffff);
    margin: 0;
    padding: 0;
}}

.container {{
    display: flex;
    justify-content: center;
    margin-top: 60px;
}}

.card {{
    background: white;
    padding: 35px 45px;
    border-radius: 16px;
    width: 650px;
    box-shadow: 0 12px 30px rgba(0,0,0,0.15);
}}

h2 {{
    color: #0d47a1;
    text-align: center;
}}

.section {{
    margin-top: 20px;
}}

.section p {{
    margin: 6px 0;
}}

hr {{
    margin: 20px 0;
}}

.actions {{
    text-align: center;
}}

.actions a {{
    display: inline-block;
    margin: 10px;
    padding: 10px 18px;
    background: #1976d2;
    color: white;
    border-radius: 8px;
    text-decoration: none;
}}

.actions a:hover {{
    background: #0d47a1;
}}
</style>
</head>

<body>

<div class="container">
    <div class="card">

        <h2>📋 FICHE FIP ÉLÈVE</h2>

        <div class="section">
            <p><b>Matricule :</b> {data['matricule']}</p>
            <p><b>Nom & Postnom :</b> {data['nom']}</p>
            <p><b>Sexe :</b> {data.get('sexe','')}</p>
            <p><b>Classe :</b> {data['classe']}</p>
            <p><b>Section :</b> {data['section']}</p>
            <p><b>Catégorie :</b> {data['categorie']}</p>
            <p><b>Téléphone :</b> {data['telephone']}</p>
        </div>

        <hr>

        <div class="section">
            <p><b>FIP mensuel :</b> {data['fip_mensuel']}</p>
            <p><b>Total payé :</b> {data['fip_total']}</p>
            <p><b>Solde :</b> {data['solde_fip']}</p>
        </div>

        <hr>

        <div class="section">
            <p><b>✅ Mois payés :</b> {", ".join(data['mois_payes'])}</p>
            <p><b>❌ Mois non payés :</b> {", ".join(data['mois_non_payes'])}</p>
        </div>

        <div class="actions">
            <a href="/admin/fip_eleve">Nouvelle recherche</a>
            <a href="/admin1/panel">Menu principal</a>
        </div>

    </div>
</div>

</body>
</html>
"""
    return html


#=================================
#  ADMIN  PANEL 
#===============================
ADMIN1_PANEL_HTML = """
<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<title>Panel Administrateur</title>

<style>
body {
    margin: 0;
    font-family: "Bookman Old Style", serif;
    background: #f4f6fb;
}

.header {
    display: flex;
    justify-content: center;
    align-items: center;
    padding: 20px;
    position: relative;
}

.header h1 {
    font-size: 48px;
    color: #0d47a1;
    margin: 0;
}

.header img {
    position: absolute;
    right: 30px;
    height: 85px;
}

.band-blue { height: 20px; background: #0d47a1; }
.band-red  { height: 20px; background: #c62828; }

.marquee-box {
    background: white;
    padding: 12px;
}

marquee {
    font-size: 24px;
    color: #0d47a1;
    font-weight: bold;
}

.panel {
    width: 420px;
    margin: 40px auto;
    background: white;
    padding: 30px;
    border-radius: 14px;
    box-shadow: 0 10px 30px rgba(0,0,0,0.15);
    text-align: center;
}

.panel h2 {
    margin-bottom: 20px;
    color: #0d47a1;
}

.panel a {
    display: block;
    padding: 12px;
    margin: 8px 0;
    background: #1976d2;
    color: white;
    text-decoration: none;
    border-radius: 8px;
    transition: 0.3s;
}

.panel a:hover {
    background: #0d47a1;
}

.footer-info {
    margin: 40px auto;
    width: 80%;
    background: white;
    padding: 25px;
    border-radius: 14px;
    box-shadow: 0 6px 20px rgba(0,0,0,0.12);
    text-align: center;
    font-size: 16px;
}
</style>
</head>

<!-- ================= MODALE AIDE ================= -->
<div id="aideModal" style="
    display:none;
    position:fixed;
    inset:0;
    background:rgba(0,0,0,0.5);
    z-index:999;
">
    <div style="
        background:white;
        width:420px;
        margin:100px auto;
        padding:25px;
        border-radius:14px;
        box-shadow:0 10px 30px rgba(0,0,0,0.25);
        font-family:'Bookman Old Style', serif;
    ">
        <h3 style="color:#0d47a1;text-align:center;">
            ❓ Comment consulter les frais d’un élève
        </h3>

        <p style="font-size:14px;line-height:1.6;">
            Cette application permet de consulter les informations de paiement
            des frais scolaires d’un élève en suivant les étapes ci-dessous :
        </p>

        <div style="
            background:#e3f2fd;
            padding:12px;
            border-radius:10px;
            font-size:14px;
            line-height:1.8;
        ">
            <b>1.</b> Depuis le panel, cliquez sur <b>Gestion Élèves</b><br>
            <b>2.</b> Vous arrivez sur la page <b> GESTION DES ELEVE</b><br>
            <b>3.</b> Saisissez le <b>numéro de téléphone</b> parent ou de l’élève<br>
            <b>4.</b> Cliquez sur le bouton <b>FIP ÉLÈVE</b><br>
            <b>5.</b> Le système affiche le ou les <b>numéros matricules</b><br>
            <b>6.</b> Cliquez sur le <b>numéro matricule</b><br>
            <b>7.</b> Les <b>informations de paiement</b> s’affichent
        </div>

        <p style="font-size:13px;margin-top:12px;color:#444;">
            ℹ️ Ce processus est entièrement public et ne nécessite pas
            de connexion administrateur.
        </p>

        <button onclick="fermerAide()" style="
            margin-top:15px;
            width:100%;
            padding:10px;
            border:none;
            border-radius:10px;
            background:#1976d2;
            color:white;
            font-size:15px;
            cursor:pointer;
        ">
            Fermer
        </button>
    </div>
</div>
<!-- ================= MODALE AIDE FIN ================= -->

<!-- ================= JAVA SCRIPTS ================= -->
<script>
function ouvrirAide() {
    document.getElementById("aideModal").style.display = "block";
}

function fermerAide() {
    document.getElementById("aideModal").style.display = "none";
}
</script>

<!-- ================= JAVA SCRIPTS FIN================= -->


<body>

<div class="header">
    <h1>CS NSANGA LE THANZIE</h1>
    <img src="/static/images/logo_csnst.png">
</div>

<div class="band-blue"></div>

<div class="marquee-box">
    <marquee>
        Complexe Scolaire Nsanga le Thanzie : . Pour consulter les FIPs de vos élèves :Cliquez sur le bouton Gestion Élève. Saisissez votre numéro de téléphone. Validez votre saisie. Sélectionnez ensuite le PL ou le LT de l’élève concerné.Merci pour votre confiance.

    </marquee>
</div>

<div class="band-red"></div>

<div class="panel">
    <h2>PANNEAU ADMIN</h2>

    <a href="/admin/login">🔐 Connexion Administrateur</a>
    <a href="/admin1/gestion_eleve">📊 Gestion Élèves</a>
    <a href="#">📘 Journal Paiements</a>
    <a href="#">📄 Rapports</a>
    <a href="#">📅 Statistiques</a>
    <a href="#">🧾 Comptabilité</a>
    <a href="#">🖨️ Documents</a>
    <a href="#">⚙️ Paramètres</a>
    <a href="javascript:void(0)" onclick="ouvrirAide()">❓ Aide</a>

</div>

<div class="footer-info">
    <b>Complexe Scolaire Nsanga le Thanzie</b><br>
     165 Av : Kasangu croisement de l'Eglise–Q/Gambela2 - C/Lubumbashi - RDC <br>
            Tél : +24397 477 37 60 - 
       Email : serveurthanzie@gmail.com -
  Facebook : Nsanga Thanzie - Youtube: nsanga le thanzie ecole
           Site : csnsangalethanzie.org
</div>

</body>
</html>
"""

@app.route("/admin1/panel")
def admin1_panel():
    return render_template_string(ADMIN1_PANEL_HTML)
    
    
# ===============
# GESTION ELEVES
#================ 
GESTION_ELEVE_HTML = """
<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<title>Gestion des Élèves</title>

<style>
body {
    background: linear-gradient(135deg, #e3f2fd, #ffffff);
    font-family: "Bookman Old Style", serif;
}

.box {
    width: 480px;
    margin: 80px auto;
    background: white;
    padding: 35px;
    border-radius: 18px;
    box-shadow: 0 12px 35px rgba(0,0,0,0.18);
    text-align: center;
}

h2 { color: #0d47a1; }

input {
    width: 100%;
    padding: 14px;
    font-size: 15px;
    border-radius: 10px;
    border: 1px solid #ccc;
    margin-bottom: 25px;
}

.btn-row {
    display: flex;
    gap: 10px;
}

.btn-row button {
    flex: 1;
    padding: 12px;
    border: none;
    border-radius: 10px;
    font-size: 14px;
    cursor: pointer;
    background: #1976d2;
    color: white;
}

.btn-row button:hover {
    background: #0d47a1;
}

.back {
    margin-top: 18px;
    width: 100%;
    padding: 12px;
    border-radius: 10px;
    border: none;
    background: #c62828;
    color: white;
}

/* MODAL */
.modal {
    display: none;
    position: fixed;
    inset: 0;
    background: rgba(0,0,0,0.5);
}

.modal-content {
    background: white;
    width: 380px;
    margin: 120px auto;
    padding: 25px;
    border-radius: 14px;
    text-align: center;
}

.matricule {
    display: block;
    padding: 10px;
    margin: 8px 0;
    background: #e3f2fd;
    border-radius: 8px;
    cursor: pointer;
    font-weight: bold;
    text-decoration: none;
    color: #000;
}

.matricule:hover {
    background: #1976d2;
    color: white;
}
</style>
</head>

<body>

<div class="box">
    <h2>GESTION DES ÉLÈVES</h2>

    <input id="phoneInput" type="text" placeholder="Saisir numéro téléphone">

    <div class="btn-row">
        <button onclick="rechercherFipEleve()">FIP ÉLÈVE</button>
        <button>COMPT.</button>
        <button>ADM SYT</button>
    </div>

    <button class="back" onclick="location.href='/admin1/panel'">
        ← RETOUR AU PANEL
    </button>
</div>

<div class="modal" id="modal">
    <div class="modal-content">
        <h3>Choisir le matricule</h3>
        <div id="listeMatricules"></div>
        <br>
        <button onclick="fermerModal()">Fermer</button>
        
    </div>
</div>

<script>
function rechercherFipEleve() {
    const phone = document.getElementById("phoneInput").value.trim();
    if (!phone) {
        alert("Veuillez saisir un numéro de téléphone");
        return;
    }

    fetch("/admin1/find_matricules_by_phone?phone=" + encodeURIComponent(phone))
        .then(res => res.json())
        .then(data => {
            const liste = document.getElementById("listeMatricules");
            liste.innerHTML = "";

            if (data.length === 0) {
                liste.innerHTML = "<p style='color:red'>Aucun élève trouvé</p>";
            } else {
       data.forEach(m => {
           liste.innerHTML += `
               <a class="matricule"
                  href="/admin/fip_eleve_result?matricule=${m}">
                  ${m}
               </a>
         `;
     });

        }

            document.getElementById("modal").style.display = "block";
        })
        .catch(() => alert("Erreur serveur"));
}

function fermerModal() {
    document.getElementById("modal").style.display = "none";
}
</script>

</body>
</html>
"""

@app.route("/admin1/gestion_eleve")
def gestion_eleve():
   return render_template_string(GESTION_ELEVE_HTML)


@app.route("/admin1/find_matricules_by_phone")
def find_matricules_by_phone():
    phone = request.args.get("phone", "").strip()
    if not phone:
        return jsonify([])

    # 🔹 Normalisation côté utilisateur
    digits = "".join(c for c in phone if c.isdigit())
    last9 = digits[-9:]

    conn = get_db_connection()
    cur = conn.cursor(row_factory=psycopg.rows.dict_row)


    query = (
        """
        SELECT DISTINCT matricule
        FROM eleves
        WHERE
        REPLACE(
          REPLACE(
            REPLACE(
              REPLACE(
                REPLACE(telephone, '+', ''),
              ' ', ''),
            '-', ''),
          '/', ''),
        ';', '')
        LIKE %s
        """
        if DATABASE_URL
        else
        """
        SELECT DISTINCT matricule
        FROM eleves
        WHERE
        REPLACE(
          REPLACE(
            REPLACE(
              REPLACE(
                REPLACE(telephone, '+', ''),
              ' ', ''),
            '-', ''),
          '/', ''),
        ';', '')
        LIKE ?
        """
    )

    cur.execute(query, (f"%{last9}",))
    result = [r[0] for r in cur.fetchall()]
    conn.close()

    return jsonify(result)



#============================================================
#  JOURNAL 
#============================================================

JOURNAL_HTML = """
<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<title>Journal des Paiements</title>

<style>
body {
    font-family: "Bookman Old Style", serif;
    background: linear-gradient(135deg, #e3f2fd, #ffffff);
}

.container {
    width: 650px;
    margin: 60px auto;
    background: white;
    padding: 35px;
    border-radius: 16px;
    box-shadow: 0 8px 25px rgba(0,0,0,0.15);
    text-align: center;
}

h2 { color: #0d47a1; }

input[type=date] {
    padding: 12px;
    width: 70%;
    font-size: 16px;
    border-radius: 8px;
    border: 1px solid #ccc;
}

button {
    margin-top: 25px;
    padding: 12px 30px;
    font-size: 16px;
    border: none;
    border-radius: 10px;
    background: #1976d2;
    color: white;
    cursor: pointer;
}

button:hover { background: #0d47a1; }

a {
    display: block;
    margin-top: 20px;
    color: #0d47a1;
    text-decoration: none;
}
</style>
</head>

<body>
<div class="container">
    <h2>📘 JOURNAL DES PAIEMENTS</h2>

    <form method="GET" action="/admin/journal_result">
        <input type="date" name="date" required>
        <br>
        <button type="submit">Afficher le journal</button>
    </form>

    <a href="/admin/dashboard">← Retour au menu</a>
</div>
</body>
</html>
"""
@app.route("/admin/journal")
@login_required
def admin_journal():
    return render_template_string(JOURNAL_HTML)

@app.route("/admin/journal_result")
@login_required
def admin_journal_result():
    date_input = request.args.get("date")
    if not date_input:
        return "Date manquante", 400

    # date venant du formulaire (YYYY-MM-DD)
    date_cible = pd.to_datetime(date_input, errors="coerce").date()
    if pd.isna(date_cible):
        return "Date invalide", 400

    conn = get_db_connection()

    # ⚠️ COLONNE CORRECTE : datepaiement
    df = pd.read_sql_query("""
        SELECT
            e.matricule,
            e.nom,
            e.classe,
            e.section,
            p.mois,
            p.fip,
            p.numrecu,
            p.datepaiement
        FROM paiements p
        JOIN eleves e ON p.eleve_id = e.id
    """, conn)

    conn.close()

    # conversion robuste
    df["date_norm"] = pd.to_datetime(
        df["datepaiement"],
        errors="coerce"
    ).dt.date

    # filtrage
    df = df[df["date_norm"] == date_cible]

    if df.empty:
        return f"""
        <h3 style="text-align:center;color:#c62828;">
            Aucun paiement trouvé pour le {date_input}
        </h3>
        <div style="text-align:center;">
            <a href="/admin/journal">← Retour</a>
        </div>
        """

    total_jour = df["fip"].sum()

    rows = ""
    for _, r in df.iterrows():
        rows += f"""
        <tr>
            <td>{r['matricule']}</td>
            <td>{r['nom']}</td>
            <td>{r['classe']}</td>
            <td>{r['section']}</td>
            <td>{r['mois']}</td>
            <td>{r['fip']}</td>
            <td>{r['numrecu']}</td>
        </tr>
        """

    return f"""
    <!DOCTYPE html>
    <html lang="fr">
    <head>
        <meta charset="UTF-8">
        <title>Journal des paiements du {date_input}</title>
        <style>
            body {{ font-family:"Bookman Old Style"; background:#f4f8ff; }}
            table {{
                width:90%;
                margin:40px auto;
                border-collapse: collapse;
                background:white;
            }}
            th, td {{
                border:1px solid #ccc;
                padding:10px;
                text-align:center;
            }}
            th {{ background:#1976d2; color:white; }}
            tfoot td {{ font-weight:bold; background:#e3f2fd; }}
            h2 {{ text-align:center; color:#0d47a1; }}
        </style>
    </head>
    <body>

    <h2>📘 Journal des paiements du {date_input}</h2>

    <table>
        <thead>
            <tr>
                <th>Matricule</th>
                <th>Nom</th>
                <th>Classe</th>
                <th>Section</th>
                <th>Mois</th>
                <th>Montant</th>
                <th>Reçu</th>
            </tr>
        </thead>
        <tbody>{rows}</tbody>
        <tfoot>
            <tr>
                <td colspan="5">TOTAL JOURNÉE</td>
                <td colspan="2">{total_jour}</td>
            </tr>
        </tfoot>
    </table>

    <div style="text-align:center;">
        <a href="/admin/journal">← Retour</a>
    </div>

    </body>
    </html>
    """



@app.route("/api/journal_pdf/<date_iso>")
@login_required
def api_journal_pdf(date_iso):
    conn = get_db_connection()

    query = (
        """
        SELECT e.matricule, e.nom, e.classe, p.mois, p.fip
        FROM paiements p
        JOIN eleves e ON p.eleve_id = e.id
       
        WHERE p.datepaiement = %s


        """
        if DATABASE_URL
        else
        """
        SELECT e.matricule, e.nom, e.classe, p.mois, p.fip
        FROM paiements p
        JOIN eleves e ON p.eleve_id = e.id
        WHERE DATE(p.DatePaiement) = ?
        """
    )

    df = pd.read_sql_query(query, conn, params=(date_iso,))
    conn.close()

    if df.empty:
        return "Aucune donnée", 404

    total = df["fip"].sum()

    # 📁 Dossier temporaire Render-safe
    os.makedirs("temp", exist_ok=True)
    file_path = os.path.join("temp", f"journal_{date_iso}.pdf")

    c = canvas.Canvas(file_path, pagesize=A4)
    c.setFont("Helvetica", 9)

    y = 800
    c.drawString(50, y, f"JOURNAL DES PAIEMENTS - {date_iso}")
    y -= 25

    for _, r in df.iterrows():
        c.drawString(
            50, y,
            f"{r['matricule']} | {r['nom']} | {r['classe']} | {r['mois']} | {r['fip']}"
        )
        y -= 14
        if y < 60:
            c.showPage()
            c.setFont("Helvetica", 9)
            y = 800

    y -= 20
    c.setFont("Helvetica-Bold", 10)
    c.drawString(50, y, f"TOTAL JOURNALIER : {total}")

    c.save()
    return send_file(file_path, as_attachment=True)


# ===============================================================
# 🔵 11. Lancement local
# ===============================================================
if __name__ == "__main__":
    print("🚀 API en mode LOCAL : http://127.0.0.1:5000")
    debug = not DATABASE_URL
    app.run(host="0.0.0.0", port=5000, debug=debug)




