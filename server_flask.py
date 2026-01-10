# ===============================================================
# server_flask.py — VERSION STABLE SANS PANDAS (LOCAL + RENDER)
# ===============================================================

from flask import (
    Flask, jsonify, request,
    render_template_string, redirect,
    url_for, session, send_file
)

from functools import wraps
import os
import re
from datetime import datetime

import psycopg
from psycopg.rows import dict_row

from reportlab.lib.pagesizes import A4
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle,
    Paragraph, Image, Spacer
)
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas
import import_excel_pg as import_excel






# ===============================================================
# 🔹 CONFIGURATION GLOBALE (OBLIGATOIRE ICI)
# ===============================================================

DATABASE_URL = os.environ.get("DATABASE_URL")


def canonical_classe(raw):
    """
    Normalise toutes les classes Excel / utilisateur vers
    les classes officielles du Complexe Scolaire THZ.

    Exemples :
    1°P, 1░P, 1 P  -> 1P
    3°Sc, 3░SC    -> 3SC
    1°Elctro      -> 1ELCTRO
    7°EB          -> 7EB
    """
    if not raw:
        return None

    s = str(raw).upper().strip()

    # Supprime symboles parasites : ° ░ espace / -
    s = re.sub(r"[^A-Z0-9]", "", s)

    # Corrections orthographiques connues
    corrections = {
        "ELCTRO": "ELCTRO",
        "ELECTRO": "ELCTRO",
        "SC": "SC",
        "SCIENCE": "SC",
        "LITTERATURE": "LIT",
        "LITT": "LIT",
        "CONS": "CONS",
        "CONSTRUCTION": "CONS",
    }

    # Sépare numéro / section
    match = re.match(r"^([0-9]+)([A-Z]+)$", s)
    if not match:
        return None

    niveau, section = match.groups()

    section = corrections.get(section, section)

    classe_norm = f"{niveau}{section}"

    # 🔒 LISTE BLANCHE (sécurité)
    CLASSES_VALIDES = {
        # Maternelle
        "1M","2M","3M",

        # Primaire
        "1P","2P","3P","4P","5P","6P",

        # Secondaire EB
        "7EB","8EB",

        # Secondaire Humanités
        "1HP","1SC","1LIT","1EL","1TCC","1CG","1MG","1ELCTRO","1CONS",
        "2HP","2SC","2LIT","2EL","2TCC","2CG","2MG",
        "3HP","3SC","3LIT","3EL","3TCC","3CG","3MG",
        "4HP","4SC","4LIT","4EL","4TCC","4CG","4MG",
    }

    return classe_norm if classe_norm in CLASSES_VALIDES else None


#==================
# PSYCOPG
#==================

def fetch_all(query, params=None):
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(query, params or ())
            return cur.fetchall()

def fetch_one(query, params=None):
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(query, params or ())
            return cur.fetchone()



# ===============================================================
# 🔹 Configuration générale
# ===============================================================

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "BJ2KEL24")


ADMIN_PASSWORDS = [
    p.strip()
    for p in os.environ.get("ADMIN_PASSWORDS", "").split(",")
    if p.strip()
]

# mots de passe admin


# Mois officiels
MOIS_SCOLAIRE = [
    "Sept", "Oct", "Nov", "Dec", "Janv", "Fevr",
    "Mars", "Avr", "Mai", "Juin"
]

# Décorateur pour protéger les routes admin
def login_required(f):
    """
    Protège les routes administrateur.
    Redirige vers /admin/login si non connecté.
    """
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("admin_logged"):
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return wrapper



# ===============================================================
# 🔹 Connexion base de données (SQLite / PostgreSQL auto)
# ===============================================================

def get_db_connection():
    """
    Ouvre une connexion PostgreSQL sécurisée.
    Compatible Render (SSL) et local.
    """
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL manquant")

    return psycopg.connect(
        DATABASE_URL,
        sslmode="require" if "render.com" in DATABASE_URL else "disable"
    )


# ===============================================================
# 🔵 1. Détermination FIP mensuel selon classe
# ===============================================================
def get_fip_par_classe(classe):
    classe = canonical_classe(classe)
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
        "1CG", "1MG", "1TCC", "1EL", "1ELCTRO","1CONS",
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
    """
    Nettoie et normalise les mois venant d'Excel ou DB.
    Retourne un mois officiel ou None.
    """
    if not m_raw:
        return None

    s = str(m_raw).lower().strip()
    s = re.sub(r'^(ac|sld)[\.\-\s/]*', '', s)
    s = s.replace(".", "").replace(",", "")

    mapping = {
        "sept": "Sept", "oct": "Oct", "nov": "Nov",
        "dec": "Dec", "janv": "Janv",
        "fev": "Fevr", "févr": "Fevr",
        "mars": "Mars", "avr": "Avr",
        "mai": "Mai", "juin": "Juin",
    }

    for k, v in mapping.items():
        if k in s:
            return v

    return None
    

# ===============================================================
# 🔵 3. Calcul FIP pour un élève
# ===============================================================
def calcul_fip_eleve(matricule):
    """
    Calcule le FIP d'un élève.
    Fonction MÉTIER pure (aucun HTML).
    """
    conn = get_db_connection()
    cur = conn.cursor(row_factory=dict_row)

    # Élève
    cur.execute("""
        SELECT id, matricule, nom, sexe, classe,
               section, categorie, telephone
        FROM eleves
        WHERE LOWER(matricule)=LOWER(%s)
        LIMIT 1
    """, (matricule,))
    eleve = cur.fetchone()

    if not eleve:
        conn.close()
        return None

    fip_mensuel = get_fip_par_classe(eleve["classe"])
    total_attendu = fip_mensuel * len(MOIS_SCOLAIRE)

    # Paiements
    cur.execute("""
        SELECT mois, COALESCE(fip,0) AS fip
        FROM paiements
        WHERE eleve_id=%s
    """, (eleve["id"],))
    rows = cur.fetchall()
    conn.close()

    pay_by_month = {}

    for r in rows:
        mois = canonical_month(r["mois"])
        if mois:
            pay_by_month[mois] = pay_by_month.get(mois, 0) + float(r["fip"])

    total_paye = 0
    mois_payes, mois_non_payes = [], []

    for m in MOIS_SCOLAIRE:
        montant = pay_by_month.get(m, 0)
        if montant == 0:
            mois_non_payes.append(m)
        else:
            total_paye += montant
            mois_payes.append(m if montant >= fip_mensuel else f"Ac.{m}")

    return {
       **eleve,
       "fip_mensuel": fip_mensuel,
       "total_attendu": total_attendu,
       "fip_total": round(total_paye, 2),
       "solde_fip": round(total_attendu - total_paye, 2),
       "mois_payes": mois_payes,
       "mois_non_payes": mois_non_payes
    }


# ===============================================================
# 🔵 3bis. Fonctions utilitaires pour FIP par section et par mois
# ===============================================================

def calcul_fip_section(section, mois=None):
    """
    Calcule le total FIP payé pour une section.
    Si mois est fourni, cumule jusqu'à ce mois inclus.
    """
    mois_cible = canonical_month(mois) if mois else None

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT p.mois, COALESCE(p.fip,0)
        FROM paiements p
        JOIN eleves e ON p.eleve_id = e.id
        WHERE LOWER(e.section) = LOWER(%s)
    """, (section,))

    rows = cur.fetchall()
    conn.close()

    total = 0.0
    mois_payes = set()

    for mois_db, fip in rows:
        mois_norm = canonical_month(mois_db)
        if not mois_norm:
            continue

        if mois_cible:
            if MOIS_SCOLAIRE.index(mois_norm) > MOIS_SCOLAIRE.index(mois_cible):
                continue

        if fip > 0:
            total += float(fip)
            mois_payes.add(mois_norm)

    return {
        "section": section.upper(),
        "mois_cumul": sorted(
            mois_payes,
            key=lambda m: MOIS_SCOLAIRE.index(m)
        ),
        "total_paye": round(total, 2)
    }



def calcul_fip_par_mois(mois):
    """
    Calcule le total FIP payé pour un mois donné,
    avec détail par section.
    """
    mois_cible = canonical_month(mois)
    if not mois_cible:
        raise ValueError("Mois invalide")

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            e.section,
            p.mois,
            COALESCE(p.fip, 0)
        FROM paiements p
        JOIN eleves e ON p.eleve_id = e.id
    """)

    rows = cur.fetchall()
    conn.close()

    total_general = 0.0
    details_sections = {}

    for section, mois_db, fip in rows:
        mois_norm = canonical_month(mois_db)
        if mois_norm != mois_cible:
            continue

        montant = float(fip)
        total_general += montant

        section = section or "Non définie"
        details_sections[section] = (
            details_sections.get(section, 0.0) + montant
        )

    return {
        "mois": mois_cible,
        "total_general": round(total_general, 2),
        "details_sections": {
            sec: round(val, 2)
            for sec, val in details_sections.items()
        }
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
    try:
        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor(row_factory=dict_row) as cur:

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

                cur.execute(query, (matricule,))
                eleve = cur.fetchone()

                if not eleve:
                    return jsonify({"error": "Élève introuvable"}), 404

        # 🔥 ON RENVOIE CE QUE LA BASE CONTIENT, BRUT
        return jsonify(eleve), 200

    except Exception as e:
        print("❌ ERREUR API ELEVE :", e)
        return jsonify({"error": str(e)}), 500

#==========================
#    API MOBILE ELEVE
#==========================

@app.route("/api/mobile/eleve/<matricule>")
def api_mobile_eleve(matricule):
    try:
        data = calcul_fip_eleve(matricule)

        if data is None:
            return jsonify({"error": f"Aucun élève trouvé pour {matricule}"}), 404

        return jsonify({
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
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500




@app.route("/api/dashboard")
def api_dashboard():
    try:
        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor(row_factory=dict_row) as cur:

                cur.execute("SELECT COUNT(*) FROM eleves;")
                nb_eleves = cur.fetchone()["count"]

                cur.execute("SELECT COUNT(*) FROM paiements;")
                nb_paiements = cur.fetchone()["count"]

                cur.execute("SELECT COALESCE(SUM(fip), 0) FROM paiements;")
                total_fip = cur.fetchone()["coalesce"]

                cur.execute(
                    "SELECT COUNT(DISTINCT classe) FROM eleves WHERE classe IS NOT NULL;"
                )
                nb_classes = cur.fetchone()["count"]

        return jsonify({
            "nb_eleves": int(nb_eleves),
            "nb_paiements": int(nb_paiements),
            "nb_classes": int(nb_classes),
            "total_fip_paye": round(float(total_fip), 2)
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500



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
    
#==================================
#   ROUTE /api/classe/<classe>
#==================================

@app.route("/api/classe/<classe>")
def api_classe(classe):
    """
    Retourne les informations FIP de tous les élèves d'une classe
    Classe acceptée sous toutes formes : 1°P, 1░P, 1P, etc.
    """

    # 🔹 Normalisation classe utilisateur
    classe_norm = canonical_classe(classe)
    if not classe_norm:
        return jsonify({"error": "Classe invalide"}), 400

    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(row_factory=psycopg.rows.dict_row)

        # 🔹 Requête robuste (ignore ° ░ espaces etc.)
        cur.execute("""
            SELECT *
            FROM eleves
            WHERE regexp_replace(UPPER(classe), '[^A-Z0-9]', '', 'g') = %s
        """, (classe_norm,))

        eleves = cur.fetchall()

        if not eleves:
            return jsonify({
                "error": f"Aucun élève trouvé pour la classe {classe}"
            }), 404

        # 🔹 Calcul FIP pour chaque élève
        resultats = []
        for e in eleves:
            data = calcul_fip_eleve(e["matricule"])
            if data:
                resultats.append(data)

        total_attendu = sum(e["total_attendu"] for e in resultats)
        total_paye = sum(e["fip_total"] for e in resultats)
        solde_total = sum(e["solde_fip"] for e in resultats)

        return jsonify({
            "classe": classe,
            "classe_normalisee": classe_norm,
            "nb_eleves": len(resultats),
            "total_attendu_fip": round(total_attendu, 2),
            "total_paye_fip": round(total_paye, 2),
            "solde_total_fip": round(solde_total, 2),
            "eleves": resultats
        })

    except Exception as e:
        print("❌ ERREUR api_classe :", e)
        return jsonify({"error": "Erreur serveur"}), 500

    finally:
        if conn:
            conn.close()




# ===============================================================
# 🔵 13. /api/fip_section/<section> — Cumul FIP par section
# ===============================================================

@app.route("/admin/fip_section_result", methods=["GET"])
@login_required
def admin_fip_section_result():
    """
    Page HTML affichant le résultat FIP par section.
    """
    section = request.args.get("section", "").strip()
    mois = request.args.get("mois", "").strip()

    if not section:
        return "Section manquante", 400

    try:
        result = calcul_fip_section(section, mois)

        mois_affiches = (
            ", ".join(result["mois_cumul"])
            if result["mois_cumul"]
            else "Aucun paiement"
        )

        return f"""
<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<title>Résultat FIP Section</title>

<style>
body {{
    font-family: "Bookman Old Style", serif;
    background: linear-gradient(to right, #eef5ff, #ffffff);
}}

.container {{
    display: flex;
    justify-content: center;
    margin-top: 70px;
}}

.card {{
    background: white;
    padding: 35px 45px;
    border-radius: 16px;
    width: 520px;
    box-shadow: 0 12px 30px rgba(0,0,0,0.15);
}}

h2 {{
    text-align: center;
    color: #0d47a1;
}}

.highlight {{
    background: #e3f2fd;
    padding: 15px;
    border-radius: 10px;
    margin-top: 20px;
    text-align: center;
}}

.total {{
    font-size: 22px;
    font-weight: bold;
    color: #1b5e20;
}}

.actions {{
    margin-top: 30px;
    text-align: center;
}}

.actions a {{
    margin: 8px;
    padding: 10px 18px;
    background: #1976d2;
    color: white;
    border-radius: 8px;
    text-decoration: none;
}}
</style>
</head>

<body>

<div class="container">
<div class="card">

<h2>📊 FIP — SECTION</h2>

<p><b>Section :</b> {result["section"]}</p>
<p><b>Mois cumulés :</b> {mois_affiches}</p>

<div class="highlight">
    <div class="total">
        TOTAL PAYÉ : {result["total_paye"]}
    </div>
</div>

<div class="actions">
    <a href="/admin/fip">Nouvelle recherche</a>
    <a href="/admin/dashboard">Menu principal</a>
</div>

</div>
</div>

</body>
</html>
"""

    except Exception as e:
        print("❌ Erreur admin_fip_section_result :", e)
        return "Erreur interne serveur", 500



# ===============================================================
# 🔵 14. /api/fip_mois/<mois> — Total FIP par mois
# ===============================================================
@app.route("/api/fip_mois/<mois>")
def api_fip_mois(mois):
    try:
        result = calcul_fip_par_mois(mois)
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
        return jsonify({
        "status": "error",
        "message": "Import Excel désactivé sur Render. Importer en local."}), 503


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
#        Route  FIP MOIS   RESULTAT
#============================================   

@app.route("/admin/fip_mois_result", methods=["GET"])
@login_required
def admin_fip_mois_result():
    """
    Page HTML affichant le total FIP par mois (toutes sections).
    """
    mois = request.args.get("mois", "").strip()

    if not mois:
        return "Mois manquant", 400

    try:
        result = calcul_fip_par_mois(mois)

        rows_html = ""
        for section, montant in result["details_sections"].items():
            rows_html += f"""
            <tr>
                <td>{section}</td>
                <td>{montant}</td>
            </tr>
            """

        return f"""
<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<title>FIP Mensuel</title>

<style>
body {{
    font-family: "Bookman Old Style", serif;
    background: linear-gradient(to right, #e3f2fd, #ffffff);
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

h2 {{
    color: #0d47a1;
    margin-bottom: 20px;
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
    font-size: 20px;
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
}}
</style>
</head>

<body>

<div class="container">

<h2>📅 TOTAL FIP — MOIS : {result["mois"]}</h2>

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

<a href="/admin/fip" class="btn">← Retour</a>

</div>

</body>
</html>
"""

    except Exception as e:
        print("❌ Erreur admin_fip_mois_result :", e)
        return "Erreur interne serveur", 500




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


#===============================================
#   ROUTE /api/rapport_classe/<classe>
#=================================================

@app.route("/api/rapport_classe/<classe>")
@login_required
def rapport_pdf_classe(classe):
    """
    Génère un PDF par classe (montants payés ou mois non payés)
    Compatible toutes variantes de classe : 1°P, 1░P, 4°CG, etc.
    """

    type_pdf = request.args.get("type", "paye")

    # 🔹 Normalisation classe
    classe_norm = canonical_classe(classe)
    if not classe_norm:
        return "Classe invalide", 400

    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(row_factory=psycopg.rows.dict_row)

        # 🔹 Récupération élèves (robuste)
        cur.execute("""
            SELECT matricule, nom
            FROM eleves
            WHERE regexp_replace(UPPER(classe), '[^A-Z0-9]', '', 'g') = %s
            ORDER BY nom
        """, (classe_norm,))

        eleves = cur.fetchall()

        if not eleves:
            return f"Aucun élève trouvé pour la classe {classe}", 404

        lignes = []
        for e in eleves:
            data = calcul_fip_eleve(e["matricule"])
            if not data:
                continue

            valeur = (
                ", ".join(data["mois_non_payes"])
                if type_pdf == "impaye"
                else str(data["fip_total"])
            )

            lignes.append([
                e["matricule"],
                e["nom"],
                valeur
            ])

        # 🔹 Génération PDF (INCHANGÉE)
        os.makedirs("temp", exist_ok=True)
        path = os.path.join("temp", f"rapport_{classe_norm}_{type_pdf}.pdf")

        doc = SimpleDocTemplate(
            path,
            pagesize=A4,
            rightMargin=2*cm,
            leftMargin=2*cm,
            topMargin=2*cm,
            bottomMargin=2*cm
        )

        elements = []

        table_data = [["Matricule", "Nom", "Valeur"]] + lignes
        table = Table(table_data, colWidths=[3*cm, 7*cm, 5*cm])
        table.setStyle(TableStyle([
            ("GRID", (0,0), (-1,-1), 1, colors.black),
            ("BACKGROUND", (0,0), (-1,0), colors.lightgrey),
            ("ALIGN", (0,0), (-1,-1), "CENTER"),
        ]))

        elements.append(table)
        doc.build(elements)

        return send_file(path, as_attachment=True)

    except Exception as e:
        print("❌ ERREUR rapport_pdf_classe :", e)
        return "Erreur interne serveur", 500

    finally:
        if conn:
            conn.close()


    
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
@app.route("/admin/fip_eleve_result")
def admin_fip_eleve_result():
    """
    Affiche le résultat FIP élève (HTML).
    ⚠️ AUCUN recalcul ici : tout vient de calcul_fip_eleve()
    """

    matricule = request.args.get("matricule", "").strip()
    if not matricule:
        return "Matricule manquant", 400

    # 🔹 CALCUL MÉTIER UNIQUE
    data = calcul_fip_eleve(matricule)
    if not data:
        return "Élève introuvable", 404

    # 🔹 DONNÉES DIRECTEMENT ISSUES DU CALCUL CENTRAL
    fip_mensuel = data["fip_mensuel"]
    total_attendu = data["total_attendu"]
    total_paye = data["fip_total"]
    solde_fip = data["solde_fip"]
    mois_payes = data["mois_payes"]
    mois_non_payes = data["mois_non_payes"]

    # 🔹 INFOS ÉLÈVE
    eleve = {
        "matricule": data["matricule"],
        "nom": data["nom"],
        "sexe": data.get("sexe", ""),
        "classe": data["classe"],
        "section": data.get("section", ""),
        "categorie": data.get("categorie", ""),
        "telephone": data.get("telephone", "")
    }

    # 🔹 HTML (VISUEL INCHANGÉ)
    return f"""
<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<title>Résultat FIP Élève</title>

<style>
body {{
    font-family: "Bookman Old Style", serif;
    background: linear-gradient(to right, #f1f8ff, #ffffff);
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
.section p {{
    margin: 6px 0;
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
</style>
</head>

<body>

<div class="container">
<div class="card">

<h2>📋 FICHE FIP ÉLÈVE</h2>

<div class="section">
<p><b>Matricule :</b> {eleve['matricule']}</p>
<p><b>Nom :</b> {eleve['nom']}</p>
<p><b>Sexe :</b> {eleve['sexe']}</p>
<p><b>Classe :</b> {eleve['classe']}</p>
<p><b>Section :</b> {eleve['section']}</p>
<p><b>Catégorie :</b> {eleve['categorie']}</p>
<p><b>Téléphone :</b> {eleve['telephone']}</p>
</div>

<hr>

<div class="section">
<p><b>FIP mensuel :</b> {fip_mensuel}</p>
<p><b>Total attendu :</b> {total_attendu}</p>
<p><b>Total payé :</b> {round(total_paye, 2)}</p>
<p><b>Solde :</b> {round(solde_fip, 2)}</p>
</div>

<hr>

<div class="section">
<p><b>✅ Mois payés :</b> {", ".join(mois_payes) if mois_payes else "Aucun"}</p>
<p><b>❌ Mois non payés :</b> {", ".join(mois_non_payes) if mois_non_payes else "Aucun"}</p>
</div>

<div class="actions">
<a href="/admin1/gestion_eleve">← Retour</a>
</div>

</div>
</div>

</body>
</html>
"""




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

# ===============================================================
# 🔵 GESTION DES ÉLÈVES (FORMULAIRE)
# ===============================================================

@app.route("/admin1/gestion_eleve")
def gestion_eleve():
    return render_template_string(GESTION_ELEVE_HTML)


# ===============================================================
# 🔵 RECHERCHE DES MATRICULES PAR NUMÉRO DE TÉLÉPHONE
# ===============================================================

@app.route("/admin1/find_matricules_by_phone")
def find_matricules_by_phone():
    phone = request.args.get("phone", "").strip()

    # 🔹 Sécurité : entrée vide
    if not phone:
        return jsonify([])

    # 🔹 Normalisation stricte du numéro
    digits = "".join(c for c in phone if c.isdigit())

    # 🔹 Sécurité : minimum 6 chiffres
    if len(digits) < 6:
        return jsonify([])

    last9 = digits[-9:]

    try:
        conn = get_db_connection()
        cur = conn.cursor(row_factory=psycopg.rows.dict_row)

        query = """
        SELECT DISTINCT matricule
        FROM eleves
        WHERE telephone IS NOT NULL
          AND REPLACE(
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

        cur.execute(query, (f"%{last9}",))
        rows = cur.fetchall()

        # 🔹 Extraction propre
        result = [row["matricule"] for row in rows]

        return jsonify(result)

    except Exception as e:
        # ⚠️ Log utile Render / local
        print("❌ Erreur find_matricules_by_phone :", e)
        return jsonify([])

    finally:
        try:
            conn.close()
        except Exception:
            pass




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

    # Validation simple du format YYYY-MM-DD
    try:
        date_cible = datetime.strptime(date_input, "%Y-%m-%d").date()
    except ValueError:
        return "Date invalide", 400

    try:
        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor(row_factory=dict_row) as cur:

                query = """
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
                    WHERE p.datepaiement = %s
                    ORDER BY e.nom
                """
                cur.execute(query, (date_cible,))
                results = cur.fetchall()

        if not results:
            return f"""
            <h3 style="text-align:center;color:#c62828;">
                Aucun paiement trouvé pour le {date_input}
            </h3>
            <div style="text-align:center;">
                <a href="/admin/journal">← Retour</a>
            </div>
            """

        total_jour = sum(r["fip"] or 0 for r in results)

        rows = ""
        for r in results:
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

    except Exception as e:
        print("❌ ERREUR admin_journal_result :", e)
        return f"Erreur serveur : {e}", 500


#======================================
#       api/journal_pdf/<date_iso>"
#=======================================

@app.route("/api/journal_pdf/<date_iso>")
@login_required
def api_journal_pdf(date_iso):

    try:
        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor(row_factory=dict_row) as cur:

                cur.execute("""
                    SELECT
                        e.matricule,
                        e.nom,
                        e.classe,
                        p.mois,
                        p.fip
                    FROM paiements p
                    JOIN eleves e ON p.eleve_id = e.id
                    WHERE p.datepaiement = %s
                    ORDER BY e.nom
                """, (date_iso,))

                rows = cur.fetchall()

        if not rows:
            return "Aucune donnée", 404

        # 🔢 Calcul total journalier
        total = sum(r["fip"] or 0 for r in rows)

        # 📁 Dossier temporaire compatible Render
        os.makedirs("temp", exist_ok=True)
        file_path = os.path.join("temp", f"journal_{date_iso}.pdf")

        # 🧾 Génération PDF
        c = canvas.Canvas(file_path, pagesize=A4)
        c.setFont("Helvetica", 9)

        y = 800
        c.drawString(50, y, f"JOURNAL DES PAIEMENTS - {date_iso}")
        y -= 25

        for r in rows:
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

    except Exception as e:
        print("❌ ERREUR api_journal_pdf :", e)
        return f"Erreur serveur : {e}", 500


# ===============================================================
# 🔵 11. Lancement local
# ===============================================================
if __name__ == "__main__":
    print("🚀 API en mode LOCAL : http://127.0.0.1:5000")
    debug = not DATABASE_URL
    app.run(host="0.0.0.0", port=5000, debug=debug)




