(function (root) {
  "use strict";

  var allowedCallbacks = Object.freeze([
    "xtimers-auth://auth/callback",
    "xtimers-pro-auth://auth/callback"
  ]);

  function hasOAuthResponse(url) {
    var query = url.searchParams;
    var fragment = new URLSearchParams(url.hash.replace(/^#/, ""));
    var responseKeys = [
      "code",
      "error",
      "error_code",
      "error_description",
      "access_token"
    ];
    return responseKeys.some(function (key) {
      return query.has(key) || fragment.has(key);
    });
  }

  function buildReturnURL(pageURL, callbackBoundary) {
    if (allowedCallbacks.indexOf(callbackBoundary) === -1) return null;
    var source = new URL(pageURL);
    if (!hasOAuthResponse(source)) return null;
    return callbackBoundary + source.search + source.hash;
  }

  var api = Object.freeze({ buildReturnURL: buildReturnURL });
  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }

  if (!root.document) return;

  function start() {
    var body = root.document.body;
    var title = root.document.getElementById("auth-title");
    var message = root.document.getElementById("auth-message");
    var openApp = root.document.getElementById("open-app");
    var callbackBoundary = body.getAttribute("data-callback-url") || "";
    var appName = body.getAttribute("data-app-name") || "XTimers";
    var returnURL = buildReturnURL(root.location.href, callbackBoundary);

    if (!returnURL) {
      body.classList.add("invalid");
      title.textContent = "This sign-in link is incomplete";
      message.textContent = "Return to " + appName + " and start sign-in again.";
      return;
    }

    // Keep the one-time OAuth response out of browser history and screenshots.
    root.history.replaceState(null, root.document.title, root.location.pathname);
    openApp.href = returnURL;

    // No automatic redirect, by design. Auto-firing summons the browser's
    // own "Open <app>?" confirmation while this page is also showing its
    // button — two prompts for one action, and the page cannot detect the
    // browser's dialog to stay quiet around it (a visibility-based delay
    // misfires: the tab stays visible while the customer reads the dialog).
    // One visible action at a time instead: the customer clicks the single
    // button here, the browser confirms once, and after "always allow" the
    // whole handoff is that one click. A gesture-driven navigation is also
    // the one form browsers never swallow.
    var help = root.document.getElementById("auth-help");
    var retry = root.document.getElementById("retry-open");

    function returnToApp(event) {
      if (event) event.preventDefault();
      // Post-click the page's job is over: say DONE, retire the primary
      // button entirely (a big call-to-action makes "done" read as "open
      // the app"), and keep recovery as the help line's quiet text link —
      // the stripped one-time response means a reload could not retry.
      title.textContent = "Done — you can close this tab";
      message.textContent = appName + " is finishing your sign-in in the app.";
      openApp.hidden = true;
      if (help) help.hidden = false;
      root.location.assign(returnURL);
    }

    openApp.addEventListener("click", returnToApp);
    if (retry) retry.addEventListener("click", returnToApp);
    openApp.hidden = false;
  }

  if (root.document.readyState === "loading") {
    root.document.addEventListener("DOMContentLoaded", start, { once: true });
  } else {
    start();
  }
}(typeof window !== "undefined" ? window : globalThis));
