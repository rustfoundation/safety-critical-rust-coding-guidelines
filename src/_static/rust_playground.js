/* SPDX-License-Identifier: MIT OR Apache-2.0
   SPDX-FileCopyrightText: The Coding Guidelines Subcommittee Contributors */

/**
 * Rust Playground Interactive Examples
 * 
 * This script provides interactivity for Rust code examples:
 * - Copy button: Copies full code including hidden lines to clipboard
 * - Run button: Executes code on the Rust Playground
 * - Toggle button: Shows/hides hidden lines (# prefixed)
 * 
 * Note: This file is also embedded in exts/coding_guidelines/rust_examples.py
 * and generated at build time. Changes should be made in both places.
 */
(function() {
    'use strict';
    
    const PLAYGROUND_URL = 'https://play.rust-lang.org/execute';
    
    // Initialize all rust examples on page load
    document.addEventListener('DOMContentLoaded', function() {
        initializeRustExamples();
    });
    
    function initializeRustExamples() {
        const containers = document.querySelectorAll('.rust-example-container');
        containers.forEach(initializeExample);
    }
    
    function initializeExample(container) {
        // Get the data
        const dataScript = container.querySelector('.rust-example-data');
        if (!dataScript) return;
        
        let data;
        try {
            data = JSON.parse(dataScript.textContent);
        } catch (e) {
            console.error('Failed to parse rust example data:', e);
            return;
        }
        
        // Store data on container for later access
        container._rustData = data;
        
        // Set up button handlers
        const copyBtn = container.querySelector('.rust-btn-copy');
        const runBtn = container.querySelector('.rust-btn-run');
        const toggleBtn = container.querySelector('.rust-btn-toggle-hidden');
        
        if (copyBtn) {
            copyBtn.addEventListener('click', function() {
                handleCopy(container, data);
            });
        }
        
        if (runBtn && data.runnable) {
            runBtn.addEventListener('click', function() {
                handleRun(container, data);
            });
        }
        
        if (toggleBtn && data.hasHiddenLines) {
            toggleBtn.addEventListener('click', function() {
                handleToggleHidden(container, data);
            });
        }
    }
    
    function handleCopy(container, data) {
        const copyBtn = container.querySelector('.rust-btn-copy');
        const tooltip = copyBtn.querySelector('.rust-btn-tooltip');
        
        // Always copy full code including hidden lines
        navigator.clipboard.writeText(data.code).then(function() {
            // Show success tooltip
            tooltip.textContent = 'Copied!';
            tooltip.classList.add('show');
            
            setTimeout(function() {
                tooltip.classList.remove('show');
            }, 1500);
        }).catch(function(err) {
            console.error('Failed to copy:', err);
            tooltip.textContent = 'Failed to copy';
            tooltip.classList.add('show');
            
            setTimeout(function() {
                tooltip.classList.remove('show');
            }, 1500);
        });
    }
    
    function handleRun(container, data) {
        const runBtn = container.querySelector('.rust-btn-run');
        const outputDiv = container.querySelector('.rust-example-output');
        const statusSpan = container.querySelector('.rust-example-output-status');
        const contentPre = container.querySelector('.rust-example-output-content');
        
        // Prevent double-click
        if (runBtn.classList.contains('running')) return;
        
        // Set running state (mdBook style - subtle visual change)
        runBtn.classList.add('running');
        runBtn.disabled = true;
        
        // Show output area with loading message
        outputDiv.style.display = 'block';
        statusSpan.textContent = 'Running...';
        statusSpan.className = 'rust-example-output-status';
        contentPre.textContent = '';
        
        // Prepare the request
        const requestBody = {
            channel: data.channel,
            mode: 'debug',
            edition: data.edition,
            crateType: 'bin',
            tests: false,
            code: data.code,
            backtrace: false
        };
        
        fetch(PLAYGROUND_URL, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(requestBody)
        })
        .then(function(response) {
            if (!response.ok) {
                throw new Error('Playground request failed: ' + response.status);
            }
            return response.json();
        })
        .then(function(result) {
            displayResult(container, data, result);
        })
        .catch(function(error) {
            displayError(container, data, error);
        })
        .finally(function() {
            runBtn.classList.remove('running');
            runBtn.disabled = false;
        });
    }
    
    function displayResult(container, data, result) {
        const statusSpan = container.querySelector('.rust-example-output-status');
        const contentPre = container.querySelector('.rust-example-output-content');
        
        const hasError = result.stderr && result.stderr.trim();
        const hasOutput = result.stdout && result.stdout.trim();
        const success = result.success;
        
        let output = '';
        if (hasError) {
            output += result.stderr;
        }
        if (hasOutput) {
            if (output) output += '\n';
            output += result.stdout;
        }
        if (!output) {
            output = success ? '(no output)' : '(compilation failed with no error message)';
        }
        
        // Determine status based on expected outcome
        let statusText = '';
        let statusClass = '';
        
        switch (data.expectedOutcome) {
            case 'compile_fail':
                if (!success) {
                    // Check if expected error code matches
                    if (data.expectedError) {
                        if (result.stderr && result.stderr.includes(data.expectedError)) {
                            statusText = 'Compilation failed as expected (' + data.expectedError + ')';
                            statusClass = 'expected';
                        } else {
                            statusText = 'Compilation failed (expected ' + data.expectedError + ')';
                            statusClass = 'expected';
                        }
                    } else {
                        statusText = 'Compilation failed as expected';
                        statusClass = 'expected';
                    }
                } else {
                    statusText = 'Unexpected success (expected compile_fail)';
                    statusClass = 'error';
                }
                break;
                
            case 'should_panic':
                if (success) {
                    // Check if there was a panic in the output
                    const panicOccurred = (result.stderr && result.stderr.includes('panicked')) ||
                                         (result.stdout && result.stdout.includes('panicked'));
                    if (panicOccurred) {
                        statusText = 'Panicked as expected';
                        statusClass = 'expected';
                    } else {
                        statusText = 'Expected panic did not occur';
                        statusClass = 'error';
                    }
                } else {
                    statusText = 'Compilation failed';
                    statusClass = 'error';
                }
                break;
                
            case 'no_run':
                if (success) {
                    statusText = 'Compiled successfully (not executed)';
                    statusClass = 'success';
                    output = '(compilation successful - execution skipped per no_run)';
                } else {
                    statusText = 'Compilation failed';
                    statusClass = 'error';
                }
                break;
                
            default:  // success expected
                if (success) {
                    statusText = 'Success';
                    statusClass = 'success';
                } else {
                    statusText = 'Failed';
                    statusClass = 'error';
                }
        }
        
        statusSpan.textContent = statusText;
        statusSpan.className = 'rust-example-output-status ' + statusClass;
        
        // Add version note if there might be version differences
        const configVersion = container.dataset.version;
        const configChannel = container.dataset.channel;
        if (configVersion && !success && data.expectedOutcome === 'success') {
            output += '\n\nℹ️ Note: This example targets Rust ' + configVersion + '. ';
            output += 'The playground uses the latest ' + configChannel + ' version, which may behave differently.';
        }
        
        contentPre.textContent = output;
        
        // Set up close button
        const closeBtn = container.querySelector('.rust-example-output-close');
        closeBtn.onclick = function() {
            container.querySelector('.rust-example-output').style.display = 'none';
        };
    }
    
    function displayError(container, data, error) {
        const statusSpan = container.querySelector('.rust-example-output-status');
        const contentPre = container.querySelector('.rust-example-output-content');
        
        statusSpan.textContent = 'Error';
        statusSpan.className = 'rust-example-output-status error';
        contentPre.textContent = 'Failed to run code: ' + error.message + '\n\nPlease check your internet connection and try again.';
        
        // Set up close button
        const closeBtn = container.querySelector('.rust-example-output-close');
        closeBtn.onclick = function() {
            container.querySelector('.rust-example-output').style.display = 'none';
        };
    }
    
    function handleToggleHidden(container, data) {
        const toggleBtn = container.querySelector('.rust-btn-toggle-hidden');
        const codeElement = container.querySelector('.rust-example-code code');
        
        const isShowingHidden = toggleBtn.classList.contains('active');
        
        if (isShowingHidden) {
            // Hide the hidden lines - show display code
            codeElement.innerHTML = escapeHtml(data.displayCode);
            toggleBtn.classList.remove('active');
            toggleBtn.title = 'Show hidden lines';
            toggleBtn.setAttribute('aria-label', 'Show hidden lines');
        } else {
            // Show the hidden lines - render full code with markers
            codeElement.innerHTML = renderCodeWithHiddenLines(data.code, data.hiddenLineNumbers);
            toggleBtn.classList.add('active');
            toggleBtn.title = 'Hide hidden lines';
            toggleBtn.setAttribute('aria-label', 'Hide hidden lines');
        }
    }
    
    function renderCodeWithHiddenLines(code, hiddenLineNumbers) {
        const lines = code.split('\n');
        const hiddenSet = new Set(hiddenLineNumbers);
        
        return lines.map(function(line, index) {
            const escaped = escapeHtml(line);
            if (hiddenSet.has(index)) {
                return '<span class="hidden-line"># ' + escaped + '</span>';
            }
            return escaped;
        }).join('\n');
    }
    
    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
    
    // Expose for potential external use
    window.RustPlayground = {
        initialize: initializeRustExamples,
        run: function(container) {
            if (container._rustData) {
                handleRun(container, container._rustData);
            }
        }
    };
})();
