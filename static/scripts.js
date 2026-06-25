function getCsrfToken() {
    return document.querySelector('meta[name="csrf-token"]').getAttribute('content');
}


// entity removal from character's inventory or spells function
window.remove_entity = function(character_id, item_id, custom_item_id, spell_id) {
    let formData = new FormData();
    formData.append("character_id", character_id);

    if(item_id !== null)
        formData.append("item_id", item_id);
    if(custom_item_id !== null)
        formData.append("custom_item_id", custom_item_id);
    if(spell_id !== null)
        formData.append("spell_id", spell_id);

    fetch("/entity/remove", {
        method: "POST",
        headers: {
            'X-CSRFToken': getCsrfToken()
        },
        body: formData,
        credentials: 'same-origin'
    })
    .then(res => res.json())
    .then(data => {
        if (data.success) {
            alert("Removed successfully!");
            location.reload();
        } else {
            alert("Error: " + data.error);
        }
    })
    .catch(err => {
        alert("Request failed: " + err);
    });
}


// add an entity to a character's inventory or spells
window.add_entity = function(character_id, select_id, entity_type) {
    const select = document.getElementById(select_id);
    const entity_id = select.value;

    if(!entity_id) {
        alert("Please select an item to add.");
        return;
    }

    fetch(`/entity/add/${character_id}`, {
        method: "POST",
        headers: {
            "Content-type": "application/json",
            'X-CSRFToken': getCsrfToken()
         },
        body: JSON.stringify({ entity_type: entity_type, entity_id: entity_id }),
        credentials: 'same-origin'
    })
    .then(response => response.json())
    .then(data => {
        if(data.status === "success") {
            alert("Added successfully!");
            location.reload();
        } else {
            alert("Error: " + data.message);
        }
    })
    .catch(error => console.error("Error:", error));
}


// update the health bar fill based on current/max HP
function updateHealthBarFill() {
  const currentElem = document.querySelector('.current_hp');
  const maxElem = document.querySelector('.max_hp');
  const fillElem = document.querySelector('.health-bar-fill');

  if (!currentElem || !maxElem || !fillElem) {
    return;
  }

  const current = parseInt(currentElem.innerText || currentElem.textContent, 10) || 0;
  const max = parseInt(maxElem.innerText || maxElem.textContent, 10) || 1;
  const ratio = Math.min(current / max, 1);
  const fill = ratio * 100;

  fillElem.style.width = `${fill}%`;

  if (ratio > 0.5) {
    fillElem.style.backgroundColor = getComputedStyle(document.documentElement).getPropertyValue('--accent-neon').trim() || '#d33';
    fillElem.classList.remove('low-health');
  } else if (ratio > 0.25) {
    fillElem.style.backgroundColor = '#d67b33';
    fillElem.classList.remove('low-health');
  } else {
    fillElem.style.backgroundColor = '#851515';
    fillElem.classList.add('low-health');
  }
}


function formatDateTime(value) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
        return value;
    }

    return new Intl.DateTimeFormat("en-GB", {
        year: "numeric",
        month: "short",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
    }).format(date);
}


// character's sheet update function
window.send_update = function(span) {
    const field = span.dataset.field;
    const value = span.innerText.trim();
    const char_id = span.dataset.id;

    const positiveIntFields = new Set([
        "strength", "dexterity", "constitution",
        "intelligence", "wisdom", "charisma",
        "hit_points", "max_hit_points", "temp_hp",
        "level", "xp"
    ]);

    if (positiveIntFields.has(field)) {
        if (!/^\d+$/.test(value)) {
            alert(`Please enter a valid non-negative integer for ${field.toUpperCase()}.`);
            span.innerText = span.dataset.lastValid;
            span.focus();
            return;
        }
    }

    fetch(`/api/characters/${char_id}/update`, {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            'X-CSRFToken': getCsrfToken()
         },
        body: JSON.stringify({ field: field, value: value }),
        credentials: 'same-origin'
    })
    .then(res => res.json())
    .then(data => {
        if(data.status === "success") {
            span.classList.add("edit-success");
            span.dataset.lastValid = value;
            setTimeout(() => span.classList.remove("edit-success"), 1000);
        } else {
            alert("Error: " + data.message);
            span.innerText = span.dataset.lastValid;
            span.focus();
        }
    })
    .catch(err => {
        console.error("Update failed:", err);
        span.innerText = span.dataset.lastValid;
        span.focus();
    });
}
  // gets last valid field value
document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("[contenteditable][data-field]").forEach(span => {
    span.dataset.lastValid = span.innerText.trim();

    span.addEventListener("blur", () => send_update(span));
    if (span.classList.contains("current_hp") || span.classList.contains("max_hp")) {
      span.addEventListener("input", () => updateHealthBarFill());
    }
    span.addEventListener("keydown", e => {
      if (e.key === "Enter") {
        e.preventDefault();
        span.blur();
      }
    });
  });

  // hp adjust buttons
  document.querySelectorAll(".adjust-btn").forEach(button => {
    button.addEventListener("click", () => {
      const change = parseInt(button.dataset.change);
      const currentSpan = document.querySelector(".current_hp");
      let current = parseInt(currentSpan.innerText.trim()) || 0;
      const max = parseInt(document.querySelector(".max_hp").innerText.trim()) || 1;

      current = Math.max(0, Math.min(current + change, max));
      currentSpan.innerText = current;
      updateHealthBarFill();
      send_update(currentSpan);
    });
  });

  // health bar fill
  updateHealthBarFill();
});



// update a given campaign's dice roll log
document.addEventListener("DOMContentLoaded", () => {
    const campaignData = document.getElementById("campaign-data");
    if (!campaignData) return;

    const campaignId = campaignData.dataset.campaignId;
    let lastRendered = "";

    function fetchDiceLogs() {
        fetch(`/campaign/${campaignId}/dice_logs`, {
            headers: {
            'X-CSRFToken': getCsrfToken()
        },
        credentials: 'same-origin'
        })
            .then(res => res.json())
            .then(data => {
                const logContainer = document.getElementById("dice-log-container");
                if (!logContainer) return;

                const newRendered = JSON.stringify(data);
                if (newRendered === lastRendered) return;

                lastRendered = newRendered;
                logContainer.innerHTML = "";

                data.forEach(roll => {
                    const card = document.createElement("div");
                    card.classList.add("card");

                    card.innerHTML = `
                        <p>${roll.name}</p>
                        <p>${roll.roll_result}</p>
                        <small>Created at: ${formatDateTime(roll.created_at)}</small>
                    `;

                    logContainer.appendChild(card);
                });

                // Scroll to bottom after updating log
                logContainer.scrollTo({ top: logContainer.scrollHeight, behavior: 'smooth' });
            })
            .catch(err => console.error("Failed to fetch logs", err));
    }

    window.fetchDiceLogs = fetchDiceLogs;

    setInterval(fetchDiceLogs, 5000);
    fetchDiceLogs();
});


// allows players on a campaign to roll up to 100d999 with modifiers
window.rollDice = function({ campaignId, characterId, formula, displayName }) {
    fetch("/roll_dice", {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            'X-CSRFToken': getCsrfToken()
         },
        body: JSON.stringify({ campaign_id: campaignId, character_id: characterId, formula, display_name: displayName }),
        credentials: 'same-origin'
    })
    .then(res => res.json())
    .then(data => {
        if (data.error) {
            alert(data.error);
            return;
        }

        const resultBox = document.getElementById("dice-result");
        const displayLabel = data.display_name || displayName || data.name;
        if (resultBox) {
            resultBox.innerHTML = `<p>${displayLabel}</p> rolled: <strong>${data.roll_result}</strong>`;
        }

        if (typeof window.fetchDiceLogs === "function") window.fetchDiceLogs();
    })
    .catch(err => {
        console.error("Dice roll failed", err);
        alert("Dice roll failed");
    });
}


// password visibility toggle
document.addEventListener("DOMContentLoaded", function () {
    // New button-based toggles (supports one or multiple target inputs)
    const toggleButtons = document.querySelectorAll(".password-toggle");
    toggleButtons.forEach((button) => {
        const targetIds = (button.dataset.togglePassword || "")
            .split(",")
            .map((id) => id.trim())
            .filter(Boolean);
        const showText = button.dataset.showText || "Show";
        const hideText = button.dataset.hideText || "Hide";

        const targets = targetIds
            .map((id) => document.getElementById(id))
            .filter(Boolean);

        if (!targets.length) {
            return;
        }

        const setVisibility = (shouldShow) => {
            targets.forEach((input) => {
                input.type = shouldShow ? "text" : "password";
            });
            button.textContent = shouldShow ? hideText : showText;
            button.setAttribute("aria-pressed", shouldShow ? "true" : "false");
        };

        setVisibility(false);
        button.addEventListener("click", () => {
            const shouldShow = targets.some((input) => input.type === "password");
            setVisibility(shouldShow);
        });
    });

    // Backward compatibility if old checkbox still exists in any template
    const legacyToggle = document.getElementById("togglePassword");
    const password = document.getElementById("password");
    const confirmation = document.getElementById("confirmation");
    if (legacyToggle && legacyToggle.type === "checkbox") {
        legacyToggle.addEventListener("change", function () {
            const type = legacyToggle.checked ? "text" : "password";
            if (password) password.type = type;
            if (confirmation) confirmation.type = type;
        });
    }
});
