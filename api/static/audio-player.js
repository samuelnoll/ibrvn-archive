(() => {
  const formatTime = value => {
    if (!Number.isFinite(value)) return "--:--"

    const totalSeconds = Math.max(0, Math.floor(value))
    const minutes = Math.floor(totalSeconds / 60)
    const seconds = String(totalSeconds % 60).padStart(2, "0")
    return `${minutes}:${seconds}`
  }

  const setIcon = (button, iconName) => {
    const use = button.querySelector("use")
    if (use) use.setAttribute("href", `#icon-${iconName}`)
  }

  const updateRangeFill = input => {
    const min = Number(input.min) || 0
    const max = Number(input.max) || 100
    const value = Number(input.value) || 0
    const percentage = max > min ? ((value - min) / (max - min)) * 100 : 0
    input.style.setProperty("--range-progress", `${percentage}%`)
  }

  const initializePlayer = player => {
    if (player.dataset.initialized) return
    player.dataset.initialized = "true"

    const audio = player.querySelector("audio")
    const toggle = player.querySelector(".sermon-player-toggle")
    const progress = player.querySelector(".sermon-player-progress")
    const time = player.querySelector(".sermon-player-time")
    const mute = player.querySelector(".sermon-player-mute")
    const volume = player.querySelector(".sermon-player-volume")
    const speedControl = player.querySelector(".sermon-player-speed-control")
    const speedToggle = player.querySelector(".sermon-player-speed-toggle")
    const speedLabel = player.querySelector(".sermon-player-speed-label")
    const speedMenu = player.querySelector(".sermon-player-speed-menu")
    const speedOptions = player.querySelectorAll("[data-playback-rate]")

    const closeSpeedMenu = () => {
      speedMenu.hidden = true
      speedToggle.setAttribute("aria-expanded", "false")
    }

    const updateTime = () => {
      time.textContent = `${formatTime(audio.currentTime)} / ${formatTime(audio.duration)}`
      progress.value = audio.duration
        ? String((audio.currentTime / audio.duration) * 100)
        : "0"
      updateRangeFill(progress)
    }

    const updateVolume = () => {
      volume.value = String(audio.muted ? 0 : audio.volume)
      setIcon(mute, audio.muted || audio.volume === 0 ? "volume-off" : "volume")
      mute.setAttribute(
        "aria-label",
        audio.muted || audio.volume === 0 ? "Ativar som" : "Silenciar \u00e1udio",
      )
      updateRangeFill(volume)
    }

    toggle.addEventListener("click", async () => {
      if (audio.paused) {
        document.querySelectorAll("[data-audio-player] audio").forEach(other => {
          if (other !== audio) other.pause()
        })

        try {
          await audio.play()
        } catch (error) {
          return
        }
      } else {
        audio.pause()
      }
    })

    progress.addEventListener("input", () => {
      if (audio.duration) {
        audio.currentTime = (Number(progress.value) / 100) * audio.duration
      }
      updateRangeFill(progress)
    })

    volume.addEventListener("input", () => {
      audio.muted = false
      audio.volume = Number(volume.value)
      updateVolume()
    })

    mute.addEventListener("click", () => {
      audio.muted = !audio.muted
      updateVolume()
    })

    speedToggle.addEventListener("click", () => {
      const willOpen = speedMenu.hidden

      document.querySelectorAll(".sermon-player-speed-menu").forEach(menu => {
        menu.hidden = true
        menu.parentElement
          ?.querySelector(".sermon-player-speed-toggle")
          ?.setAttribute("aria-expanded", "false")
      })

      speedMenu.hidden = !willOpen
      speedToggle.setAttribute("aria-expanded", String(willOpen))
    })

    speedOptions.forEach(option => {
      option.addEventListener("click", () => {
        const playbackRate = Number(option.dataset.playbackRate)
        audio.playbackRate = playbackRate
        speedLabel.textContent = option.textContent
        speedOptions.forEach(item => {
          item.setAttribute("aria-checked", String(item === option))
        })
        closeSpeedMenu()
        speedToggle.focus()
      })
    })

    speedControl.addEventListener("keydown", event => {
      if (event.key === "Escape") {
        closeSpeedMenu()
        speedToggle.focus()
      }
    })

    audio.addEventListener("play", () => {
      player.classList.add("is-started", "is-playing")
      toggle.setAttribute("aria-label", "Pausar \u00e1udio")
      setIcon(toggle, "pause")
    })

    audio.addEventListener("pause", () => {
      player.classList.remove("is-playing")
      toggle.setAttribute("aria-label", "Reproduzir \u00e1udio")
      setIcon(toggle, "play")
    })

    audio.addEventListener("ended", () => {
      audio.currentTime = 0
      updateTime()
    })
    audio.addEventListener("loadedmetadata", updateTime)
    audio.addEventListener("durationchange", updateTime)
    audio.addEventListener("timeupdate", updateTime)
    audio.addEventListener("volumechange", updateVolume)

    updateRangeFill(progress)
    updateVolume()
  }

  const initializeWithin = root => {
    if (root.matches?.("[data-audio-player]")) initializePlayer(root)
    root.querySelectorAll?.("[data-audio-player]").forEach(initializePlayer)
  }

  document.addEventListener("DOMContentLoaded", () => {
    initializeWithin(document)

    document.addEventListener("click", event => {
      document.querySelectorAll(".sermon-player-speed-control").forEach(control => {
        if (control.contains(event.target)) return

        const menu = control.querySelector(".sermon-player-speed-menu")
        const toggle = control.querySelector(".sermon-player-speed-toggle")
        menu.hidden = true
        toggle.setAttribute("aria-expanded", "false")
      })
    })

    new MutationObserver(mutations => {
      mutations.forEach(mutation => {
        mutation.addedNodes.forEach(node => {
          if (node.nodeType === Node.ELEMENT_NODE) initializeWithin(node)
        })
      })
    }).observe(document.body, {childList: true, subtree: true})
  })
})()
