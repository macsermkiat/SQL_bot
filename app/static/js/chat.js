/**
 * Chat interface logic for KCMH SQL Bot.
 * Handles message sending, receiving, and role-aware display.
 */
(function () {
    "use strict";

    var chatContainer = document.getElementById("chat-container");
    var inputForm = document.getElementById("input-form");
    var messageInput = document.getElementById("message-input");
    var sendButton = document.getElementById("send-button");
    var sessionId = null;
    var userRole = window.USER_ROLE || "standard_user";

    function escapeHtml(text) {
        var div = document.createElement("div");
        div.textContent = text;
        return div.innerHTML.replace(/\n/g, "<br>");
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

            if (userRole === "super_user" && metadata.query_result) {
                var qr = metadata.query_result;
                metaItems +=
                    '<span class="query-stat">' +
                    qr.row_count + " rows" +
                    (qr.truncated ? " (truncated)" : "") +
                    "</span>" +
                    '<span class="query-stat">' +
                    qr.execution_time_ms.toFixed(0) + " ms" +
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

    function addLoadingIndicator() {
        var loadingDiv = document.createElement("div");
        loadingDiv.className = "message assistant";
        loadingDiv.id = "loading-message";
        loadingDiv.innerHTML =
            '<div class="message-content loading">' +
            '<div class="loading-dots"><span></span><span></span><span></span></div>' +
            "<span>Analyzing your question...</span></div>";
        chatContainer.appendChild(loadingDiv);
        chatContainer.scrollTop = chatContainer.scrollHeight;
    }

    function removeLoadingIndicator() {
        var el = document.getElementById("loading-message");
        if (el) el.remove();
    }

    function sendMessage(message) {
        addMessage("user", message);
        addLoadingIndicator();
        sendButton.disabled = true;

        fetch("/api/chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                message: message,
                session_id: sessionId,
            }),
        })
            .then(function (response) {
                if (response.status === 401) {
                    window.location.href = "/login";
                    return null;
                }
                if (!response.ok) throw new Error("Failed to get response");
                return response.json();
            })
            .then(function (data) {
                removeLoadingIndicator();
                if (!data) return;

                sessionId = data.session_id;

                addMessage("assistant", data.answer, {
                    confidence: data.confidence,
                    sql: data.sql,
                    assumptions: data.assumptions,
                    error: data.error,
                    query_result: data.query_result,
                });
            })
            .catch(function (err) {
                removeLoadingIndicator();
                addMessage(
                    "assistant",
                    "Sorry, I encountered an error. Please try again.",
                    { error: err.message }
                );
            })
            .finally(function () {
                sendButton.disabled = false;
                messageInput.focus();
            });
    }

    inputForm.addEventListener("submit", function (e) {
        e.preventDefault();
        var message = messageInput.value.trim();
        if (!message) return;
        messageInput.value = "";
        sendMessage(message);
    });

    messageInput.focus();
})();