# server_flask.py
"""
API Flask — Version PRO (compatible Render et local)
Projet : Solde Élève Nsanga Le Thanzie

✔ Compatible Render (gunicorn server_flask:app)
✔ Compatible lancement local (python server_flask.py)
✔ API déjà prête pour extensions (élève / comptable / admin)
"""

from flask import Flask, jsonify, request
import sqlite3
import pandas as pd
import re

# ======================================================
# 🔵 Configuration
# ======================================================

app = Flask(__name__)
DB_PATH = "thz.db"

# Liste des mois scolaires utilisés dans le système
MOIS_SCOLAIRE = ["Sept", "Oct", "Nov", "Dec", "Janv", "Fevr",
                 "Mars", "Avr", "Mai", "Juin", "Juil"]


# ======================================================
# 1️⃣ Détermination automatique du FIP mensuel
# ======================================================

def get_fip_par_classe(classe):
    """Retourne le FIP mensuel selon la classe de l'élève."""
    if not classe:
        return 0

    c = str(classe).strip().replace("°", "").upper()

    groupe_40 = ["1M", "2M", "3M", "1P", "2P", "3P", "4P", "5P", "6P"]
    groupe_45 = ["7EB", "8EB", "1HP", "1LIT", "1SC",
                 "2HP", "2LIT", "2SC",
                 "3HP", "3LIT", "3SC"]
    groupe_55 = ["1CG", "1MC", "1TCC", "1EL", "1ELECTRO", "1CONST",
                 "2CG", "2MC", "2TCC", "2EL",
                 "3CG", "3MC", "3TCC", "3EL"]
    groupe_80 = ["4CG", "4MC", "4TCC", "4EL"]

    if c in groupe_40:
        return 40
    elif c in groupe_45:
        return 45
    elif c in groupe_55:
        return 55
    elif c in groupe_80:
        return 80
    else:
        return 0  # FIP inconnu → 0


# ======================================================
# 2️⃣ Fonctions utilitaires
# ======================================================

def get_connection():
    """Connexion simple à SQLite."""
    return sqlite3.connect(DB_PATH)


def canonical_month(m_raw):
    """Normalise les libellés de mois en format officiel."""
    if pd.isna(m_raw):
        return None

    s = str(m_raw).strip().lower()

    # Nettoyage AC., SLD., etc
    s = re.sub(r'^(ac|sld)[\.\-\s]*', '', s)

    # Dictionnaire de correspondance
    mapping = {
        "sept": "Sept",
        "oct": "Oct",
        "nov": "Nov",
        "dec": "Dec",
        "janv": "Janv",
        "fev": "Fevr",
        "févr": "Fevr",
        "mars": "Mars",
        "avr": "Avr",
        "mai": "Mai",
        "juin": "Juin",
        "juil": "Juil",
    }

    for k, v in mapping.items():
        if k in s:
            return v

    return None


# ======================================================
# 3️⃣ Routes API
# ======================================================

@app.route("/")
def home():
    return jsonify({
        "status": "ok",
        "message": "API Solde Élève (version Render) opérationnelle."
    })


@app.route("/api/ping")
def ping():
    return jsonify({"message": "API en ligne"})


# -------------------------------
# 🔵 Consultation d'un élève par matricule
# -------------------------------
@app.route("/api/eleve/<matricule>")
def get_eleve(matricule):
    try:
        conn = get_connection()

        # 🔹 Lecture infos élève
        eleve_df = pd.read_sql_query(
            "SELECT * FROM eleves WHERE LOWER(matricule) = LOWER(?)",
            conn, params=(matricule,)
        )

        if eleve_df.empty:
            conn.close()
            return jsonify({"error": f"Aucun élève trouvé pour {matricule}"}), 404

        eleve = eleve_df.iloc[0].to_dict()
        nom = eleve.get("nom_postnom") or "Non renseigné"
        classe = eleve.get("classe", "")

        # 🔹 Détermination automatique du FIP mensuel
        fip_mensuel = get_fip_par_classe(classe)
        total_attendu = fip_mensuel * len(MOIS_SCOLAIRE)

        # 🔹 Lecture des paiements
        pay_df = pd.read_sql_query("""
            SELECT mois, fip, recu_num
            FROM paiements p
            JOIN eleves e ON e.id = p.eleve_id
            WHERE LOWER(e.matricule) = LOWER(?)
        """, conn, params=(matricule,))

        conn.close()

        if pay_df.empty:
            return jsonify({
                "nom": nom,
                "matricule": matricule,
                "classe": classe,
                "fip_mensuel": fip_mensuel,
                "message": "Aucun paiement trouvé."
            }), 200

        # 🔹 Normalisation et regroupement
        pay_df["mois_norm"] = pay_df["mois"].apply(canonical_month)
        pay_df["fip"] = pd.to_numeric(pay_df["fip"], errors="coerce").fillna(0)

        pay_group = pay_df.groupby("mois_norm")["fip"].sum().to_dict()

        # 🔹 Mois payés / non payés
        mois_payes = [m for m in MOIS_SCOLAIRE if m in pay_group and pay_group[m] > 0]
        mois_non_payes = [m for m in MOIS_SCOLAIRE if m not in mois_payes]

        total_paye = sum(min(pay_group[m], fip_mensuel) for m in mois_payes)
        solde_fip = total_attendu - total_paye

        # 🔹 Résultat JSON
        result = {
            "nom": nom,
            "matricule": matricule,
            "sexe": eleve.get("sexe", ""),
            "classe": classe,
            "section": eleve.get("section", ""),
            "categorie": eleve.get("categorie", ""),
            "telephone": eleve.get("telephone", ""),
            "fip_mensuel": fip_mensuel,
            "fip_total": total_paye,
            "total_attendu_fip": total_attendu,
            "solde_fip": round(solde_fip, 2),
            "mois_payes": mois_payes,
            "mois_non_payes": mois_non_payes
        }

        return jsonify(result)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ======================================================
# 4️⃣ Lancement du serveur (LOCAL uniquement)
# ======================================================
if __name__ == "__main__":
    print("🚀 API en mode LOCAL : http://127.0.0.1:5000")
    app.run(host="0.0.0.0", port=5000, debug=True)
