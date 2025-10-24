/* jshint esversion: 8 */ 
/* jshint browser: true */
/* global fetch, setInterval, clearInterval, console */

// ====================================================================
// SECTION 1 : FONCTIONS UTILITAIRES
// ====================================================================

/**
 * Met à jour la barre de progression.
 * @param {number} percent - Pourcentage de 0 à 100.
 */
function setProgress(percent) {
    // Récupération des éléments à chaque appel pour garantir la portée
    const progressBar = document.getElementById('progress-bar');
    const progressPercent = document.getElementById('progress-percent');
    
    if (!progressBar || !progressPercent) return; // Sécurité

    progressBar.style.width = `${percent}%`;
    progressPercent.textContent = `${percent}%`;

    // Logique CRUCIALE pour l'animation rayée (applique les fonds CSS)
    if (percent > 0) {
        // Le premier dégradé : les rayures animées
        // Le second dégradé (MODIFIÉ) : la couleur de remplissage uni (Orange)
        progressBar.style.backgroundImage = `repeating-linear-gradient(
            -45deg, 
            transparent, 
            transparent 10px, 
            rgba(255, 255, 255, 0.3) 10px, 
            rgba(255, 255, 255, 0.3) 20px
        ),
        linear-gradient(
            to right, 
            var(--color-primary), /* Simplifié pour n'utiliser que la couleur primaire */
            var(--color-primary)
        )`;
        progressBar.style.backgroundSize = '40px 40px, 100% 100%';
    } else {
        // Réinitialiser quand la progression est à 0
        progressBar.style.backgroundImage = 'none';
        progressBar.style.backgroundSize = '0 0';
    }
}


/**
 * Affiche l'état de la recherche (chargement et barre de progression).
 * setProgress doit être défini avant cet appel.
 * @param {boolean} visible - Vrai pour afficher, Faux pour cacher.
 * @param {string} text - Texte à afficher pendant le chargement.
 */
function setStatus(visible, text = 'Recherche en cours...') {
    const statusDiv = document.getElementById('status');
    const loadingText = document.getElementById('loading-text');
    const progressBar = document.getElementById('progress-bar');

    if (!statusDiv || !loadingText || !progressBar) return; // Sécurité

    statusDiv.classList.toggle('hidden', !visible);
    if (visible) {
        loadingText.textContent = text;
        setProgress(0);
    } else {
        progressBar.style.width = '0%';
    }
}


/**
 * Nettoie et formate les résultats en éléments HTML.
 * @param {Array<Object>} products - Liste des produits.
 */
function renderResults(products) {
    const resultsContainer = document.getElementById('results-container');
    if (!resultsContainer) return;

    resultsContainer.innerHTML = ''; 

    if (products.length === 0) {
        resultsContainer.innerHTML = '<p class="no-results">Aucun produit pertinent trouvé ou erreur de scraping.</p>';
        return;
    }

    // Tri par prix au kg (le moins cher en premier)
    products.sort((a, b) => a.unit_price_kg - b.unit_price_kg);

    const list = document.createElement('div');
    list.className = 'product-list';

    products.forEach(product => {
        const item = document.createElement('div');
        item.className = 'product-item';
        
        // Utilisation de toFixed et replace pour le format français
        const unitPrice = product.unit_price_kg.toFixed(2).replace('.', ',');
        const totalPrice = product.total_price.toFixed(2).replace('.', ',');
        
        item.innerHTML = `
            <div class="product-info">
                <h3 class="product-title">
                    <a href="${product.link}" target="_blank" rel="noopener noreferrer">${product.title}</a>
                </h3>
                <p class="unit-price-display">
                    Prix au kg: <span class="price-value">${unitPrice} €/kg</span>
                </p>
            </div>
            <div class="product-details">
                <p class="total-price">
                    Prix total: ${totalPrice} €
                </p>
                </div>
        `;
        list.appendChild(item);
    });

    resultsContainer.appendChild(list);
}


// ====================================================================
// SECTION 2 : INITIALISATION ET LOGIQUE PRINCIPALE
// ====================================================================

document.addEventListener('DOMContentLoaded', () => {
    // Déclaration des constantes
    const searchForm = document.getElementById('search-form');
    const queryInput = document.getElementById('query');

    // Constantes d'API
    const API_URL = '/api/search'; 
    const MAX_PAGES = 5; 

    if (!searchForm || !queryInput) return; // Sécurité de base

    /**
     * Gère la soumission du formulaire et l'appel à l'API.
     */
    searchForm.addEventListener('submit', async (e) => {
        e.preventDefault();

        const query = queryInput.value.trim();
        if (!query) return;

        setStatus(true, `Recherche de "${query}" en cours...`);

        // Afficher le message d'attente
        document.getElementById('results-container').innerHTML = '<p class="initial-message">Veuillez patienter pendant le scraping...</p>';


        let progressInterval;
        try {
            // Simuler la progression pendant le temps de scraping
            progressInterval = setInterval(() => {
                const progressBar = document.getElementById('progress-bar');
                if (!progressBar) return;

                // Utilisation de .replace('%', '') pour obtenir la valeur numérique
                const current = parseInt(progressBar.style.width.replace('%', ''), 10) || 0;
                if (current < 90) { // S'arrêter juste avant 100%
                    setProgress(current + 3);
                }
            }, 500);

            const url = `${API_URL}?query=${encodeURIComponent(query)}&pages=${MAX_PAGES}`;
            const response = await fetch(url);
            
            clearInterval(progressInterval); // Arrêter la simulation de progression

            if (!response.ok) {
                // Tenter de lire le message d'erreur JSON
                const errorData = await response.json().catch(() => ({ error: 'Erreur inconnue du serveur Flask (la réponse n\'était pas JSON).' }));
                throw new Error(errorData.error || `Erreur HTTP: ${response.status}`);
            }

            const products = await response.json();
            setProgress(100);
            setStatus(false); 
            renderResults(products);

        } catch (error) {
            if (progressInterval) {
                clearInterval(progressInterval);
            }
            console.error('Erreur lors du scraping:', error);
            setStatus(false);
            // Afficher l'erreur dans l'interface
            document.getElementById('results-container').innerHTML = `<p class="error-message">Une erreur s'est produite: ${error.message}. Vérifiez le Terminal pour les logs Python/Flask.</p>`;
        }
    });

});