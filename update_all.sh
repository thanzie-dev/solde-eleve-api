
#!/bin/bash

echo "==============================================="
echo " 🔄  MISE À JOUR AUTOMATISÉE DU PROJET FLASK"
echo "==============================================="

PROJECT_DIR="/c/ProjetSoldeEleve"
ENV_DIR="$PROJECT_DIR/env/Scripts"

echo "➡ Passage au dossier du projet..."
cd "$PROJECT_DIR" || { echo "❌ Erreur : Impossible d'accéder au projet."; exit 1; }

echo "➡ Vérification du .gitignore..."
grep -qxF "thz.db" .gitignore || echo "thz.db" >> .gitignore
grep -qxF "rapport_import.pdf" .gitignore || echo "rapport_import.pdf" >> .gitignore

echo "➡ Activation de l’environnement virtuel..."
source "$ENV_DIR/activate" || { echo "❌ Erreur : impossible d'activer l'env."; exit 1; }

echo "➡ Exécution de import_excel.py pour mettre à jour thz.db..."
python import_excel.py

if [ $? -ne 0 ]; then
    echo "❌ Erreur dans import_excel.py — Mise à jour annulée."
    deactivate
    exit 1
fi

echo "✔ Base SQLite mise à jour avec succès."

echo "➡ Désactivation de l'environnement..."
deactivate

echo "➡ Vérification des fichiers modifiés avec Git..."
git status

echo "➡ Ajout des modifications..."
git add .

echo "➡ Commit des changements..."
git commit -m "Mise à jour automatique : import Excel + code backend" || echo "⚠ Aucun changement à committer."

echo "➡ Envoi vers GitHub..."
git push origin main || { echo "❌ Échec du push."; exit 1; }

echo "==============================================="
echo " ✔  DÉPLOIEMENT TERMINÉ — RENDER VA RECONSTRUIRE"
echo "==============================================="
