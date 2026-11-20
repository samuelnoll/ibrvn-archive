(() => {
  if (navigator.doNotTrack === "1" || navigator.globalPrivacyControl === true) return

  const randomId = () => {
    if (crypto.randomUUID) return crypto.randomUUID()
    return `${Date.now()}-${Math.random().toString(16).slice(2)}-${Math.random().toString(16).slice(2)}`
  }

  const storedId = (storageProvider, key) => {
    try {
      const storage = storageProvider()
      let value = storage.getItem(key)
      if (!value) {
        value = randomId()
        storage.setItem(key, value)
      }
      return value
    } catch (_error) {
      return randomId()
    }
  }

  const visitorId = storedId(() => window.localStorage, "ibrvn_analytics_visitor")
  const sessionId = storedId(() => window.sessionStorage, "ibrvn_analytics_session")
  const queue = []
  let flushTimer

  const flush = useBeacon => {
    if (!queue.length) return
    const events = queue.splice(0, 50)
    const body = JSON.stringify({visitor_id: visitorId, session_id: sessionId, events})

    if (useBeacon && navigator.sendBeacon) {
      const sent = navigator.sendBeacon(
        "/api/analytics/events",
        new Blob([body], {type: "application/json"}),
      )
      if (sent) return
    }

    fetch("/api/analytics/events", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body,
      credentials: "same-origin",
      keepalive: true,
    }).catch(() => {})
  }

  const scheduleFlush = () => {
    clearTimeout(flushTimer)
    flushTimer = setTimeout(() => flush(false), 3000)
  }

  const track = event => {
    queue.push({
      event_id: randomId(),
      page_path: window.location.pathname,
      ...event,
    })
    if (queue.length >= 10) flush(false)
    else scheduleFlush()
  }

  window.IBRVNAnalytics = {track, flush}

  document.addEventListener("DOMContentLoaded", () => {
    if (!window.location.pathname.startsWith("/analytics") && !window.location.pathname.startsWith("/quality")) {
      track({event_type: "page_view", referrer: document.referrer})
    }

    document.addEventListener("click", event => {
      const link = event.target.closest("[data-analytics-event]")
      if (!link) return
      track({
        event_type: link.dataset.analyticsEvent,
        content_type: link.dataset.contentType || "",
        content_id: link.dataset.contentId || "",
        resource_id: link.dataset.resourceId || "",
      })
    })
  })

  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") flush(true)
  })
  window.addEventListener("pagehide", () => flush(true))
})()
