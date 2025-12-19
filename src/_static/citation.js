/**
 * Citation navigation handler for bibliography back links.
 * 
 * Provides smart "back" behavior:
 * - If we arrived at a bibliography entry by clicking a :cite: link, 
 *   go back to that exact location
 * - If we navigated directly (URL, scrolling, etc.), find and jump to 
 *   the first :cite: reference for this entry
 */
(function() {
    'use strict';
    
    // Track the last citation anchor we clicked
    let lastClickedCitationAnchor = null;
    
    // Listen for clicks on citation references
    document.addEventListener('click', function(event) {
        const target = event.target.closest('.citation-ref');
        if (target) {
            // Store the anchor ID we're navigating to
            lastClickedCitationAnchor = target.getAttribute('href')?.replace('#', '') 
                                     || target.getAttribute('refid');
        }
    });
    
    // Handle back link clicks
    window.citationGoBack = function(anchorId) {
        // Check if we arrived here by clicking a citation link to this specific entry
        if (lastClickedCitationAnchor === anchorId) {
            // We clicked a citation to get here, so go back
            lastClickedCitationAnchor = null;
            history.back();
        } else {
            // We didn't click a citation, find the first reference to this entry
            const selector = '.citation-ref[href="#' + anchorId + '"], ' +
                           '.citation-ref[refid="' + anchorId + '"]';
            const firstRef = document.querySelector(selector);
            
            if (firstRef) {
                // Scroll to the first citation reference
                firstRef.scrollIntoView({ behavior: 'smooth', block: 'center' });
                
                // Briefly highlight it
                firstRef.classList.add('citation-highlight');
                setTimeout(function() {
                    firstRef.classList.remove('citation-highlight');
                }, 2000);
            }
        }
    };
})();
