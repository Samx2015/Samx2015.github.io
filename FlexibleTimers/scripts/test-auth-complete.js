"use strict";

var assert = require("assert");
var fs = require("fs");
var path = require("path");
var vm = require("vm");
var completion = require("../assets/flexible-timers/auth-complete.js");
var completionScriptPath = path.join(
  __dirname,
  "../assets/flexible-timers/auth-complete.js"
);
var completionScript = fs.readFileSync(completionScriptPath, "utf8");

function makeElement(initial) {
  var listeners = Object.create(null);
  return {
    textContent: initial && initial.textContent || "",
    href: initial && initial.href || "#",
    hidden: Boolean(initial && initial.hidden),
    listeners: listeners,
    addEventListener: function (type, listener) {
      listeners[type] = listener;
    }
  };
}

function runCompletionPage(options) {
  var classNames = [];
  var assignments = [];
  var historyCalls = [];
  var timeoutCalls = [];
  var elements = {
    "auth-title": makeElement({ textContent: "Return to " + options.appName }),
    "auth-message": makeElement(),
    "open-app": makeElement({ hidden: true }),
    "auth-help": makeElement({ hidden: true }),
    "retry-open": makeElement()
  };
  var document = {
    title: "Return to " + options.appName + " after Xin Account sign-in",
    readyState: "complete",
    body: {
      classList: {
        add: function (name) { classNames.push(name); }
      },
      getAttribute: function (name) {
        if (name === "data-callback-url") return options.callbackURL;
        if (name === "data-app-name") return options.appName;
        return null;
      }
    },
    getElementById: function (id) {
      return elements[id] || null;
    }
  };
  var root = {
    document: document,
    history: {
      replaceState: function (state, title, url) {
        historyCalls.push([state, title, url]);
      }
    },
    location: {
      href: options.pageURL,
      pathname: new URL(options.pageURL).pathname,
      assign: function (url) { assignments.push(url); }
    },
    setTimeout: function (callback, delay) {
      timeoutCalls.push([callback, delay]);
    }
  };

  vm.runInNewContext(completionScript, {
    window: root,
    URL: URL,
    URLSearchParams: URLSearchParams
  }, { filename: completionScriptPath });

  return {
    assignments: assignments,
    classNames: classNames,
    elements: elements,
    historyCalls: historyCalls,
    timeoutCalls: timeoutCalls
  };
}

function click(element) {
  var prevented = false;
  assert.strictEqual(typeof element.listeners.click, "function");
  element.listeners.click({
    preventDefault: function () { prevented = true; }
  });
  assert.strictEqual(prevented, true);
}

assert.strictEqual(
  completion.buildReturnURL(
    "https://xintechllc.com/XTimers/auth/complete.html?code=one%2Btime",
    "xtimers-auth://auth/callback"
  ),
  "xtimers-auth://auth/callback?code=one%2Btime"
);

assert.strictEqual(
  completion.buildReturnURL(
    "https://xintechllc.com/XTimers/auth/complete-pro.html?error=access_denied&error_description=Cancelled",
    "xtimers-pro-auth://auth/callback"
  ),
  "xtimers-pro-auth://auth/callback?error=access_denied&error_description=Cancelled"
);

assert.strictEqual(
  completion.buildReturnURL(
    "https://xintechllc.com/XTimers/auth/complete.html#access_token=legacy",
    "xtimers-auth://auth/callback"
  ),
  "xtimers-auth://auth/callback#access_token=legacy"
);

assert.strictEqual(
  completion.buildReturnURL(
    "https://xintechllc.com/XTimers/auth/complete.html",
    "xtimers-auth://auth/callback"
  ),
  null
);

assert.strictEqual(
  completion.buildReturnURL(
    "https://xintechllc.com/XTimers/auth/complete.html?code=redacted",
    "malicious-app://steal/callback"
  ),
  null
);

assert.strictEqual(
  completion.buildReturnURL(
    "https://xintechllc.com/XTimers/auth/complete.html?state=not-a-response",
    "xtimers-auth://auth/callback"
  ),
  null
);

[
  {
    appName: "XTimers",
    callbackURL: "xtimers-auth://auth/callback",
    pageURL: "https://xintechllc.com/XTimers/auth/complete.html?code=one%2Btime#state=kept",
    returnURL: "xtimers-auth://auth/callback?code=one%2Btime#state=kept",
    pathname: "/XTimers/auth/complete.html"
  },
  {
    appName: "XTimers Pro",
    callbackURL: "xtimers-pro-auth://auth/callback",
    pageURL: "https://xintechllc.com/XTimers/auth/complete-pro.html?error=access_denied&error_description=Cancelled",
    returnURL: "xtimers-pro-auth://auth/callback?error=access_denied&error_description=Cancelled",
    pathname: "/XTimers/auth/complete-pro.html"
  }
].forEach(function (consumer) {
  var page = runCompletionPage(consumer);
  var openApp = page.elements["open-app"];
  var help = page.elements["auth-help"];
  var retry = page.elements["retry-open"];

  assert.strictEqual(openApp.href, consumer.returnURL);
  assert.strictEqual(openApp.hidden, false);
  assert.deepStrictEqual(page.historyCalls, [
    [
      null,
      "Return to " + consumer.appName + " after Xin Account sign-in",
      consumer.pathname
    ]
  ]);
  assert.deepStrictEqual(page.timeoutCalls, []);
  assert.deepStrictEqual(page.assignments, []);

  click(openApp);
  assert.strictEqual(page.elements["auth-title"].textContent,
    "Signed in with your Xin Account");
  assert.strictEqual(page.elements["auth-message"].textContent,
    consumer.appName + " is finishing your Xin Account sign-in in the app.");
  assert.strictEqual(openApp.hidden, true);
  assert.strictEqual(help.hidden, false);
  assert.deepStrictEqual(page.assignments, [consumer.returnURL]);

  click(retry);
  assert.deepStrictEqual(page.assignments, [
    consumer.returnURL,
    consumer.returnURL
  ]);
});

var invalidPage = runCompletionPage({
  appName: "XTimers",
  callbackURL: "xtimers-auth://auth/callback",
  pageURL: "https://xintechllc.com/XTimers/auth/complete.html?state=not-a-response"
});
assert.deepStrictEqual(invalidPage.classNames, ["invalid"]);
assert.strictEqual(invalidPage.elements["auth-title"].textContent,
  "This Xin Account sign-in link is incomplete");
assert.strictEqual(invalidPage.elements["auth-message"].textContent,
  "Return to XTimers and start Xin Account sign-in again.");
assert.strictEqual(invalidPage.elements["open-app"].hidden, true);
assert.strictEqual(invalidPage.elements["open-app"].listeners.click, undefined);
assert.deepStrictEqual(invalidPage.historyCalls, []);
assert.deepStrictEqual(invalidPage.timeoutCalls, []);
assert.deepStrictEqual(invalidPage.assignments, []);

[
  {
    file: "complete.html",
    callbackURL: "xtimers-auth://auth/callback",
    appName: "XTimers"
  },
  {
    file: "complete-pro.html",
    callbackURL: "xtimers-pro-auth://auth/callback",
    appName: "XTimers Pro"
  }
].forEach(function (consumer) {
  var html = fs.readFileSync(
    path.join(__dirname, "../auth", consumer.file),
    "utf8"
  );
  assert.ok(html.indexOf(
    "data-callback-url=\"" + consumer.callbackURL
      + "\" data-app-name=\"" + consumer.appName + "\""
  ) !== -1);
  assert.ok(html.indexOf(">Return to " + consumer.appName + "</h1>") !== -1);
  assert.ok(html.indexOf(
    "Your Xin Account sign-in is ready. Select <strong>Open "
      + consumer.appName + "</strong> to return to " + consumer.appName + "."
  ) !== -1);
  assert.ok(html.indexOf(
    "Xin Account secure sign-in for " + consumer.appName
  ) !== -1);
  assert.ok(html.indexOf(
    "Your Xin Account sign-in response is sent only to the "
      + consumer.appName + " app on this Mac."
  ) !== -1);
  assert.ok(html.indexOf(">Open " + consumer.appName + "</a>") !== -1);
  assert.ok(html.indexOf(
    "If " + consumer.appName
      + " did not open, <a id=\"retry-open\" href=\"#\">try again</a>."
  ) !== -1);
});

console.log("OAuth completion page routing and click-handoff checks passed.");
