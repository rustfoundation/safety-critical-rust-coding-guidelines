/* Rust Playground Interactive Examples */
(function() {
    'use strict';
    
    const PLAYGROUND_URL = 'https://play.rust-lang.org/execute';
    const PLAYGROUND_MIRI_URL = 'https://play.rust-lang.org/miri';
    
    // SVG icons (Font Awesome Free 6.x)
    const ICON_COPY = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 448 512"><path d="M208 0H332.1c12.7 0 24.9 5.1 33.9 14.1l67.9 67.9c9 9 14.1 21.2 14.1 33.9V336c0 26.5-21.5 48-48 48H208c-26.5 0-48-21.5-48-48V48c0-26.5 21.5-48 48-48zM48 128h80v64H64V448H256V416h64v48c0 26.5-21.5 48-48 48H48c-26.5 0-48-21.5-48-48V176c0-26.5 21.5-48 48-48z"/></svg>';
    const ICON_PLAY = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 384 512"><path d="M73 39c-14.8-9.1-33.4-9.4-48.5-.9S0 62.6 0 80V432c0 17.4 9.4 33.4 24.5 41.9s33.7 8.1 48.5-.9L361 297c14.3-8.7 23-24.2 23-41s-8.7-32.2-23-41L73 39z"/></svg>';
    const ICON_EYE = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 576 512"><path d="M288 32c-80.8 0-145.5 36.8-192.6 80.6C48.6 156 17.3 208 2.5 243.7c-3.3 7.9-3.3 16.7 0 24.6C17.3 304 48.6 356 95.4 399.4C142.5 443.2 207.2 480 288 480s145.5-36.8 192.6-80.6c46.8-43.5 78.1-95.4 93-131.1c3.3-7.9 3.3-16.7 0-24.6c-14.9-35.7-46.2-87.7-93-131.1C433.5 68.8 368.8 32 288 32zM432 256c0 79.5-64.5 144-144 144s-144-64.5-144-144s64.5-144 144-144s144 64.5 144 144zM288 192c0 35.3-28.7 64-64 64c-11.5 0-22.3-3-31.6-8.4c-.2 2.8-.4 5.5-.4 8.4c0 53 43 96 96 96s96-43 96-96s-43-96-96-96c-2.8 0-5.6 .1-8.4 .4c5.3 9.3 8.4 20.1 8.4 31.6z"/></svg>';
    const ICON_MIRI = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 640"><!--!Font Awesome Free v7.1.0 by @fontawesome - https://fontawesome.com License - https://fontawesome.com/license/free Copyright 2025 Fonticons, Inc.--><path d="M240 64C213.5 64 192 85.5 192 112L192 320C192 346.5 213.5 368 240 368L304 368C330.5 368 352 346.5 352 320L352 256L384 256C454.7 256 512 313.3 512 384C512 454.7 454.7 512 384 512L96 512C78.3 512 64 526.3 64 544C64 561.7 78.3 576 96 576L544 576C561.7 576 576 561.7 576 544C576 526.3 561.7 512 544 512L527.1 512C557.5 478 576 433.2 576 384C576 278 490 192 384 192L352 192L352 112C352 85.5 330.5 64 304 64L240 64zM184 416C170.7 416 160 426.7 160 440C160 453.3 170.7 464 184 464L360 464C373.3 464 384 453.3 384 440C384 426.7 373.3 416 360 416L184 416z"/></svg>';
    
    document.addEventListener('DOMContentLoaded', initializeRustExamples);
    
    function initializeRustExamples() {
        const containers = document.querySelectorAll('.rust-example-container');
        containers.forEach(initializeExample);
    }
    
    function initializeExample(container) {
        // Find the JSON data script
        const dataScript = container.querySelector('script.rust-example-data');
        if (!dataScript) {
            console.warn('No rust-example-data found in container', container);
            return;
        }
        
        let data;
        try {
            data = JSON.parse(dataScript.textContent);
        } catch (e) {
            console.error('Failed to parse rust example data:', e);
            return;
        }
        
        container._rustData = data;
        
        // Find the code block (Sphinx wraps it in div.highlight)
        const highlightDiv = container.querySelector('.highlight');
        if (!highlightDiv) {
            console.warn('No .highlight found in container', container);
            return;
        }
        
        // Make the highlight div position:relative for button positioning
        highlightDiv.style.position = 'relative';
        
        // Create and inject the button toolbar
        const buttons = createButtonToolbar(container, data);
        highlightDiv.appendChild(buttons);
        
        // Store reference to pre element for code manipulation
        container._preElement = highlightDiv.querySelector('pre');
        container._originalHTML = container._preElement ? container._preElement.innerHTML : '';
    }
    
    function createButtonToolbar(container, data) {
        const toolbar = document.createElement('div');
        toolbar.className = 'rust-example-buttons';
        
        // Copy button
        const copyBtn = document.createElement('button');
        copyBtn.className = 'rust-btn rust-btn-copy';
        copyBtn.title = 'Copy to clipboard';
        copyBtn.setAttribute('aria-label', 'Copy to clipboard');
        copyBtn.innerHTML = '<span class="rust-btn-icon">' + ICON_COPY + '</span><span class="rust-btn-tooltip"></span>';
        copyBtn.addEventListener('click', function() { handleCopy(container, data); });
        toolbar.appendChild(copyBtn);
        
        // Run button
        const runBtn = document.createElement('button');
        runBtn.className = 'rust-btn rust-btn-run';
        runBtn.title = data.runnable ? 'Run this code' : 'This example cannot be run';
        runBtn.setAttribute('aria-label', runBtn.title);
        runBtn.disabled = !data.runnable;
        runBtn.innerHTML = '<span class="rust-btn-icon">' + ICON_PLAY + '</span>';
        if (data.runnable) {
            runBtn.addEventListener('click', function() { handleRun(container, data); });
        }
        toolbar.appendChild(runBtn);
        
        // Miri button (only if miri option is set and not skip)
        if (data.miri && data.miri.mode !== 'skip') {
            const miriBtn = document.createElement('button');
            miriBtn.className = 'rust-btn rust-btn-miri';
            miriBtn.title = 'Run with Miri (undefined behavior detector)';
            miriBtn.setAttribute('aria-label', miriBtn.title);
            miriBtn.innerHTML = '<span class="rust-btn-icon">' + ICON_MIRI + '</span>';
            miriBtn.addEventListener('click', function() { handleMiri(container, data); });
            toolbar.appendChild(miriBtn);
        }
        
        // Toggle hidden lines button (only if there are hidden lines)
        if (data.hasHiddenLines) {
            const toggleBtn = document.createElement('button');
            toggleBtn.className = 'rust-btn rust-btn-toggle-hidden';
            toggleBtn.title = 'Show hidden lines';
            toggleBtn.setAttribute('aria-label', 'Show hidden lines');
            toggleBtn.innerHTML = '<span class="rust-btn-icon">' + ICON_EYE + '</span>';
            toggleBtn.addEventListener('click', function() { handleToggleHidden(container, data); });
            toolbar.appendChild(toggleBtn);
        }
        
        return toolbar;
    }
    
    function handleCopy(container, data) {
        const copyBtn = container.querySelector('.rust-btn-copy');
        const tooltip = copyBtn.querySelector('.rust-btn-tooltip');
        
        navigator.clipboard.writeText(data.code).then(function() {
            tooltip.textContent = 'Copied!';
            tooltip.classList.add('show');
            setTimeout(function() { tooltip.classList.remove('show'); }, 1500);
        }).catch(function(err) {
            console.error('Failed to copy:', err);
            tooltip.textContent = 'Failed';
            tooltip.classList.add('show');
            setTimeout(function() { tooltip.classList.remove('show'); }, 1500);
        });
    }
    
    function handleRun(container, data) {
        const runBtn = container.querySelector('.rust-btn-run');
        
        if (runBtn.classList.contains('running')) return;
        
        runBtn.classList.add('running');
        runBtn.disabled = true;
        
        // Store last action for retry
        container._lastAction = function() { handleRun(container, data); };
        
        // Remove any existing output or error
        const existingOutput = container.querySelector('.rust-example-output');
        if (existingOutput) existingOutput.remove();
        const existingError = container.querySelector('.rust-example-error');
        if (existingError) existingError.remove();
        
        // Create output area
        const output = createOutputArea();
        container.appendChild(output);
        
        const statusSpan = output.querySelector('.rust-example-output-status');
        const contentPre = output.querySelector('.rust-example-output-content');
        
        statusSpan.textContent = 'Running...';
        statusSpan.className = 'rust-example-output-status';
        
        fetch(PLAYGROUND_URL, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                channel: data.channel,
                mode: 'debug',
                edition: data.edition,
                crateType: 'bin',
                tests: false,
                code: data.code,
                backtrace: false
            })
        })
        .then(function(response) {
            if (!response.ok) {
                if (response.status === 429) {
                    throw new Error('rate_limit');
                }
                throw new Error('http_' + response.status);
            }
            return response.json();
        })
        .then(function(result) {
            displayResult(container, data, result, statusSpan, contentPre);
        })
        .catch(function(error) {
            output.remove();
            showError(container, error.message);
        })
        .finally(function() {
            runBtn.classList.remove('running');
            runBtn.disabled = false;
        });
    }
    
    function createOutputArea() {
        const output = document.createElement('div');
        output.className = 'rust-example-output';
        output.innerHTML = 
            '<div class="rust-example-output-header">' +
                '<span class="rust-example-output-status"></span>' +
                '<button class="rust-example-output-close" title="Close">×</button>' +
            '</div>' +
            '<pre class="rust-example-output-content"></pre>';
        
        output.querySelector('.rust-example-output-close').addEventListener('click', function() {
            output.remove();
        });
        
        return output;
    }
    
    function displayResult(container, data, result, statusSpan, contentPre) {
        const success = result.success;
        let output = '';
        
        if (result.stderr) output += result.stderr;
        if (result.stdout) {
            if (output) output += '\n';
            output += result.stdout;
        }
        if (!output) output = success ? '(no output)' : '(compilation failed)';
        
        // Check for warnings in output
        const hasWarnings = output.includes('warning:') || output.includes('warning[');
        const warnMode = data.warnMode || 'allow';  // Default to allow if not set
        const failOnWarnings = warnMode === 'error';
        
        let statusText = '';
        let statusClass = '';
        
        switch (data.expectedOutcome) {
            case 'compile_fail':
                if (!success) {
                    statusText = data.expectedError && result.stderr && result.stderr.includes(data.expectedError)
                        ? 'Compilation failed as expected (' + data.expectedError + ')'
                        : 'Compilation failed as expected';
                    statusClass = 'expected';
                } else {
                    statusText = 'Unexpected success (expected compile_fail)';
                    statusClass = 'error';
                }
                break;
            case 'should_panic':
                if (!success && ((result.stderr && result.stderr.includes('panicked')) || 
                               (result.stdout && result.stdout.includes('panicked')))) {
                    statusText = 'Panicked as expected';
                    statusClass = 'expected';
                } else if (!success) {
                    statusText = 'Compilation failed';
                    statusClass = 'error';
                } else {
                    statusText = 'Expected panic did not occur';
                    statusClass = 'error';
                }
                break;
            case 'no_run':
                if (success) {
                    if (hasWarnings && failOnWarnings) {
                        statusText = 'Compiled with warnings';
                        statusClass = 'warning';
                    } else {
                        statusText = 'Compiled successfully';
                        statusClass = 'success';
                    }
                    output = '(compilation successful - not executed)' + (hasWarnings ? '\n\n' + output : '');
                } else {
                    statusText = 'Compilation failed';
                    statusClass = 'error';
                }
                break;
            default:
                if (success) {
                    if (hasWarnings && failOnWarnings) {
                        statusText = 'Success with warnings';
                        statusClass = 'warning';
                    } else {
                        statusText = 'Success';
                        statusClass = 'success';
                    }
                } else {
                    statusText = 'Failed';
                    statusClass = 'error';
                }
        }
        
        statusSpan.textContent = statusText;
        statusSpan.className = 'rust-example-output-status ' + statusClass;
        
        if (!success && data.expectedOutcome === 'success' && data.version) {
            output += '\n\nℹ️ Note: This example targets Rust ' + data.version + 
                     '. The playground uses the latest ' + data.channel + ' version.';
        }
        
        contentPre.textContent = output;
    }
    
    function handleMiri(container, data) {
        const miriBtn = container.querySelector('.rust-btn-miri');
        
        if (miriBtn.classList.contains('running')) return;
        
        miriBtn.classList.add('running');
        miriBtn.disabled = true;
        
        // Store last action for retry
        container._lastAction = function() { handleMiri(container, data); };
        
        // Remove any existing output or error
        const existingOutput = container.querySelector('.rust-example-output');
        if (existingOutput) existingOutput.remove();
        const existingError = container.querySelector('.rust-example-error');
        if (existingError) existingError.remove();
        
        // Create output area
        const output = createOutputArea();
        container.appendChild(output);
        
        const statusSpan = output.querySelector('.rust-example-output-status');
        const contentPre = output.querySelector('.rust-example-output-content');
        
        statusSpan.textContent = 'Running Miri...';
        statusSpan.className = 'rust-example-output-status';
        
        // Miri always uses nightly channel
        fetch(PLAYGROUND_MIRI_URL, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                channel: 'nightly',  // Miri requires nightly
                edition: data.edition,
                code: data.code
            })
        })
        .then(function(response) {
            if (!response.ok) {
                if (response.status === 429) {
                    throw new Error('rate_limit');
                }
                throw new Error('http_' + response.status);
            }
            return response.json();
        })
        .then(function(result) {
            displayMiriResult(container, data, result, statusSpan, contentPre);
        })
        .catch(function(error) {
            output.remove();
            showError(container, error.message);
        })
        .finally(function() {
            miriBtn.classList.remove('running');
            miriBtn.disabled = false;
        });
    }
    
    function displayMiriResult(container, data, result, statusSpan, contentPre) {
        let output = '';
        
        if (result.stderr) output += result.stderr;
        if (result.stdout) {
            if (output) output += '\n';
            output += result.stdout;
        }
        if (!output) output = '(no output from Miri)';
        
        // Check for UB in output
        const hasUB = output.includes('Undefined Behavior') || 
                      output.includes('error: unsupported operation') ||
                      output.includes('error[');
        
        // Check for warnings
        const hasWarnings = output.includes('warning:') || output.includes('warning[');
        const warnMode = data.warnMode || 'allow';
        const failOnWarnings = warnMode === 'error';
        
        const expectUB = data.miri && data.miri.mode === 'expect_ub';
        const ubSuccess = expectUB ? hasUB : !hasUB;
        
        let statusText = '';
        let statusClass = '';
        
        if (ubSuccess) {
            if (expectUB) {
                statusText = 'UB detected as expected';
                statusClass = 'miri-ub';
            } else if (hasWarnings && failOnWarnings) {
                statusText = 'No UB, but has warnings';
                statusClass = 'warning';
            } else {
                statusText = 'No undefined behavior detected';
                statusClass = 'miri-success';
            }
        } else {
            if (expectUB) {
                statusText = 'Expected UB but none detected';
                statusClass = 'error';
            } else {
                statusText = 'Undefined behavior detected!';
                statusClass = 'miri-ub';
            }
        }
        
        statusSpan.textContent = statusText;
        statusSpan.className = 'rust-example-output-status ' + statusClass;
        contentPre.textContent = output;
    }
    
    function showError(container, errorType) {
        // Remove any existing error
        const existing = container.querySelector('.rust-example-error');
        if (existing) existing.remove();
        
        // Determine error message
        let message = 'Playground unavailable';
        if (errorType === 'rate_limit') {
            message = 'Too many requests - wait a moment';
        } else if (errorType && errorType.startsWith('http_5')) {
            message = 'Playground error - try again';
        } else if (errorType === 'timeout') {
            message = 'Request timed out';
        }
        
        const errorDiv = document.createElement('div');
        errorDiv.className = 'rust-example-error';
        errorDiv.innerHTML = 
            '<span class="rust-example-error-icon">⚠️</span>' +
            '<span class="rust-example-error-message">' + message + '</span>' +
            '<button class="rust-example-error-retry">Retry</button>' +
            '<button class="rust-example-error-dismiss">×</button>';
        
        // Wire up buttons
        errorDiv.querySelector('.rust-example-error-retry').addEventListener('click', function() {
            errorDiv.remove();
            if (container._lastAction) container._lastAction();
        });
        errorDiv.querySelector('.rust-example-error-dismiss').addEventListener('click', function() {
            errorDiv.remove();
        });
        
        // Auto-dismiss after 10 seconds
        setTimeout(function() {
            if (errorDiv.parentNode) errorDiv.remove();
        }, 10000);
        
        container.appendChild(errorDiv);
    }
    
    function handleToggleHidden(container, data) {
        const toggleBtn = container.querySelector('.rust-btn-toggle-hidden');
        const pre = container._preElement;
        if (!pre) return;
        
        const isShowingHidden = toggleBtn.classList.contains('active');
        
        if (isShowingHidden) {
            // Restore original Pygments-highlighted HTML (without hidden lines)
            pre.innerHTML = container._originalHTML;
            toggleBtn.classList.remove('active');
            toggleBtn.title = 'Show hidden lines';
            toggleBtn.setAttribute('aria-label', 'Show hidden lines');
        } else {
            // Show pre-highlighted full code with hidden lines marked
            // This HTML was generated at build time by Pygments
            if (data.fullCodeHighlighted) {
                pre.innerHTML = data.fullCodeHighlighted;
            }
            toggleBtn.classList.add('active');
            toggleBtn.title = 'Hide hidden lines';
            toggleBtn.setAttribute('aria-label', 'Hide hidden lines');
        }
    }
    
    window.RustPlayground = {
        initialize: initializeRustExamples
    };
})();
