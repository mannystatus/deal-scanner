self.addEventListener("push", (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch (e) {
    data = {};
  }

  const title = data.title || "New deal on Hack the Deal";
  const options = {
    body: data.body || "",
    // data.icon (the deal's own thumbnail) wins when present so each
    // notification shows the actual product photo; our mark is the fallback.
    icon: data.icon || "/assets/notification-icon.png",
    // Android's status-bar badge only reads the alpha channel and tints it
    // solid, so this has to be a glyph-only silhouette, not the full-color icon.
    badge: "/assets/notification-badge.png",
    data: { url: data.url || "/" },
  };

  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || "/";
  event.waitUntil(clients.openWindow(url));
});
