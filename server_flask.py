# ===============================================================
# server_flask.py — VERSION STABLE SANS PANDAS (LOCAL + RENDER)
# ===============================================================

from flask import (
    Flask, jsonify, request,render_template,
    render_template_string, redirect,
    url_for, session, send_file
)

from functools import wraps
import os
import re
from datetime import datetime,timedelta
from datetime import date
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



""" Fonction métier centrale """

def annee_scolaire_from_date(d: date) -> str:
    """
    Règle métier officielle :
    - avant le 06 septembre → année N-1/N
    - à partir du 06 septembre → année N/N+1
    """
    if d.month < 9 or (d.month == 9 and d.day < 6):
        return f"{d.year-1}-{d.year}"
    return f"{d.year}-{d.year+1}"




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
    conn = get_db_connection()
    try:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(query, params or ())
            return cur.fetchall()
    finally:
        conn.close()


def fetch_one(query, params=None):
    conn = get_db_connection()
    try:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(query, params or ())
            return cur.fetchone()
    finally:
        conn.close()




# ===============================================================
# 🔹 Configuration générale
# ===============================================================

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "BJ2KEL24")



# ===============================================================
# 🔐 VARIABLES D’ENVIRONNEMENT — À DÉFINIR AVANT LES ROUTES
# ===============================================================

ADMIN_PASSWORDS = [
    p.strip()
    for p in os.environ.get("ADMIN_PASSWORDS", "").split(",")
    if p.strip()
]

COMPTA_PASSWORD = os.environ.get("COMPTA_PASSWORD")

DATABASE_URL = os.environ.get("DATABASE_URL")

FLASK_SECRET_KEY = os.environ.get("FLASK_SECRET_KEY", "BJ2KEL24")





# ⏱️ Durée de session (15 minutes)
app.permanent_session_lifetime = timedelta(minutes=15)



# 🔒 Sécurité cookies (à ajouter ici)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"


app.config["SESSION_COOKIE_SECURE"] = True



def login_user(role):
    session["role"] = role

def logout_user():
    session.pop("role", None)

def current_role():
    return session.get("role")

#==============================
# DÉCORATEURS DE SÉCURITÉ (PRO)
#===============================

def require_role(*roles):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            role = session.get("role")
            if role not in roles:
                return redirect("/admin/login")
            return f(*args, **kwargs)
        return wrapper
    return decorator
    

#==================
# DÉCORATEURS API
#==================

def require_api_role(*roles):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            role = session.get("role")
            if role not in roles:
                return jsonify({"error": "Unauthorized"}), 401
            return f(*args, **kwargs)
        return wrapper
    return decorator



@app.route("/connexion")
def connexion():
    return render_template("connexion.html")




@app.route("/thz")
def thz():
    return render_template("thz.html")


@app.route("/entreprise")
def entreprise():
    return render_template("index.html")




#================
#  ROUTE LOGIN
#================

@app.route("/login", methods=["POST"])
def login():

    password = request.form.get("password")

    if password in ADMIN_PASSWORDS:
        session["logged_in"] = True
        return redirect("/thz")

    else:
        return redirect("/")



#================
#  ROUTE ADMIN/LOGIN
#================


@app.route("/admin/login", methods=["GET", "POST"])

def admin_login():
    error = None

    if request.method == "POST":
        pwd = request.form.get("password", "").strip()

        if pwd in ADMIN_PASSWORDS:
            session["role"] = "admin"
            return redirect("/admin/dashboard")

        if COMPTA_PASSWORD and pwd == COMPTA_PASSWORD:
            session["role"] = "compta"
            return redirect("/admin/dashboard/finance")

        error = "Mot de passe incorrect."

    return render_template_string(LOGIN_FORM_HTML, error=error)


#================
#  ROUTE HOME
#===============


@app.route("/home")
def home():
    return render_template_string(HOME_HTML)





#====================
#  ROUTE DECONNEXION
#====================


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/admin/login")




@app.route("/test")
def test():
    return render_template("test.html")


@app.route("/db-test")
def db_test():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM caisse_journaliere")
            total = cur.fetchone()[0]

    return render_template("db_test.html", total=total)


@app.route("/caisse-list")
def caisse_list():
    annee = request.args.get("annee_scolaire")
    date_debut = request.args.get("date_debut")
    date_fin = request.args.get("date_fin")

    where = []
    params = []

    if annee:
        where.append("annee_scolaire = %s")
        params.append(annee)

    if date_debut:
        where.append("date_operation >= %s")
        params.append(date_debut)

    if date_fin:
        where.append("date_operation <= %s")
        params.append(date_fin)

    where_sql = "WHERE " + " AND ".join(where) if where else ""

    query = f"""
        SELECT
            date_operation,
            (report + bloc1 + bloc2 + bus1 + bus2) AS total
        FROM caisse_journaliere
        {where_sql}
        ORDER BY date_operation
        LIMIT 100
    """

    with get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(query, params)
            rows = cur.fetchall()

    return render_template(
        "caisse_list.html",
        rows=rows,
        annee=annee,
        date_debut=date_debut,
        date_fin=date_fin
    )


@app.route("/solde-list")
def solde_list():
    annee = request.args.get("annee_scolaire")
    date_debut = request.args.get("date_debut")
    date_fin = request.args.get("date_fin")

    where = []
    params = []

    if annee:
        where.append("c.annee_scolaire = %s")
        params.append(annee)

    if date_debut:
        where.append("c.date_operation >= %s")
        params.append(date_debut)

    if date_fin:
        where.append("c.date_operation <= %s")
        params.append(date_fin)

    where_sql = "WHERE " + " AND ".join(where) if where else ""

    query = f"""
    SELECT
        c.date_operation,
        c.annee_scolaire,
        c.report,
        c.bloc1,
        c.bloc2,
        c.bus1,
        c.bus2,
        (c.bloc1 + c.bloc2 + c.bus1 + c.bus2) AS tot_entr,
        COUNT(d.id) AS nb_depenses,
        COALESCE(SUM(d.montant), 0) AS total_dep,
        COALESCE(SUM(d.banque), 0) AS banque,
        (
            (c.bloc1 + c.bloc2 + c.bus1 + c.bus2 + c.report)
            - (COALESCE(SUM(d.montant), 0) + COALESCE(SUM(d.banque), 0))
        ) AS solde
    FROM caisse_journaliere c
    LEFT JOIN depense d
      ON d.date_depense = c.date_operation
     AND d.annee_scolaire = c.annee_scolaire
    {where_sql}
    GROUP BY
        c.date_operation,
        c.annee_scolaire,
        c.report,
        c.bloc1, c.bloc2, c.bus1, c.bus2
    ORDER BY c.date_operation
    LIMIT 100
    """


    with get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(query, params)
            rows = cur.fetchall()

    return render_template(
        "solde_list.html",
        rows=rows,
        annee=annee,
        date_debut=date_debut,
        date_fin=date_fin
    )



@app.route("/depenses-list")
def depenses_list():
    annee = request.args.get("annee_scolaire")
    date_debut = request.args.get("date_debut")
    date_fin = request.args.get("date_fin")

    where = []
    params = []

    if annee:
        where.append("annee_scolaire = %s")
        params.append(annee)

    if date_debut:
        where.append("date_depense >= %s")
        params.append(date_debut)

    if date_fin:
        where.append("date_depense <= %s")
        params.append(date_fin)

    where_sql = "WHERE " + " AND ".join(where) if where else ""

    query = f"""
        SELECT
            date_depense,
            ref_dp,
            libelle,
            montant,
            banque
        FROM depense
        {where_sql}
        ORDER BY date_depense
        LIMIT 100
    """

    with get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(query, params)
            rows = cur.fetchall()

    return render_template(
        "depenses.html",
        rows=rows,
        annee=annee,
        date_debut=date_debut,
        date_fin=date_fin
    )




@app.route("/resume-journalier")
@require_role("admin", "compta")   # 🔐 Sécurité recommandée
def resume_journalier():

    # ======================================================
    # 🔹 PARAMÈTRES
    # ======================================================
    annee = request.args.get("annee", "2025-2026")
    date_debut = request.args.get("date_debut")
    date_fin = request.args.get("date_fin")

    # ======================================================
    # 🔹 WHERE DYNAMIQUE
    # ======================================================
    where_clauses = ["c.annee_scolaire = %s"]
    params = [annee]

    if date_debut:
        where_clauses.append("c.date_operation >= %s")
        params.append(date_debut)

    if date_fin:
        where_clauses.append("c.date_operation <= %s")
        params.append(date_fin)

    where_sql = "WHERE " + " AND ".join(where_clauses)

    # ======================================================
    # 🔹 REQUÊTE SQL (LOGIQUE MÉTIER OFFICIELLE)
    # ======================================================
    query = f"""
        SELECT
            c.date_operation AS date_jour,

            COALESCE(c.report,0) AS report,
            COALESCE(c.bloc1,0)  AS bloc1,
            COALESCE(c.bloc2,0)  AS bloc2,
            COALESCE(c.bus1,0)   AS bus1,
            COALESCE(c.bus2,0)   AS bus2,

            -- ✅ Total Entré SANS report
            (COALESCE(c.bloc1,0) + COALESCE(c.bloc2,0) +
             COALESCE(c.bus1,0)  + COALESCE(c.bus2,0)) AS tot_entr,

            COALESCE(d.nb_depenses,0)   AS nb_depenses,
            COALESCE(d.total_cash,0)    AS total_depenses,
            COALESCE(d.total_banque,0)  AS banque,

            -- ✅ Solde réel = (Entré + Report) - Dépenses
            (
                (COALESCE(c.report,0) +
                 COALESCE(c.bloc1,0) +
                 COALESCE(c.bloc2,0) +
                 COALESCE(c.bus1,0) +
                 COALESCE(c.bus2,0))
                -
                (COALESCE(d.total_cash,0) + COALESCE(d.total_banque,0))
            ) AS solde

        FROM caisse_journaliere c

        LEFT JOIN (
            SELECT
                date_depense,
                annee_scolaire,
                COUNT(*) AS nb_depenses,
                SUM(COALESCE(montant,0)) AS total_cash,
                SUM(COALESCE(banque,0))  AS total_banque
            FROM depense
            GROUP BY date_depense, annee_scolaire
        ) d
          ON d.date_depense = c.date_operation
         AND d.annee_scolaire = c.annee_scolaire

        {where_sql}
        ORDER BY c.date_operation
    """

    rows = fetch_all(query, tuple(params))

    # ======================================================
    # 🔹 TOTAUX GÉNÉRAUX (RÈGLE MÉTIER)
    # ======================================================
    totaux = {
        "report": 0,
        "bloc1": 0,
        "bloc2": 0,
        "bus1": 0,
        "bus2": 0,
        "tot_entr": 0,
        "total_depenses": 0,
        "banque": 0,
        "solde": 0
    }

    for r in rows:
        totaux["report"] += r["report"]
        totaux["bloc1"] += r["bloc1"]
        totaux["bloc2"] += r["bloc2"]
        totaux["bus1"]  += r["bus1"]
        totaux["bus2"]  += r["bus2"]
        totaux["total_depenses"] += r["total_depenses"]
        totaux["banque"] += r["banque"]

    # ✅ Total Entré réel (sans report)
    totaux["tot_entr"] = (
        totaux["bloc1"] +
        totaux["bloc2"] +
        totaux["bus1"] +
        totaux["bus2"]
    )

    # ✅ Solde final = dernier jour affiché
    totaux["solde"] = rows[-1]["solde"] if rows else 0

    return render_template(
        "resume_journalier.html",
        rows=rows,
        totaux=totaux,
        annee=annee,
        date_debut=date_debut,
        date_fin=date_fin
    )





@app.route("/")
def index():
    return render_template("index.html")




#===========Modal B1=======Page /thz

@app.route("/acces-admin-panel", methods=["POST"])
def acces_admin_panel():

    data = request.get_json(silent=True) or {}
    password = data.get("password","")

    # ADMIN_PASSWORDS est déjà défini chez toi
    if password in ADMIN_PASSWORDS:
        session["admin"] = True
        session.permanent = True
        return jsonify({"ok": True})

    return jsonify({"ok": False})



#===========Modal B2=======Page /thz


@app.route("/acces-resume-journalier", methods=["POST"])
def acces_resume_journalier():

    data = request.get_json()
    password = data.get("password", "")

    # 🔐 vérification avec la variable déjà existante
    if password == COMPTA_PASSWORD:
        session["auth_compta"] = True
        session.permanent = True   # 🔥 IMPORTANT
        return jsonify({"ok": True})

    return jsonify({"ok": False})






# mots de passe admin


# Mois officiels
MOIS_SCOLAIRE = [
    "Sept", "Oct", "Nov", "Dec", "Janv", "Fevr",
    "Mars", "Avr", "Mai", "Juin"
]



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




@app.route("/api/ping")
def ping():
    return jsonify({"message": "API en ligne"})


@app.route("/api/eleve/<matricule>")
def api_eleve(matricule):
    conn = get_db_connection()
    try:
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
        return jsonify({"error": "Erreur serveur"}), 500

    finally:
        conn.close()


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

    # ---------------------------
    # 1️⃣ Connexion DB UNIQUE
    # ---------------------------
    conn = get_db_connection()

    try:
        with conn.cursor(row_factory=dict_row) as cur:

            # ---------------------------
            # 2️⃣ Nombre d'élèves
            # ---------------------------
            cur.execute("SELECT COUNT(*) AS total FROM eleves;")
            nb_eleves = cur.fetchone()["total"]

            # ---------------------------
            # 3️⃣ Nombre de paiements
            # ---------------------------
            cur.execute("SELECT COUNT(*) AS total FROM paiements;")
            nb_paiements = cur.fetchone()["total"]

            # ---------------------------
            # 4️⃣ Total FIP payé
            # ---------------------------
            cur.execute(
                "SELECT COALESCE(SUM(fip), 0) AS total FROM paiements;"
            )
            total_fip = cur.fetchone()["total"]

            # ---------------------------
            # 5️⃣ Nombre de classes actives
            # ---------------------------
            cur.execute("""
                SELECT COUNT(DISTINCT classe) AS total
                FROM eleves
                WHERE classe IS NOT NULL;
            """)
            nb_classes = cur.fetchone()["total"]

        # ---------------------------
        # 6️⃣ Réponse JSON propre
        # ---------------------------
        return jsonify({
            "nb_eleves": int(nb_eleves),
            "nb_paiements": int(nb_paiements),
            "nb_classes": int(nb_classes),
            "total_fip_paye": round(float(total_fip), 2)
        })

    except Exception as e:
        print("❌ ERREUR API DASHBOARD :", e)
        return jsonify({"error": "Erreur serveur dashboard"}), 500

    finally:
        conn.close()



# ===============================================================
# 🔵 18. PDF par Classe (étape 1)
# ===============================================================
PDF_CLASSE_HTML = """
<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<!-- CSS MOBILE -->
<link rel="stylesheet" href="{{ url_for('static', filename='css/mobile.css') }}">
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
@require_role("admin", "compta")

def admin_pdf_classe():
    return render_template_string(PDF_CLASSE_HTML)


@app.route("/admin/pdf_classe_choix")
@require_role("admin", "compta")

def admin_pdf_classe_choix():
    classe = request.args.get("classe", "").strip()

    if not classe:
        return "Classe manquante", 400

    html = f"""
    <!DOCTYPE html>
    <html lang="fr">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <!-- CSS MOBILE -->
        <link rel="stylesheet" href="{{ url_for('static', filename='css/mobile.css') }}">
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
@require_role("admin", "compta")

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
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<!-- CSS MOBILE -->
<link rel="stylesheet" href="{{ url_for('static', filename='css/mobile.css') }}">
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
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<!-- CSS MOBILE -->
<link rel="stylesheet" href="{{ url_for('static', filename='css/mobile.css') }}">
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







# ===============================================================
# 🔵 12. Interface et routes upload Excel
# ===============================================================

UPLOAD_FORM_HTML = """
<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <!-- CSS MOBILE -->
    <link rel="stylesheet" href="{{ url_for('static', filename='css/mobile.css') }}">
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
@require_role("admin", "compta")

def admin_upload_form():
    return render_template_string(UPLOAD_FORM_HTML)

@app.route("/admin/upload_excel", methods=["POST"])
@require_role("admin", "compta")

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
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<!-- CSS MOBILE -->
<link rel="stylesheet" href="{{ url_for('static', filename='css/mobile.css') }}">
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
@require_role("admin", "compta")

def admin_fip_form():
    return render_template_string(FIP_FORM_HTML)
 



#==============================================
#        Route  FIP MOIS   RESULTAT
#============================================   

@app.route("/admin/fip_mois_result", methods=["GET"])
@require_role("admin", "compta")

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
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<!-- CSS MOBILE -->
<link rel="stylesheet" href="{{ url_for('static', filename='css/mobile.css') }}">
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
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<!-- CSS MOBILE -->
<link rel="stylesheet" href="{{ url_for('static', filename='css/mobile.css') }}">
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
        <a href="/admin1/panel" class="menu-btn logout">🚪 Déconnexion</a>
        

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
@require_role("admin", "compta")


def admin_dashboard():
    return render_template_string(DASHBOARD_HTML)


#===============================================
#   ROUTE /api/rapport_classe/<classe>
#=================================================

@app.route("/api/rapport_classe/<classe>")

def rapport_pdf_classe(classe):

    type_pdf = request.args.get("type", "paye")
    classe_norm = canonical_classe(classe)
    if not classe_norm:
        return "Classe invalide", 400

    try:
        # ==================================================
        # 🔹 1) CONNEXION DB UNIQUE
        # ==================================================
        conn = get_db_connection()
        cur = conn.cursor(row_factory=dict_row)

        # ==================================================
        # 🔹 2) RÉCUPÉRATION DES ÉLÈVES
        # ==================================================
        cur.execute("""
            SELECT id, matricule, nom
            FROM eleves
            WHERE regexp_replace(UPPER(classe), '[^A-Z0-9]', '', 'g') = %s
            ORDER BY nom
        """, (classe_norm,))
        eleves = cur.fetchall()

        if not eleves:
            conn.close()
            return f"Aucun élève trouvé pour la classe {classe}", 404

        # ==================================================
        # 🔹 3) RÉCUPÉRATION DES PAIEMENTS (UNE SEULE REQUÊTE)
        # ==================================================
        cur.execute("""
            SELECT
                e.matricule,
                p.mois,
                COALESCE(p.fip,0) AS fip
            FROM paiements p
            JOIN eleves e ON p.eleve_id = e.id
            WHERE regexp_replace(UPPER(e.classe), '[^A-Z0-9]', '', 'g') = %s
        """, (classe_norm,))
        paiements = cur.fetchall()

        conn.close()

        # ==================================================
        # 🔹 4) ORGANISATION EN MÉMOIRE
        # ==================================================
        pay_map = {}
        for p in paiements:
            m = canonical_month(p["mois"])
            if not m:
                continue
            pay_map.setdefault(p["matricule"], {}).setdefault(m, 0)
            pay_map[p["matricule"]][m] += float(p["fip"])

        # ==================================================
        # 🔹 5) CONSTRUCTION DES LIGNES PDF
        # ==================================================
        lignes = []
        total_general = 0.0

        for i, e in enumerate(eleves, start=1):

            paiements_eleve = pay_map.get(e["matricule"], {})
            mois_payes = sorted(
                paiements_eleve.keys(),
                key=lambda m: MOIS_SCOLAIRE.index(m)
            )

            total_paye = sum(paiements_eleve.values())

            mois_non_payes = [
                m for m in MOIS_SCOLAIRE
                if m not in mois_payes
            ]

            if type_pdf == "paye":
                lignes.append([
                    i,
                    e["matricule"],
                    e["nom"],
                    round(total_paye, 2),      # ✅ Valeur calculée
                    ", ".join(mois_payes)
                ])
                total_general += total_paye
            else:
                lignes.append([
                    i,
                    e["matricule"],
                    e["nom"],
                    ", ".join(mois_non_payes)
                ])

        # ==================================================
        # 🔹 6) LIGNE TOTAL GÉNÉRAL
        # ==================================================
        if type_pdf == "paye":
            lignes.append([
                "",
                "",
                "TOTAL",
                round(total_general, 2),     # ✅ TOTAL FINAL
                ""
            ])

        # ==================================================
        # 🔹 7) GÉNÉRATION DU PDF
        # ==================================================
        os.makedirs("temp", exist_ok=True)
        path = f"temp/rapport_{classe_norm}_{type_pdf}.pdf"

        doc = SimpleDocTemplate(
            path,
            pagesize=A4,
            rightMargin=2*cm,
            leftMargin=2*cm,
            topMargin=2*cm,
            bottomMargin=2*cm
        )

        elements = []

        # LOGO
        logo = "static/images/logo_csnst.png"
        if os.path.exists(logo):
            elements.append(Image(logo, 3*cm, 2.3*cm))
        elements.append(Spacer(1, 12))

        # TITRE
        titre = (
            f"LISTE DES MOIS PAYÉS<br/>POUR LA CLASSE DE : <b>{classe_norm}</b>"
            if type_pdf == "paye"
            else f"LISTE DES MOIS NON PAYÉS<br/>POUR LA CLASSE DE : <b>{classe_norm}</b>"
        )
        elements.append(Paragraph(
            titre,
            ParagraphStyle("title", fontSize=14, alignment=1, spaceAfter=20)
        ))

        # TABLE
        headers = (
            ["N°", "Matricule", "Nom", "Valeur", "Mois payés"]
            if type_pdf == "paye"
            else ["N°", "Matricule", "Nom", "Valeur"]
        )

        table = Table([headers] + lignes, repeatRows=1)
        table.setStyle(TableStyle([
            ("GRID", (0,0), (-1,-1), 1, colors.grey),
            ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#1976d2")),
            ("TEXTCOLOR", (0,0), (-1,0), colors.white),
            ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
            ("ALIGN", (0,1), (0,-1), "CENTER"),
            ("ALIGN", (1,1), (2,-1), "LEFT"),
            ("ALIGN", (3,1), (3,-1), "CENTER"),
            ("ALIGN", (4,1), (4,-1), "LEFT"),
        ]))

        elements.append(table)
        doc.build(elements)

        return send_file(path, as_attachment=True)

    except Exception as e:
        print("❌ ERREUR PDF CLASSE :", e)
        return "Erreur interne serveur", 500


    
 #==========================================
 #  HTML de confirmation
 #==========================================

CONFIRM_IMPORT_HTML = """
<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<!-- CSS MOBILE -->
<link rel="stylesheet" href="{{ url_for('static', filename='css/mobile.css') }}">
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
@require_role("admin", "compta")

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
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<!-- CSS MOBILE -->
<link rel="stylesheet" href="{{ url_for('static', filename='css/mobile.css') }}">
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
@require_role("admin", "compta")

def admin_fip_eleve():
    return render_template_string(FIP_ELEVE_FORM_HTML)


 
#==============================================
#RESULTAT ELEVE (Recherche par Numéro Matricule
#============================================== 

@app.route("/admin/fip_eleve_result")
@require_role("admin", "compta")

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
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<!-- CSS MOBILE -->
<link rel="stylesheet" href="{{ url_for('static', filename='css/mobile.css') }}">
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
<!--<meta name="viewport" content="width=device-width, initial-scale=1.0"> -->
<!-- CSS MOBILE -->
<!--<link rel="stylesheet" href="{{ url_for('static', filename='css/mobile.css') }}">  -->
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

/* =========================
   EN-TÊTE ADMIN PANEL
   ========================= */

.admin-header {
    display: grid;
    grid-template-columns: auto 1fr auto;
    align-items: center;
    padding: 20px 30px;
    gap: 25px;
}

.admin-left {
    display: flex;
    align-items: center;
    gap: 15px;
}

.admin-logo {
    height: 90px;
}

.admin-band {
    width: 340px;
}

.band-blue {
    height: 7px;
    background: #0d47a1;
}

.band-red {
    height: 7px;
    background: #c62828;
}

.admin-marquee {
    height: 26px;
    overflow: hidden;
    position: relative;
    background: #fff;
}

.admin-marquee span {
    position: absolute;
    white-space: nowrap;
    font-size: 14px;
    font-weight: bold;
    color: #0d47a1;
    animation: scroll-left 14s linear infinite;
}

.admin-center {
    text-align: center;
}



/* LOGO ECUSON */

.admin-logo-center {
    height: 85px;          /* proche du cercle THZ */
    display: block;
    margin: 0 auto;
    object-fit: contain;
    
    /* 🎯 AJUSTEMENT PRO : vers la gauche */
    transform: translateX(-110px);
}


.header-right {
    text-align: right;
    font-weight: bold;
    line-height: 1.2;
}

.school-black {
    color: #000000;
    font-size: 16px;
}

.school-red {
    color: #c62828;
    font-size: 17px;
    letter-spacing: 1px;
}



.admin-right {
    text-align: right;
    font-family: "Bookman Old Style", serif;
}

.institution-text {
    margin-bottom: 10px;
    line-height: 1.2;
}

.school-black {
    color: #000;
    font-size: 20px;
    font-weight: bold;
}

.school-red {
    color: #c62828;
    font-size: 17px;
    font-weight: bold;
    letter-spacing: 1px;
}

.btn-logout {
    display: inline-block;
    padding: 6px 16px;
    background-color: #c62828;
    color: white;
    font-size: 13px;
    font-weight: bold;
    border-radius: 6px;
    text-decoration: none;
    transition: all 0.25s ease;
}

.btn-logout:hover {
    background-color: #8e0000;
    transform: scale(1.05);
}




@keyframes scroll-left {
    from { transform: translateX(100%); }
    to { transform: translateX(-100%); }
}


.admin-separator {
    height: 2px;
    width: 80%;
    margin: 25px auto;
    background: linear-gradient(
        to right,
        transparent,
        #0d47a1,
        #c62828,
        #0d47a1,
        transparent
    );
}

.logout-box {
    margin-top: 10px;
}

.btn-logout {
    display: inline-block;
    padding: 6px 14px;
    background-color: #c62828;
    color: white;
    font-size: 13px;
    font-weight: bold;
    border-radius: 6px;
    text-decoration: none;
    transition: 0.3s;
}

.btn-logout:hover {
    background-color: #8e0000;
}

/* =========================
   SÉPARATEUR THZ
   ========================= */

.thz-divider {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 100%;
    margin: 0px 0 18px 0;
    animation: fadeSlideDown 0.8s ease-out;
}

.thz-divider .line {
    flex: 1;
    height: 6px;
}

.thz-divider .line.left {
    background: linear-gradient(to right, #0aa84f, #1abc9c);
}

.thz-divider .line.right {
    background: linear-gradient(to left, #c62828, #e53935);
}



.thz-circle {
    width: 65px;
    height: 65px;

    border-radius: 50%;
    background: linear-gradient(145deg, #3f6fb6, #2c5aa0);

    color: white;
    font-family: "Bookman Old Style", serif;
    font-size: 20px;
    font-weight: bold;

    display: flex;
    align-items: center;
    justify-content: center;

    border: 3px solid white;
    box-shadow: 0 6px 14px rgba(0,0,0,0.25);

    z-index: 2;
    animation: pulseSoft 2.5s ease-in-out infinite;
}



.thz-center {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 8px; /* espace cercle ↔ bouton */
    z-index: 2;
}

.btn-gestion-caisse {
    display: inline-flex;
    align-items: center;
    gap: 6px;

    padding: 7px 18px;
    font-size: 13px;
    font-family: "Bookman Old Style", serif;
    font-weight: bold;

    color: #0d47a1;
    background: linear-gradient(145deg, #ffffff, #f1f3f6);
    border: 1.5px solid #0d47a1;
    border-radius: 22px;

    text-decoration: none;
    cursor: pointer;

    box-shadow: 0 4px 10px rgba(0,0,0,0.12);
    transition: all 0.25s ease;
}

.btn-gestion-caisse:hover {
    background: #0d47a1;
    color: white;
    transform: translateY(-2px);
    box-shadow: 0 6px 16px rgba(0,0,0,0.25);
}





@keyframes fadeSlideDown {
    from {
        opacity: 0;
        transform: translateY(-8px);
    }
    to {
        opacity: 1;
        transform: translateY(0);
    }
}


@keyframes pulseSoft {
    0% {
        transform: scale(1);
        box-shadow: 0 0 0 rgba(13, 71, 161, 0.4);
    }
    50% {
        transform: scale(1.05);
        box-shadow: 0 0 12px rgba(13, 71, 161, 0.4);
    }
    100% {
        transform: scale(1);
        box-shadow: 0 0 0 rgba(13, 71, 161, 0.4);
    }
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

<!-- ===== MODALE AIDE FIN ===== -->

<!-- ===== JAVA SCRIPTS ======== -->

<script>
function ouvrirAide() {
    document.getElementById("aideModal").style.display = "block";
}

function fermerAide() {
    document.getElementById("aideModal").style.display = "none";
}
</script>

<!-- ======JAVA SCRIPTS FIN======== -->


<body>

<!-- ================= EN-TÊTE ADMIN PRO ================= -->

<div class="admin-header">

    <!-- GAUCHE : logo + bandes + texte défilant -->
    
    <div class="admin-left">
        <img src="/static/images/logo_csnst.png" class="admin-logo">

        <div class="admin-band">
            <div class="band-blue"></div>
            <div class="band-red"></div>
            <div class="admin-marquee">
                <span>
                    Gestion comptable — Suivi de la caisse — Contrôle des dépenses — Transparence financière
                </span>
            </div>
        </div>
    </div>

    <!-- CENTRE : logo secondaire -->
    <div class="admin-center">
        <img src="/static/images/logo_csnst1.png"
             alt="Emblème CSNST"
             class="admin-logo-center">
    </div>

    <!-- DROITE : nom école + déconnexion -->
      <!-- DROITE : institution + déconnexion -->
            <div class="admin-right">

                <div class="institution-text">
                    <span class="school-black">COMPLEXE SCOLAIRE</span><br>
                    <span class="school-red">NSANGA LE THANZIE</span>
                </div>

                <a href="/" class="btn-logout">
                    🔓 Déconnexion
                </a>

            </div>


</div>      


<!-- ================= FIN EN-TÊTE ADMIN ================= -->


<!-- <div class="band-blue"></div> -->

<!-- <div class="marquee-box">
    <marquee>
        Complexe Scolaire Nsanga le Thanzie : . Pour consulter les FIPs de vos élèves :Cliquez sur le bouton Gestion Élève. Saisissez votre numéro de téléphone. Validez votre saisie. Sélectionnez ensuite le PL ou le LT de l’élève concerné.Merci pour votre confiance.

    </marquee>
 </div>  -->



<!--<SEPARATEUR ENTRE ENTET ET PANNEAU -->

<!-- ===== LIGNE DE SÉPARATION THZ === -->

<div class="thz-divider">

    <span class="line left"></span>

    <div class="thz-center">
    
  
    <!-- CERCLE THZ -->
    
        <div class="thz-circle">THZ</div>
         
         <!-- BOUTON UNIQUE -->
         
        <a href="/thz" class="btn-admin">
           🧾 RETOUR Home
        </a>
    </div>

    <span class="line right"></span>

</div>



<div class="panel">

    <h2>PANNEAU ADMIN</h2>

    <a href="/admin/login">🔐 Connexion Administrateur</a>
    <a href="/admin1/gestion_eleve">📊 Gestion Élèves</a>
    <a href="#">📘 Journal Paiements</a>
    <a href="#">📄 Rapports</a>
    <a href="#">📅 Statistiques</a>
    <a href="/admin/login">🧾 Comptabilité</a>
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
@require_role("admin", "compta")

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
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<!-- CSS MOBILE -->
<link rel="stylesheet" href="{{ url_for('static', filename='css/mobile.css') }}">
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
@require_role("admin", "compta")

def gestion_eleve():
    return render_template_string(GESTION_ELEVE_HTML)


# ===============================================================
# 🔵 RECHERCHE DES MATRICULES PAR NUMÉRO DE TÉLÉPHONE
# ===============================================================

@app.route("/admin1/find_matricules_by_phone")
@require_role("admin", "compta")

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
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<!-- CSS MOBILE -->
<link rel="stylesheet" href="{{ url_for('static', filename='css/mobile.css') }}">
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
@require_role("admin", "compta")

def admin_journal():
    return render_template_string(JOURNAL_HTML)
    
    
@app.route("/admin/journal_result")
@require_role("admin", "compta")
def admin_journal_result():

    date_input = request.args.get("date")
    if not date_input:
        return "Date manquante", 400

    # ---------------------------
    # 1️⃣ Validation date
    # ---------------------------
    try:
        date_cible = datetime.strptime(date_input, "%Y-%m-%d").date()
    except ValueError:
        return "Date invalide", 400

    # ---------------------------
    # 2️⃣ Connexion DB UNIQUE
    # ---------------------------
    conn = get_db_connection()
    try:
        with conn.cursor(row_factory=dict_row) as cur:

            query = """
                SELECT
                    e.matricule,
                    e.nom,
                    e.classe,
                    e.section,
                    p.mois,
                    p.fip,
                    p.numrecu
                FROM paiements p
                JOIN eleves e ON p.eleve_id = e.id
                WHERE p.datepaiement >= %s
                  AND p.datepaiement < %s
                ORDER BY e.nom
            """

            cur.execute(
                query,
                (date_cible, date_cible + timedelta(days=1))
            )

            results = cur.fetchall()

        # ---------------------------
        # 3️⃣ Aucun paiement
        # ---------------------------
        if not results:
            return f"""
            <h3 style="text-align:center;color:#c62828;">
                Aucun paiement trouvé pour le {date_input}
            </h3>
            <div style="text-align:center;">
                <a href="/admin/journal">← Retour</a>
            </div>
            """

        # ---------------------------
        # 4️⃣ Total journalier
        # ---------------------------
        total_jour = sum((r["fip"] or 0) for r in results)

        # ---------------------------
        # 5️⃣ Lignes tableau
        # ---------------------------
        rows_html = ""
        for i, r in enumerate(results, start=1):
            rows_html += f"""
            <tr>
                <td>{i}</td>
                <td>{r['matricule']}</td>
                <td>{r['nom']}</td>
                <td>{r['classe']}</td>
                <td>{r['section']}</td>
                <td>{r['mois']}</td>
                <td>{r['fip']}</td>
                <td>{r['numrecu']}</td>
            </tr>
            """

        # ---------------------------
        # 6️⃣ HTML final
        # ---------------------------
        return f"""
        <!DOCTYPE html>
        <html lang="fr">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <!-- CSS MOBILE -->
            <link rel="stylesheet" href="{{ url_for('static', filename='css/mobile.css') }}">
            <title>Journal des paiements du {date_input}</title>
            <style>
                body {{
                    font-family: "Bookman Old Style", serif;
                    background: #f4f8ff;
                }}
                table {{
                    width: 90%;
                    margin: 40px auto;
                    border-collapse: collapse;
                    background: white;
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
                tfoot td {{
                    font-weight: bold;
                    background: #e3f2fd;
                }}
            </style>
        </head>
        <body>

        <div style="display:flex;align-items:center;padding:15px 40px;">
            <img src="/static/images/logo_csnst.png" style="height:75px;">
            <h2 style="margin-left:20px;color:#0d47a1;">
                📘 Journal des paiements du {date_input}
            </h2>
        </div>

        <table>
            <thead>
                <tr>
                    <th>N°</th>
                    <th>Matricule</th>
                    <th>Nom</th>
                    <th>Classe</th>
                    <th>Section</th>
                    <th>Mois</th>
                    <th>Montant</th>
                    <th>Reçu</th>
                </tr>
            </thead>
            <tbody>
                {rows_html}
            </tbody>
            <tfoot>
                <tr>
                    <td colspan="6">TOTAL JOURNÉE</td>
                    <td>{total_jour}</td>
                    <td></td>
                </tr>
            </tfoot>
        </table>

        <div style="text-align:center;">
            <a href="/admin/journal">← Retour</a>
        </div>

        <div style="text-align:center;margin:30px;">
            <a href="/api/journal_pdf/{date_input}"
               style="
                display:inline-block;
                padding:12px 30px;
                background:#1976d2;
                color:white;
                text-decoration:none;
                border-radius:10px;
                font-size:16px;
               ">
                🖨️ Imprimer le PDF
            </a>
        </div>

        </body>
        </html>
        """

    except Exception as e:
        print("❌ ERREUR admin_journal_result :", e)
        return "Erreur serveur", 500

    finally:
        conn.close()


@app.route("/api/journal_pdf/<date_iso>")
def api_journal_pdf(date_iso):
    conn = get_db_connection()
    try:
        # ---------------------------
        # 1️⃣ Validation de la date
        # ---------------------------
        date_cible = datetime.strptime(date_iso, "%Y-%m-%d").date()

        # ---------------------------
        # 2️⃣ Requête base de données
        # ---------------------------
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("""
                SELECT
                    e.matricule,
                    e.nom,
                    e.classe,
                    e.section,
                    p.mois,
                    p.fip,
                    p.numrecu
                FROM paiements p
                JOIN eleves e ON p.eleve_id = e.id
                WHERE p.datepaiement = %s
                ORDER BY e.nom
            """, (date_cible,))
            rows = cur.fetchall()

        if not rows:
            return "Aucune donnée à imprimer", 404

        # ---------------------------
        # 3️⃣ Calcul du total
        # ---------------------------
        total = sum((r["fip"] or 0) for r in rows)

        # ---------------------------
        # 4️⃣ Préparation PDF
        # ---------------------------
        os.makedirs("temp", exist_ok=True)
        path = f"temp/journal_{date_iso}.pdf"

        doc = SimpleDocTemplate(
            path,
            pagesize=A4,
            rightMargin=2 * cm,
            leftMargin=2 * cm,
            topMargin=2 * cm,
            bottomMargin=2 * cm
        )

        elements = []

        # ---------------------------
        # 5️⃣ Logo
        # ---------------------------
        logo_path = "static/images/logo_csnst.png"
        if os.path.exists(logo_path):
            elements.append(Image(logo_path, width=4 * cm, height=3 * cm))

        elements.append(Spacer(1, 12))

        # ---------------------------
        # 6️⃣ Titre
        # ---------------------------
        title_style = ParagraphStyle(
            name="Title",
            fontSize=14,
            alignment=1,
            spaceAfter=20
        )
        elements.append(
            Paragraph(
                f"<b>Journal des paiements du {date_iso}</b>",
                title_style
            )
        )

        # ---------------------------
        # 7️⃣ Tableau
        # ---------------------------
        table_data = [[
            "N°", "Matricule", "Nom", "Classe",
            "Section", "Mois", "Montant", "Reçu"
        ]]

        for i, r in enumerate(rows, start=1):
            table_data.append([
                i,
                r["matricule"],
                r["nom"],
                r["classe"],
                r["section"],
                r["mois"],
                r["fip"],
                r["numrecu"]
            ])

        table_data.append([
            "", "", "", "", "", "TOTAL",
            total, ""
        ])

        table = Table(
            table_data,
            colWidths=[
                1.2 * cm, 2.2 * cm, 5 * cm, 1.7 * cm,
                1.7 * cm, 1.7 * cm, 2 * cm, 2 * cm
            ]
        )

        table.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.8, colors.grey),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1976d2")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
            ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#e3f2fd")),
        ]))

        elements.append(table)

        # ---------------------------
        # 8️⃣ Footer
        # ---------------------------
        footer_style = ParagraphStyle(
            name="Footer",
            fontSize=8,
            alignment=1,
            textColor=colors.grey,
            spaceBefore=25
        )

        footer_text = """
        <b>Comptabilité – CS Nsanga le Thanzie</b><br/>
        165 Av Kasangulu, croisement de l’Église<br/>
        Email : notificationnsangalethanzie@gmail.com<br/>
        Tél : +243 974 773 760 | +243 970 292 522 | +243 996 537 573
        """

        elements.append(Spacer(1, 20))
        elements.append(Paragraph(footer_text, footer_style))

        # ---------------------------
        # 9️⃣ Génération PDF
        # ---------------------------
        doc.build(elements)

        return send_file(path, as_attachment=True)

    except Exception as e:
        print("❌ ERREUR PDF JOURNAL :", e)
        return "Erreur PDF", 500

    finally:
        conn.close()




#================================================
#  CODE FLASK — VERSION PRO AVEC COMMENTAIRES
#================================================

@app.route("/api/dashboard/finance")
@require_api_role("admin", "compta")
def api_dashboard_finance():
    """
    Tableau de bord financier – KPI principaux

    Cette route retourne uniquement des indicateurs chiffrés,
    sans HTML, afin d'être utilisée par :
    - le dashboard web
    - des graphiques
    - une application mobile
    """

    try:
        # ----------------------------------------------------
        # 1️⃣ Connexion à la base de données
        # ----------------------------------------------------
        # Une seule connexion = performance + stabilité
        conn = get_db_connection()
        cur = conn.cursor(row_factory=dict_row)

        # ----------------------------------------------------
        # 2️⃣ KPI : Nombre total d'élèves
        # ----------------------------------------------------
        cur.execute("SELECT COUNT(*) AS total FROM eleves;")
        nb_eleves = cur.fetchone()["total"]

        # ----------------------------------------------------
        # 3️⃣ KPI : Total encaissé (global)
        # ----------------------------------------------------
        cur.execute("SELECT COALESCE(SUM(fip), 0) AS total FROM paiements;")
        total_encaisse = float(cur.fetchone()["total"])

        # ----------------------------------------------------
        # 4️⃣ KPI : Total encaissé pour le mois courant
        # ----------------------------------------------------
        # On calcule dynamiquement le début et la fin du mois
        cur.execute("""
            SELECT COALESCE(SUM(fip), 0) AS total
            FROM paiements
            WHERE datepaiement >= date_trunc('month', CURRENT_DATE)
              AND datepaiement <  date_trunc('month', CURRENT_DATE) + interval '1 month';
        """)
        total_mois = float(cur.fetchone()["total"])

        # ----------------------------------------------------
        # 5️⃣ KPI : Nombre de classes actives
        # ----------------------------------------------------
        cur.execute("""
            SELECT COUNT(DISTINCT classe) AS total
            FROM eleves
            WHERE classe IS NOT NULL;
        """)
        nb_classes = cur.fetchone()["total"]

        # ----------------------------------------------------
        # 6️⃣ KPI : Calcul du montant attendu (logique métier)
        # ----------------------------------------------------
        # On récupère toutes les classes des élèves
        cur.execute("SELECT classe FROM eleves;")
        classes = cur.fetchall()

        total_attendu = 0

        for row in classes:
            # Pour chaque élève, on applique la règle FIP
            fip_mensuel = get_fip_par_classe(row["classe"])
            total_attendu += fip_mensuel * len(MOIS_SCOLAIRE)

        # ----------------------------------------------------
        # 7️⃣ KPI : Impayé estimé
        # ----------------------------------------------------
        impaye_estime = max(total_attendu - total_encaisse, 0)

        # ----------------------------------------------------
        # 8️⃣ Fermeture connexion
        # ----------------------------------------------------
        conn.close()

        # ----------------------------------------------------
        # 9️⃣ Réponse JSON propre et claire
        # ----------------------------------------------------
        return jsonify({
            "nb_eleves": nb_eleves,
            "nb_classes": nb_classes,
            "total_encaisse": round(total_encaisse, 2),
            "total_mois_courant": round(total_mois, 2),
            "total_attendu": round(total_attendu, 2),
            "impaye_estime": round(impaye_estime, 2)
        })

    except Exception as e:
        print("❌ ERREUR KPI FINANCE :", e)
        return jsonify({"error": "Erreur serveur KPI"}), 500
        
  


#========================
#  décorateur API propre
#========================  
   

          
        

#=========================
# KPI HTML
#=========================


@app.route("/admin/dashboard/finance")
@require_role("admin", "compta")
def admin_dashboard_finance():
    """
    Page HTML du tableau de bord financier
    (les données viennent de l'API /api/dashboard/finance)
    """
    return render_template_string(DASHBOARD_FINANCE_HTML)

DASHBOARD_FINANCE_HTML = """
<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<!-- CSS MOBILE -->
<link rel="stylesheet" href="{{ url_for('static', filename='css/mobile.css') }}">
<!-- CSS MOBILE -->
    <link rel="stylesheet" href="{{ url_for('static', filename='css/mobile.css') }}">
<title>Dashboard Financier</title>

<style>
body {
    font-family: "Bookman Old Style", serif;
    background: linear-gradient(to right, #eef5ff, #ffffff);
    margin: 0;
}

/* Header */
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
    color: #0d47a1;
}

/* Grid KPI */
.kpi-container {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
    gap: 25px;
    padding: 40px;
}

.kpi-card {
    background: white;
    padding: 25px;
    border-radius: 16px;
    box-shadow: 0 10px 25px rgba(0,0,0,0.15);
    text-align: center;
}

.kpi-title {
    font-size: 18px;
    color: #555;
    margin-bottom: 10px;
}

.kpi-value {
    font-size: 26px;
    font-weight: bold;
    color: #0d47a1;
}

/* Couleurs spécifiques */
.green { color: #1b5e20; }
.red   { color: #c62828; }
.blue  { color: #0d47a1; }

.footer {
    text-align: center;
    margin: 30px;
}
</style>
</head>

<body>

<div class="header">
    <img src="/static/images/logo_csnst.png">
    <h1>📊 Tableau de Bord Financier</h1>
</div>

<div class="kpi-container">

    <div class="kpi-card">
        <div class="kpi-title">Nombre d'élèves</div>
        <div class="kpi-value blue" id="nb_eleves">--</div>
    </div>

    <div class="kpi-card">
        <div class="kpi-title">Classes actives</div>
        <div class="kpi-value blue" id="nb_classes">--</div>
    </div>

    <div class="kpi-card">
        <div class="kpi-title">Total attendu</div>
        <div class="kpi-value blue" id="total_attendu">--</div>
    </div>

    <div class="kpi-card">
        <div class="kpi-title">Total encaissé</div>
        <div class="kpi-value green" id="total_encaisse">--</div>
    </div>

    <div class="kpi-card">
        <div class="kpi-title">Encaissement du mois</div>
        <div class="kpi-value green" id="total_mois">--</div>
    </div>

    <div class="kpi-card">
        <div class="kpi-title">Impayés estimés</div>
        <div class="kpi-value red" id="impaye">--</div>
    </div>

</div>

<div class="footer">
    <a href="/admin/dashboard">← Retour menu admin</a>
</div>

<script>
fetch("/api/dashboard/finance")
.then(r => r.json())
.then(data => {
    document.getElementById("nb_eleves").textContent = data.nb_eleves;
    document.getElementById("nb_classes").textContent = data.nb_classes;
    document.getElementById("total_attendu").textContent = data.total_attendu + " $";
    document.getElementById("total_encaisse").textContent = data.total_encaisse + " $";
    document.getElementById("total_mois").textContent = data.total_mois_courant + " $";
    document.getElementById("impaye").textContent = data.impaye_estime + " $";
});
</script>


<!-- module pour les graphiques3 -->

<!-- GRAPHIQUE ENCAISSEMENT MENSUEL -->
<div style="
    width:85%;
    max-width:900px;
    margin:40px auto;
    background:white;
    padding:25px;
    border-radius:14px;
    box-shadow:0 6px 20px rgba(0,0,0,0.15);
">


    <h2 style="
        text-align:center;
        font-family:'Bookman Old Style', serif;
        color:#0d47a1;
        margin-bottom:30px;
    ">
        📈 Évolution des encaissements mensuels
    </h2>

    <canvas id="monthlyChart" height="100"></canvas>

</div>


<!-- GRAPHIQUE COMPARATIF -->

<div style="
    width:85%;
    max-width:900px;
    margin:40px auto;
    background:white;
    padding:25px;
    border-radius:14px;
    box-shadow:0 6px 20px rgba(0,0,0,0.15);
">


    <h2 style="
        text-align:center;
        font-family:'Bookman Old Style', serif;
        color:#0d47a1;
        margin-bottom:30px;
    ">
        📊 Comparaison financière globale
    </h2>

    <canvas id="compareChart" height="80"></canvas>

</div>

<!-- GRAPHIQUE RÉPARTITION PAR SECTION -->


<div style="
    width:85%;
    max-width:850px;
    height:360px;               /* 🔒 HAUTEUR FIXE */
    margin:40px auto;
    background:white;
    padding:25px;
    border-radius:14px;
    box-shadow:0 6px 20px rgba(0,0,0,0.15);
">

    <h2 style="
        text-align:center;
        font-family:'Bookman Old Style', serif;
        color:#0d47a1;
        margin-bottom:20px;
    ">
        🍩 Répartition des encaissements par section
    </h2>

    <canvas id="sectionChart"></canvas>
</div>


<!-- SECTION EXPLICATIVE (BANDE BLUE) -->

<div style="
    background:#0d47a1;
    color:white;
    padding:50px 60px;
    margin-top:40px;
    font-family:'Bookman Old Style', serif;
    font-size:24px;
">

    <h2 style="
        text-align:center;
        margin-bottom:30px;
        font-size:28px;
    ">
        📘 Comprendre le tableau de bord financier
    </h2>

    <p style="line-height:1.8;">
        Ce tableau de bord financier offre une vue synthétique et stratégique
        de la situation financière de l’établissement scolaire. Il permet à
        l’administration et à la comptabilité de suivre les encaissements,
        d’anticiper les manques à gagner et de prendre des décisions éclairées.
    </p>

    <ul style="line-height:1.9;margin-top:25px;">
        <li><strong>Nombre d’élèves :</strong> total des élèves inscrits et actifs dans le système.</li>

        <li><strong>Classes actives :</strong> nombre de classes réellement opérationnelles
        pour l’année scolaire en cours.</li>

        <li><strong>Total attendu :</strong> montant théorique que l’école devrait percevoir
        si tous les élèves s’acquittaient intégralement de leurs frais scolaires.</li>

        <li><strong>Total encaissé :</strong> somme effectivement perçue par l’établissement
        depuis le début de l’année scolaire.</li>

        <li><strong>Encaissement du mois :</strong> montant collecté uniquement pour le mois
        en cours, utile pour le suivi mensuel.</li>

        <li><strong>Impayé estimé :</strong> différence entre le total attendu et le total encaissé,
        représentant les montants restant à recouvrer.</li>
    </ul>

    <p style="line-height:1.8;margin-top:25px;">
        Une bonne lecture de ces indicateurs permet d’assurer une gestion saine,
        transparente et durable des finances scolaires, garantissant ainsi la
        continuité des activités pédagogiques et administratives.
    </p>
</div>


<!-- BANDE INSTITUTIONNELLE (bande Rouge) -->
<div style="
    background:#c62828;
    color:white;
    padding:20px;
    text-align:center;
    font-family:'Bookman Old Style', serif;
    font-size:18px;
">
    Comptabilité CS Nsanga le Thanzie —  
    165 Av Kasangulu, croisement de l’Église |
    Email : notificationnsangalethanzie@gmail.com |
    Tél : +243 974 773 760 / +243 995 682 745
</div>

<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>

<!-- Scripts module pour les graphiques par mois -->



<!-- 📊 Graphique comparatif Total attendu vs Total encaissé-->

<script>
(async function () {

    try {
        const response = await fetch("/api/dashboard/finance", {
            credentials: "same-origin" // 🔐 important pour session Render
        });

        // ❌ Si l'API renvoie une redirection ou du HTML (login)
        if (!response.ok) {
            throw new Error("Réponse API invalide (HTTP " + response.status + ")");
        }

        const contentType = response.headers.get("content-type") || "";
        if (!contentType.includes("application/json")) {
            throw new Error("API non JSON (probable redirection login)");
        }

        const data = await response.json();

        // 🛑 Vérification minimale des données attendues
        if (
            typeof data.total_attendu === "undefined" ||
            typeof data.total_encaisse === "undefined" ||
            typeof data.impaye_estime === "undefined"
        ) {
            throw new Error("Structure JSON invalide");
        }

        const canvas = document.getElementById("compareChart");
        if (!canvas) {
            console.warn("Canvas compareChart introuvable");
            return;
        }

        const ctx = canvas.getContext("2d");

        // 🔁 Détruire un graphique existant (mobile / re-render)
        if (canvas._chartInstance) {
            canvas._chartInstance.destroy();
        }

        const chart = new Chart(ctx, {
            type: "bar",
            data: {
                labels: ["Attendu", "Encaissé", "Impayé"],
                datasets: [{
                    label: "Montants (FIP)",
                    data: [
                        Number(data.total_attendu),
                        Number(data.total_encaisse),
                        Number(data.impaye_estime)
                    ],
                    backgroundColor: [
                        "#1976d2",
                        "#2e7d32",
                        "#c62828"
                    ],
                    borderRadius: 6
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: true, // ✅ STABLE mobile
                plugins: {
                    legend: {
                        display: false
                    },
                    tooltip: {
                        callbacks: {
                            label: function (ctx) {
                                return ctx.raw.toLocaleString() + " FIP";
                            }
                        }
                    }
                },
                scales: {
                    x: {
                        ticks: {
                            font: {
                                family: "Bookman Old Style",
                                size: 14
                            }
                        }
                    },
                    y: {
                        beginAtZero: true,
                        ticks: {
                            font: {
                                family: "Bookman Old Style",
                                size: 14,
                                callback: value => value.toLocaleString()
                            }
                        }
                    }
                }
            }
        });

        // 🔒 Sauvegarde instance (évite doublons)
        canvas._chartInstance = chart;

    } catch (err) {
        console.error("❌ ERREUR GRAPHIQUE COMPARATIF :", err);

        // Message visuel simple (optionnel)
        const canvas = document.getElementById("compareChart");
        if (canvas) {
            const parent = canvas.parentElement;
            parent.innerHTML = `
                <p style="
                    text-align:center;
                    color:#c62828;
                    font-family:'Bookman Old Style', serif;
                    font-size:16px;
                ">
                    ⚠️ Impossible de charger les données financières.<br>
                    Vérifiez la connexion ou la session.
                </p>
            `;
        }
    }

})();
</script>

<script>fetch("/api/dashboard/finance/monthly")

.then(res => res.json())
.then(data => {

    const ctx = document.getElementById("monthlyChart").getContext("2d");

    new Chart(ctx, {
        type: "line",
        data: {
            labels: data.labels,
            datasets: [{
                label: "Montant encaissé (FIP)",
                data: data.values,
                borderColor: "#1976d2",
                backgroundColor: "rgba(25,118,210,0.15)",
                fill: true,
                tension: 0.3,
                pointRadius: 5,
                pointBackgroundColor: "#0d47a1"
            }]
        },
        options: {
            responsive: true,
            plugins: {
                legend: {
                    labels: {
                        font: {
                            family: "Bookman Old Style",
                            size: 14
                        }
                    }
                }
            },
            scales: {
                x: {
                    ticks: {
                        font: {
                            family: "Bookman Old Style",
                            size: 14
                        }
                    }
                },
                y: {
                    ticks: {
                        font: {
                            family: "Bookman Old Style",
                            size: 14
                        }
                    }
                }
            }
        }
    });
});
</script>

<script>
(async function () {

    try {
        const response = await fetch("/api/dashboard/finance/by_section", {
            credentials: "same-origin" // 🔐 indispensable Render
        });

        // ❌ Réponse invalide (401, 302, 500…)
        if (!response.ok) {
            throw new Error("Réponse API invalide (HTTP " + response.status + ")");
        }

        // ❌ Render peut renvoyer HTML (login)
        const contentType = response.headers.get("content-type") || "";
        if (!contentType.includes("application/json")) {
            throw new Error("API non JSON (probable redirection login)");
        }

        const data = await response.json();

        // 🛑 Validation minimale
        if (
            !Array.isArray(data.labels) ||
            !Array.isArray(data.values) ||
            data.labels.length === 0
        ) {
            throw new Error("Données section invalides ou vides");
        }

        const canvas = document.getElementById("sectionChart");
        if (!canvas) {
            console.warn("Canvas sectionChart introuvable");
            return;
        }

        const ctx = canvas.getContext("2d");

        // 🔁 Évite double rendu (mobile / rechargement)
        if (canvas._chartInstance) {
            canvas._chartInstance.destroy();
        }

        const chart = new Chart(ctx, {
            type: "doughnut",
            data: {
                labels: data.labels,
                datasets: [{
                    data: data.values.map(v => Number(v)),
                    backgroundColor: [
                        "#1976d2",
                        "#2e7d32",
                        "#fb8c00",
                        "#6a1b9a",
                        "#c62828",
                        "#00838f",
                        "#558b2f",
                        "#455a64"
                    ]
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: true, // ✅ OBLIGATOIRE doughnut mobile
                plugins: {
                    legend: {
                        position: "bottom",
                        labels: {
                            font: {
                                family: "Bookman Old Style",
                                size: 13
                            },
                            padding: 12
                        }
                    },
                    tooltip: {
                        callbacks: {
                            label: function (context) {
                                return (
                                    context.label +
                                    " : " +
                                    context.raw.toLocaleString() +
                                    " FIP"
                                );
                            }
                        }
                    }
                }
            }
        });

        // 🔒 Sauvegarde instance
        canvas._chartInstance = chart;

    } catch (err) {
        console.error("❌ ERREUR GRAPHIQUE SECTION :", err);

        const canvas = document.getElementById("sectionChart");
        if (canvas) {
            const parent = canvas.parentElement;
            parent.innerHTML = `
                <p style="
                    text-align:center;
                    color:#c62828;
                    font-family:'Bookman Old Style', serif;
                    font-size:16px;
                ">
                    ⚠️ Impossible de charger la répartition par section.<br>
                    Vérifiez la connexion ou la session.
                </p>
            `;
        }
    }

})();
</script>



</body>
</html>
"""
#==============================
# module pour les graphiques 1
#=============================

@app.route("/api/dashboard/finance/monthly")
@require_api_role("admin", "compta")
def api_dashboard_finance_monthly():
    """
    Retourne les montants encaissés par mois scolaire
    pour affichage graphique (Chart.js)
    """

    try:
        conn = get_db_connection()
        cur = conn.cursor(row_factory=dict_row)

        # Mois scolaires officiels (ordre fixe)
        mois_ordre = MOIS_SCOLAIRE

        # Initialisation à 0
        data = {m: 0 for m in mois_ordre}

        # Requête PostgreSQL
        cur.execute("""
            SELECT mois, COALESCE(SUM(fip),0) AS total
            FROM paiements
            GROUP BY mois;
        """)

        rows = cur.fetchall()

        for r in rows:
            mois_norm = canonical_month(r["mois"])
            if mois_norm in data:
                data[mois_norm] += float(r["total"])

        conn.close()

        return jsonify({
            "labels": mois_ordre,
            "values": [round(data[m], 2) for m in mois_ordre]
        })

    except Exception as e:
        print("❌ ERREUR KPI MENSUEL :", e)
        return jsonify({"error": "Erreur graphique mensuel"}), 500
        
        
      

      
#===================================================
# Graphique de répartition des paiements par section
#==============================  =================     
        
        
@app.route("/api/dashboard/finance/by_section")
@require_api_role("admin", "compta")
def api_dashboard_finance_by_section():
    """
    Répartition financière par section
    Version stable et optimisée pour graphique doughnut
    """

    try:
        conn = get_db_connection()
        cur = conn.cursor(row_factory=dict_row)

        cur.execute("""
            SELECT
                COALESCE(e.section, 'Non définie') AS section,
                SUM(p.fip) AS total
            FROM paiements p
            JOIN eleves e ON p.eleve_id = e.id
            GROUP BY e.section
            HAVING SUM(p.fip) > 0
            ORDER BY total DESC;
        """)

        rows = cur.fetchall()
        conn.close()

        return jsonify({
            "labels": [r["section"] for r in rows],
            "values": [float(r["total"]) for r in rows]
        })

    except Exception as e:
        print("❌ ERREUR API SECTION :", e)
        return jsonify({"error": "Erreur répartition section"}), 500


@app.route("/api/depenses-par-date")
@require_role("admin", "compta")
def api_depenses_par_date():

    date_jour = request.args.get("date")

    if not date_jour:
        return jsonify({"error": "date manquante"}), 400

    query = """
        SELECT
            d.id,
            d.ref_dp,
            d.libelle,
            d.montant,
            d.annee_scolaire
        FROM depense d
        WHERE d.date_depense = %s
        ORDER BY d.id
    """

    rows = fetch_all(query, (date_jour,))

    return jsonify({
        "date": date_jour,
        "nb": len(rows),
        "depenses": rows
    })

    
    
#===============HOME=========   

HOME_HTML = """
<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<!--<meta name="viewport" content="width=device-width, initial-scale=1.0"> -->

<!-- CSS MOBILE -->
<!--<link rel="stylesheet" href="{{ url_for('static', filename='css/mobile.css') }}"> -->
<title>Accueil - CS Nsanga le Thanzie</title>

<style>
body {
    margin: 0;
    font-family: "Bookman Old Style", serif;
    background: #f4f6fb;
}

/* ================= HEADER ================= */

.header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 15px 30px;
}

.header-left {
    display: flex;
    align-items: center;
    gap: 15px;
}

.header-left img {
    height: 95px; /* avant : 70*/
}

.bands {
    width: 220px;
}

.band-blue { height: 6px; background:#0d47a1; }
.band-red  { height: 6px; background:#c62828; }

.marquee {
    overflow: hidden;
    height: 24px;
    background: #fff;
}

.marquee span {
    display: inline-block;
    white-space: nowrap;
    animation: scroll 14s linear infinite;
    font-weight: bold;
    color:#0d47a1;
}

@keyframes scroll {
    from { transform: translateX(100%); }
    to   { transform: translateX(-100%); }
}


.header-center {
    font-size: 15px;
    font-weight: bold;
    color: #0d47a1;
    background: linear-gradient(to right, #ffffff, #e3f2fd);
    padding: 10px 18px;
    border-radius: 10px;
    box-shadow: 0 4px 10px rgba(0,0,0,0.15);
    letter-spacing: 0.5px;
    
     /* 🎯 AJUSTEMENT PRO : vers la gauche */
    transform: translateX(-30px); /* décale légèrement vers la droite */
}


.header-right {
    text-align: right;
    font-size: 16px;
    color:#0d47a1;
    font-weight: bold;
}

.school-black {
    color: #000000;
    font-size: 20px;
    font-weight: bold;
}

.school-red {
    color: #c62828;
    font-size: 17px;
    font-weight: bold;
    letter-spacing: 1px;
}



/* ================= SEPARATEUR ================= */


.thz-separator {
    display: grid;
    grid-template-columns: 1fr auto 1fr;
    align-items: center;
    width: 100%;
    padding: 15px 0;
    background: #f4f6f8;
    position: relative;
    z-index: 5;
}

/* BLOCS DE LIGNES */
.thz-lines {
    position: relative;
    width: 100%;
}

.thz-lines.left,
.thz-lines.right {
    display: flex;
    flex-direction: column;
    gap: 6px;
}

/* LIGNES */
.line {
    height: 4px;
    width: 100%;
    border-radius: 2px;
}

.line.blue  { background-color: #1e40af; }
.line.green { background-color: #16a34a; }
.line.red   { background-color: #dc2626; }

/* CENTRE */
.thz-center {
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 0 20px;
}


/* Cercle THZ */

.thz-circle {
    width: 72px;              /* 🔼 agrandi */
    height: 72px;

    border-radius: 50%;
    background: #3f6fb6;

    /* 🎯 DOUBLE CONTOUR */
    border: 3px solid white;                /* contour intérieur */
    outline: 3px solid #facc15;             /* contour extérieur jaune */
    outline-offset: 3px;

    color: white;
    font-family: "Bookman Old Style", serif;
    font-size: 20px;         /* 🔼 texte un peu plus grand */
    font-weight: bold;

    display: flex;
    align-items: center;
    justify-content: center;

    box-shadow: 0 6px 18px rgba(0,0,0,0.28);

    animation: pulseTHZ 2.5s ease-in-out infinite;
}


/* BOUTON DÉCONNEXION DANS LES LIGNES */

.btn-logout-inline {
    position: absolute;
    right: 20px;
    top: 50%;
    transform: translateY(-50%);

    background: #dc2626;
    color: white;

    padding: 9px 20px;       /* 🔼 agrandi */
    border-radius: 8px;      /* 🔼 plus doux */

    font-size: 14px;         /* 🔼 lisibilité */
    font-weight: bold;

    text-decoration: none;

    box-shadow: 0 4px 10px rgba(0,0,0,0.3);
    z-index: 10;

    transition: transform 0.2s ease, box-shadow 0.2s ease;
}

.btn-logout-inline:hover {
    background: #b91c1c;
    transform: translateY(-50%) scale(1.05);
    box-shadow: 0 6px 14px rgba(0,0,0,0.35);
}


/* ===== DECONNEXION ====== */

.logout {
    position:absolute;
    right:30px;
    top:110px;
}

.logout a {
    background:#c62828;
    color:white;
    padding:8px 16px;
    text-decoration:none;
    border-radius:6px;
}

/* ===== ZONE VERTE ======== */

.zone-green {
    background: #7cb342;
    margin: 30px;
    padding: 40px 30px;   /* 🔼 plus d’espace haut/bas */
    display: flex;
    gap: 30px;
    border-radius: 12px;
}

/* == TITRE PRO (DESIGN INSTITUTIONNEL)=== */

.buttons-title {
    text-align: center;
    font-size: 18px;
    font-weight: bold;
    color: #0d47a1;
    background: linear-gradient(to right, #ffffff, #e3f2fd);
    padding: 12px 20px;
    border-radius: 8px;
    margin-bottom: 18px;
    letter-spacing: 1px;
    box-shadow: 0 4px 10px rgba(0,0,0,0.15);
}

/* +++ CADRE PRO AUTOUR DES BOUTONS +++ */

.buttons-frame {
    background: #558b2f;
    padding: 20px;
    border-radius: 14px;
    border: 2px solid #ffffff;
    box-shadow: inset 0 0 0 2px rgba(255,255,255,0.4);
}


/*++++ HTN : HOVER INTELLIGENT + TOOLTIP +++*/

.nav-btn {
    background: #3f6fb6;
    color: white;
    border: 2px solid white;
    padding: 10px;
    cursor: pointer;
    font-weight: bold;
    text-align: center;
    transition: all 0.25s ease;
    position: relative;
}

.nav-btn:hover {
    background: #0d47a1;
    transform: translateY(-3px);
    box-shadow: 0 6px 14px rgba(0,0,0,0.25);
}

/* TOOLTIP */
.nav-btn::after {
    content: attr(data-label);
    position: absolute;
    bottom: 115%;
    left: 50%;
    transform: translateX(-50%);
    background: #0d47a1;
    color: white;
    font-size: 12px;
    padding: 5px 10px;
    border-radius: 6px;
    white-space: nowrap;
    opacity: 0;
    pointer-events: none;
    transition: opacity 0.2s ease;
}

.nav-btn:hover::after {
    opacity: 1;
}


.buttons {
    display:grid;
    grid-template-columns: repeat(4, 80px);
    gap:12px;
}

.buttons button {
    background:#3f6fb6;
    color:white;
    border:2px solid white;
    padding:10px;
    cursor:pointer;
}

.buttons button:hover {
    background:#0d47a1;
}

/* STRUCTURE DES 3 ZONES A DROIT ( POR ET EVOLUTIVE ) */

.right-zones {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 20px;
    flex: 1;
}

.right-box {
    border-radius: 14px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-weight: bold;
    color: white;
    font-size: 16px;
}

/* Couleurs harmonisées */
.box-a { background: #ffffff; color:#0d47a1; }
.box-b { background: #e3f2fd; color:#0d47a1; }
.box-c { background: #c5e1a5; color:#1b5e20; }

/* ===== ZONE A INTELLIGENTE ===== */

.box-a {
    display: flex;
    flex-direction: column;
    padding: 18px;
    background: #ffffff;
    border-radius: 14px;
    border: 2px solid #0d47a1;
}

/* TITRE FIGÉ */
.zoneA-title {
    font-size: 15px;
    font-weight: bold;
    color: #0d47a1;
    text-align: center;
    padding: 10px;
    border-bottom: 2px solid #e3f2fd;
    background: linear-gradient(to right, #e3f2fd, #ffffff);
}

/* CONTENEUR TEXTE */

.zoneA-content {
    height: 220px;
    overflow: hidden;
    position: relative;
    border-top: 1px solid #ddd;
    margin-top: 10px;
}

.zoneA-scroll {
    display: block;
    font-size: 14px;
    line-height: 1.7;
    color: #333;
    padding: 10px;
    transform: translateY(0);
}

.zoneA-scroll.scrolling {
    animation: simpleScroll 12s linear infinite;
}

@keyframes simpleScroll {
    from {
        transform: translateY(100%);
    }
    to {
        transform: translateY(-100%);
    }
}



/* CLIGNOTEMENT BOUTON (BTN non actif) */
@keyframes blinkBtn {
    0% { background: #3f6fb6; }
    50% { background: #facc15; color:#0d47a1; }
    100% { background: #3f6fb6; }
}

.blink {
    animation: blinkBtn 1s infinite;
}


/* ================= MULTIMEDIA ================= */
.media {
    display:grid;
    grid-template-columns: repeat(3, 1fr);
    gap:20px;
    padding:30px;
}

.media div {
    background:#4472c4;
    height:200px;
    display:flex;
    align-items:center;
    justify-content:center;
    color:white;
}

/* ================= PANNEAU ================= */
.panel {
    background:black;
    color:white;
    padding:40px;
    text-align:center;
}

/* ================= FOOTER ================= */
.footer {
    background:#c62828;
    color:white;
    text-align:center;
    padding:15px;
}
</style>
</head>

<body>

<!-- HEADER -->
<div class="header">
    <div class="header-left">
        <img src="/static/images/logo_csnst.png">
        <div class="bands">
            <div class="band-blue"></div>
            <div class="band-red"></div>
            <div class="marquee">
                <span>Gestion scolaire — Suivi de la caisse — Transparence administrative</span>
            </div>
        </div>
    </div>
       
       <div class="header-center" id="datetime">
       <!-- Date & heure injectées par JS -->
       </div>
       
     <div class="header-right">
        <span class="school-black">COMPLEXE SCOLAIRE</span><br>
        <span class="school-red">NSANGA LE THANZIE</span>
     </div>

</div>



<!-- =======================
     SÉPARATEUR THZ CENTRAL
     ======================= -->
<div class="thz-separator">

    <!-- LIGNES GAUCHE -->
    <div class="thz-lines left">
        <span class="line blue"></span>
        <span class="line green"></span>
        <span class="line red"></span>
    </div>

    <!-- CENTRE -->
    <div class="thz-center">
        <div class="thz-circle">THZ</div>
    </div>

    <!-- LIGNES DROITE + DÉCONNEXION -->
    <div class="thz-lines right">
        <span class="line blue"></span>
        <span class="line green"></span>
        <span class="line red"></span>

        <a href="/thz" class="btn-logout-inline">
            Déconnexion
        </a>
    </div>

</div>



<!-- ZONE VERTE -->

<div class="zone-green">

    <!-- ====== BLOC BOUTONS ====== -->
    
    <div class="buttons-wrapper">

        <div class="buttons-title">
            🧭 PANNEAU DE NAVIGATION PRINCIPALE
        </div>

        <div class="buttons-frame">
            <div class="buttons">
                {% for i in range(1,17) %}
                    {% if i == 1 %}
                        <a href="/admin1/panel"
                           class="nav-btn"
                           data-label="Panneau Admin">
                           {{ i }}
                        </a>
                    {% else %}
                        <button class="nav-btn"
                                data-label="Btn {{ i }}">
                            {{ i }}
                        </button>
                    {% endif %}
                {% endfor %}
            </div>
        </div>

    </div>

    <!-- ====== 3 ZONES À DROITE ====== -->
    
    <div class="right-zones">
    
    
        <!---==== BOUTON A ===== --->
        
        <div class="right-box box-a" id="zoneA">

                    <div class="zoneA-title" id="zoneA-title">
                        Survolez un bouton
                    </div>

                    <div class="zoneA-content">
                        <div class="zoneA-scroll" id="zoneA-scroll">
                            <p>
                Placez le curseur de la souris sur un bouton pour découvrir
                son rôle et les fonctionnalités associées.
            </p>
        </div>
    </div>

</div>

        
        
        
        <div class="right-box box-b">ZONE B</div>
        <div class="right-box box-c">ZONE C</div>
    </div>

</div>




<!-- MULTIMEDIA -->
<div class="media">
    <div>VIDÉO INSTITUTIONNELLE</div>
    <div>ANNONCES & PUBLICITÉS</div>
    <div>IMAGES DÉFILANTES</div>
</div>

<!-- PANNEAU -->
<div class="panel">
    On parle du complexe Nsanga le Thanzie
</div>

<!-- FOOTER -->
<div class="footer">
    165 Av Kasangula, Q/Gambela 2, Lubumbashi — Tél : +243 974 773 760
</div>

<!-- Script pour la ZONA A -->

<script>
const zoneATitle  = document.getElementById("zoneA-title");
const zoneAScroll = document.getElementById("zoneA-scroll");

const texteBouton1 = `
<p>
<b>PANNEAU ADMINISTRATEUR</b><br><br>
Ce panneau constitue le centre de pilotage du système Nsanga le Thanzie.<br><br>
• Gestion des élèves<br>
• Suivi des paiements<br>
• Journaux comptables<br>
• Rapports officiels<br>
• Contrôle administratif et financier<br><br>
Une gestion centralisée, sécurisée et professionnelle.
</p>
`;

const texteParDefaut = `
<p>
<b>Bienvenue sur la plateforme Nsanga le Thanzie.</b><br><br>
Ce bouton n’est pas encore opérationnel.<br>
Les fonctionnalités associées seront mises à jour prochainement.<br><br>
Merci pour votre confiance.
</p>
`;

document.querySelectorAll(".nav-btn").forEach(btn => {

    btn.addEventListener("mouseenter", () => {

        const num = btn.textContent.trim();

        // reset
        zoneAScroll.classList.remove("scrolling");
        zoneAScroll.innerHTML = "";

        // forcer repaint
        void zoneAScroll.offsetHeight;

        if (num === "1") {
            zoneATitle.textContent = "Panneau Administrateur";
            zoneAScroll.innerHTML = texteBouton1;
            zoneAScroll.classList.add("scrolling");
        } else {
            zoneATitle.textContent = "BTN " + num;
            zoneAScroll.innerHTML = texteParDefaut;
            btn.classList.add("blink");
        }
    });

    btn.addEventListener("mouseleave", () => {
        btn.classList.remove("blink");
        zoneAScroll.classList.remove("scrolling");
    });

});
</script>



<!-- Script pour LA DATE ET HEURE -->


<script>
function updateDateTime() {
    const now = new Date();
    const optionsDate = {
        weekday: 'long',
        year: 'numeric',
        month: 'long',
        day: 'numeric'
    };

    const date = now.toLocaleDateString('fr-FR', optionsDate);
    const time = now.toLocaleTimeString('fr-FR');

    document.getElementById("datetime").innerHTML =
        `${date} — <span style="color:#c62828">${time}</span>`;
}

updateDateTime();
setInterval(updateDateTime, 1000);
</script>

</body>
</html>
"""







# ===============================================================
# 🔵 11. Lancement local
# ===============================================================
if __name__ == "__main__":
    print("🚀 API en mode LOCAL : http://127.0.0.1:5000")
    debug = not DATABASE_URL
    app.run(host="0.0.0.0", port=5000, debug=debug)




