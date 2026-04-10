fetch("/api/dashboard-inscription")
.then(res => {
    if (!res.ok) {
        throw new Error("Erreur API");
    }
    return res.json();
})
.then(data => {

    console.log("DATA :", data);

    // ===== KPI =====
    document.getElementById("total").innerText = data.kpi.total || 0;
    document.getElementById("py").innerText = data.kpi.py || 0;
    document.getElementById("abd").innerText = data.kpi.abd || 0;
    document.getElementById("npy").innerText = data.kpi.npy || 0;
    document.getElementById("montant").innerText = (data.kpi.montant || 0) + " FC";

    // ===== TAUX =====
    let taux = 0;

    if (data.kpi.total > 0) {
        taux = ((data.kpi.py / data.kpi.total) * 100).toFixed(1);
    }

    document.getElementById("taux_py").innerText = taux + " %";

    // ===== SECTION =====
    const sectionMap = {
        "PRM": "Primaire",
        "SEC": "Secondaire",
        "MAT": "Maternelle"
    };

    const secLabels = data.sections.map(x => sectionMap[x[0]] || x[0]);
    const secData = data.sections.map(x => x[1]);

    new Chart(document.getElementById("chartSection"), {
        type: "bar",
        data: {
            labels: secLabels,
            datasets: [{
                label: "Effectif par section",
                data: secData,
                backgroundColor: ["#3498db","#2ecc71","#f39c12"]
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false
        }
    });

    // ===== CATEGORIE =====
    const catLabels = data.categories.map(x => x[0]);
    const catData = data.categories.map(x => x[1]);

    new Chart(document.getElementById("chartCategorie"), {
        type: "doughnut",
        data: {
            labels: catLabels,
            datasets: [{
                data: catData,
                backgroundColor: ["#2ecc71","#e74c3c","#95a5a6"]
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false
        }
    });

})
.catch(err => {
    console.error("Erreur dashboard :", err);
});


function chargerFiltre() {

    let section = document.getElementById("filtreSection").value;
    let categorie = document.getElementById("filtreCategorie").value;

    let url = `/api/dashboard-filtre?section=${section}&categorie=${categorie}`;

    fetch(url)
    .then(res => res.json())
    .then(data => {

        // KPI
        document.getElementById("total").innerText = data.total;
        document.getElementById("montant").innerText = data.montant + " FC";

        console.log("Filtre appliqué :", data);
    });
}