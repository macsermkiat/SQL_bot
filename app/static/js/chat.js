/**
 * Chat interface with streaming progress and cancel support.
 * Uses SSE (Server-Sent Events) via fetch + ReadableStream.
 */
(function () {
    "use strict";

    var chatContainer = document.getElementById("chat-container");
    var inputForm = document.getElementById("input-form");
    var messageInput = document.getElementById("message-input");
    var sendButton = document.getElementById("send-button");
    var stopButton = document.getElementById("stop-button");
    var sessionId = null;
    var userRole = window.USER_ROLE || "standard_user";
    var abortController = null;
    var streamAborted = false;

    function escapeHtml(text) {
        var div = document.createElement("div");
        div.textContent = text;
        return div.innerHTML.replace(/\n/g, "<br>");
    }

    function escapeHtmlRaw(text) {
        var div = document.createElement("div");
        div.textContent = text;
        return div.innerHTML;
    }

    function addMessage(role, content, metadata) {
        metadata = metadata || {};
        var messageDiv = document.createElement("div");
        messageDiv.className = "message " + role;

        var html = '<div class="message-content">' + escapeHtml(content) + "</div>";

        if (role === "assistant" && metadata.confidence) {
            var metaItems =
                '<span class="confidence-badge confidence-' +
                metadata.confidence +
                '">' +
                "Confidence: " +
                metadata.confidence +
                "</span>";

            if (metadata.token_usage) {
                var tu = metadata.token_usage;
                metaItems +=
                    '<span class="token-stat">' +
                    tu.input_tokens.toLocaleString() +
                    " in</span>" +
                    '<span class="token-stat">' +
                    tu.output_tokens.toLocaleString() +
                    " out</span>";
            }

            if (userRole === "super_user" && metadata.query_result) {
                var qr = metadata.query_result;
                metaItems +=
                    '<span class="query-stat">' +
                    qr.row_count +
                    " rows" +
                    (qr.truncated ? " (truncated)" : "") +
                    "</span>" +
                    '<span class="query-stat">' +
                    qr.execution_time_ms.toFixed(0) +
                    " ms" +
                    "</span>";
            }

            html += '<div class="message-meta">' + metaItems + "</div>";
        }

        if (userRole === "super_user" && metadata.sql) {
            html +=
                '<details class="expandable"><summary>View SQL</summary>' +
                '<div class="expandable-content">' +
                escapeHtml(metadata.sql) +
                "</div></details>";
        }

        if (metadata.assumptions && metadata.assumptions.length > 0) {
            html +=
                '<details class="expandable"><summary>Assumptions</summary>' +
                '<ul class="assumptions-list">' +
                metadata.assumptions
                    .map(function (a) {
                        return "<li>" + escapeHtml(a) + "</li>";
                    })
                    .join("") +
                "</ul></details>";
        }

        if (metadata.error) {
            html +=
                '<div class="error-message">Error: ' +
                escapeHtml(metadata.error) +
                "</div>";
        }

        messageDiv.innerHTML = html;
        chatContainer.appendChild(messageDiv);
        chatContainer.scrollTop = chatContainer.scrollHeight;
    }

    function addProgressIndicator() {
        var progressDiv = document.createElement("div");
        progressDiv.className = "message assistant";
        progressDiv.id = "progress-message";
        progressDiv.innerHTML =
            '<div class="message-content progress-content">' +
            '<div class="progress-indicator">' +
            '<div class="progress-spinner" aria-hidden="true"></div>' +
            '<span class="progress-text" aria-live="polite">Starting...</span>' +
            "</div>" +
            '<div class="progress-bar-container" role="progressbar" ' +
            'aria-valuenow="0" aria-valuemin="0" aria-valuemax="100" ' +
            'aria-label="Query progress">' +
            '<div class="progress-bar" style="width: 0%"></div>' +
            "</div>" +
            "</div>";
        chatContainer.appendChild(progressDiv);
        chatContainer.scrollTop = chatContainer.scrollHeight;
    }

    function updateProgress(message, progress) {
        var progressMsg = document.getElementById("progress-message");
        if (!progressMsg) return;

        var textEl = progressMsg.querySelector(".progress-text");
        var barEl = progressMsg.querySelector(".progress-bar");
        var barContainer = progressMsg.querySelector(".progress-bar-container");

        if (textEl) textEl.textContent = message;
        if (barEl) barEl.style.width = progress + "%";
        if (barContainer) barContainer.setAttribute("aria-valuenow", Math.round(progress));

        chatContainer.scrollTop = chatContainer.scrollHeight;
    }

    function removeProgressIndicator() {
        var el = document.getElementById("progress-message");
        if (el) el.remove();
    }

    function showAutoFixCountdown(data) {
        var progressMsg = document.getElementById("progress-message");
        if (!progressMsg) {
            addProgressIndicator();
            progressMsg = document.getElementById("progress-message");
            if (!progressMsg) return;
        }

        var content = progressMsg.querySelector(".message-content");
        if (!content) return;

        var sec = data.seconds_remaining;

        // First event has error_message — build the full banner
        if (data.error_message) {
            var errorText = escapeHtml(data.error_message);
            var sqlHtml = "";
            if (userRole === "super_user" && data.failed_sql) {
                sqlHtml =
                    '<details class="auto-fix-sql-details">' +
                    "<summary>View failed SQL</summary>" +
                    '<pre class="auto-fix-sql">' +
                    escapeHtmlRaw(data.failed_sql) +
                    "</pre></details>";
            }
            content.innerHTML =
                '<div class="auto-fix-banner">' +
                '<div class="auto-fix-header">' +
                '<span class="auto-fix-icon">&#9888;</span>' +
                " Error detected" +
                "</div>" +
                '<div class="auto-fix-error">' + errorText + "</div>" +
                sqlHtml +
                '<div class="auto-fix-countdown-row">' +
                'Auto-fixing in <span class="auto-fix-seconds">' +
                sec +
                "</span>..." +
                "</div>" +
                "</div>";
        } else if (sec === 0) {
            // Countdown finished — transition to fixing state
            var row = content.querySelector(".auto-fix-countdown-row");
            if (row) {
                row.innerHTML =
                    '<span class="auto-fix-fixing">Fixing now...</span>';
            }
        } else {
            // Subsequent ticks — just update the number
            var secEl = content.querySelector(".auto-fix-seconds");
            if (secEl) {
                secEl.textContent = sec;
                secEl.classList.remove("auto-fix-pulse");
                // Force reflow to restart animation
                void secEl.offsetWidth;
                secEl.classList.add("auto-fix-pulse");
            }
        }

        chatContainer.scrollTop = chatContainer.scrollHeight;
    }

    function handleAutoFixNewAttempt(data) {
        // Finalize current progress indicator as an error message
        var progressMsg = document.getElementById("progress-message");
        if (progressMsg) {
            progressMsg.removeAttribute("id");
            progressMsg.className = "message assistant";

            var attemptNum = (data.attempt || 2) - 1;
            var maxAttempts = data.max_attempts || 6;
            var content = progressMsg.querySelector(".message-content");
            if (content) {
                var html =
                    '<div class="auto-fix-retry-note">' +
                    '<span class="auto-fix-icon">&#9888;</span> ' +
                    "Attempt " + attemptNum + "/" + maxAttempts + " failed" +
                    "</div>";

                if (data.error_message) {
                    html +=
                        '<div class="error-message">' +
                        escapeHtml(data.error_message) +
                        "</div>";
                }

                if (userRole === "super_user" && data.failed_sql) {
                    html +=
                        '<details class="expandable">' +
                        "<summary>View failed SQL</summary>" +
                        '<div class="expandable-content"><pre>' +
                        escapeHtmlRaw(data.failed_sql) +
                        "</pre></div></details>";
                }

                content.innerHTML = html;
            }
        }

        // Add fresh progress indicator for the new attempt
        addProgressIndicator();
        chatContainer.scrollTop = chatContainer.scrollHeight;
    }

    function setLoadingState(loading) {
        if (loading) {
            sendButton.style.display = "none";
            stopButton.style.display = "inline-flex";
            messageInput.disabled = true;
        } else {
            sendButton.style.display = "";
            stopButton.style.display = "none";
            messageInput.disabled = false;
            abortController = null;
            messageInput.focus();
        }
    }

    function stopQuery() {
        streamAborted = true;
        if (abortController) {
            abortController.abort();
            abortController = null;
        }
        removeProgressIndicator();
        addMessage("assistant", "Query cancelled.", {});
        setLoadingState(false);
    }

    function parseSSEEvents(text) {
        var events = [];
        var blocks = text.split("\n\n");

        for (var i = 0; i < blocks.length; i++) {
            var block = blocks[i].trim();
            if (!block) continue;

            var eventType = "message";
            var data = null;
            var lines = block.split("\n");

            for (var j = 0; j < lines.length; j++) {
                var line = lines[j];
                if (line.indexOf("event: ") === 0) {
                    eventType = line.substring(7).trim();
                } else if (line.indexOf("data: ") === 0) {
                    data = line.substring(6);
                }
            }

            if (data) {
                try {
                    events.push({ event: eventType, data: JSON.parse(data) });
                } catch (e) {
                    // Skip malformed JSON
                }
            }
        }
        return events;
    }

    function handleSSEEvent(event) {
        if (streamAborted) return;
        var data = event.data;

        switch (event.event) {
            case "progress":
                updateProgress(data.message, data.progress);
                break;

            case "complete":
                removeProgressIndicator();
                sessionId = data.session_id;
                addMessage("assistant", data.answer, {
                    confidence: data.confidence,
                    sql: data.sql,
                    assumptions: data.assumptions,
                    error: data.error,
                    query_result: data.query_result,
                    token_usage: data.token_usage,
                });
                break;

            case "auto_fix_countdown":
                showAutoFixCountdown(data);
                break;

            case "auto_fix_new_attempt":
                handleAutoFixNewAttempt(data);
                break;

            case "error":
                removeProgressIndicator();
                addMessage(
                    "assistant",
                    "An error occurred: " + (data.message || "Unknown error"),
                    { error: data.message }
                );
                break;

            case "cancelled":
                removeProgressIndicator();
                addMessage(
                    "assistant",
                    data.message || "Query cancelled.",
                    {}
                );
                break;
        }
    }

    function sendMessage(message) {
        addMessage("user", message);
        addProgressIndicator();
        setLoadingState(true);

        abortController = new AbortController();
        streamAborted = false;
        var buffer = "";

        fetch("/api/chat/stream", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                message: message,
                session_id: sessionId,
            }),
            signal: abortController.signal,
        })
            .then(function (response) {
                if (response.status === 401) {
                    window.location.href = "/login";
                    return;
                }
                if (!response.ok) {
                    throw new Error("Server error: " + response.status);
                }

                var reader = response.body.getReader();
                var decoder = new TextDecoder();

                function pump() {
                    return reader.read().then(function (result) {
                        if (result.done) return;

                        buffer += decoder.decode(result.value, { stream: true });

                        var parts = buffer.split("\n\n");
                        buffer = parts.pop();

                        for (var i = 0; i < parts.length; i++) {
                            var events = parseSSEEvents(parts[i] + "\n\n");
                            for (var j = 0; j < events.length; j++) {
                                handleSSEEvent(events[j]);
                            }
                        }

                        return pump();
                    });
                }

                return pump();
            })
            .catch(function (err) {
                if (err.name === "AbortError") {
                    return;
                }
                removeProgressIndicator();
                addMessage(
                    "assistant",
                    "Sorry, I encountered an error. Please try again.",
                    { error: err.message }
                );
            })
            .finally(function () {
                setLoadingState(false);
            });
    }

    stopButton.addEventListener("click", function () {
        stopQuery();
    });

    document.addEventListener("keydown", function (e) {
        if (e.key === "Escape" && abortController) {
            stopQuery();
        }
    });

    inputForm.addEventListener("submit", function (e) {
        e.preventDefault();
        if (abortController) return;
        var message = messageInput.value.trim();
        if (!message) return;
        messageInput.value = "";
        sendMessage(message);
    });

    messageInput.focus();
})();
