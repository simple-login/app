$('.mailbox-select').multipleSelect();

$(".enable-disable-alias").change(async function () {
  let aliasId = $(this).data("alias");
  let alias = $(this).data("alias-email");

  await disableAlias(aliasId, alias);
});

function getHeaders() {
  return {
    "Content-Type": "application/json",
    "X-Sl-Allowcookies": 'allow',
  }
}

async function disableAlias(aliasId, alias) {
  let oldValue;
  try {
    let res = await fetch(`/api/aliases/${aliasId}/toggle`, {
      method: "POST",
      headers: getHeaders()
    });

    if (res.ok) {
      let json = await res.json();

      if (json.enabled) {
        toastr.success(`${alias} is enabled`);
        $(`#send-email-${aliasId}`).removeClass("disabled");
      } else {
        toastr.success(`${alias} is disabled`);
        $(`#send-email-${aliasId}`).addClass("disabled");
      }
    } else {
      toastr.error("Sorry for the inconvenience! Could you refresh the page & retry please?", "Unknown Error");
      // reset to the original value
      oldValue = !$(this).prop("checked");
      $(this).prop("checked", oldValue);
    }
  } catch (e) {
    toastr.error("Sorry for the inconvenience! Could you refresh the page & retry please?", "Unknown Error");
    // reset to the original value
    oldValue = !$(this).prop("checked");
    $(this).prop("checked", oldValue);
  }
}

$(".enable-disable-pgp").change(async function (e) {
  let aliasId = $(this).data("alias");
  let alias = $(this).data("alias-email");
  const oldValue = !$(this).prop("checked");
  let newValue = !oldValue;

  try {
    let res = await fetch(`/api/aliases/${aliasId}`, {
      method: "PUT",
      headers: getHeaders(),
      body: JSON.stringify({
        disable_pgp: oldValue,
      }),
    });

    if (res.ok) {
      if (newValue) {
        toastr.success(`PGP is enabled for ${alias}`);
      } else {
        toastr.info(`PGP is disabled for ${alias}`);
      }
    } else {
      toastr.error("Sorry for the inconvenience! Could you refresh the page & retry please?", "Unknown Error");
      // reset to the original value
      $(this).prop("checked", oldValue);
    }
  } catch (err) {
    toastr.error("Sorry for the inconvenience! Could you refresh the page & retry please?", "Unknown Error");
    // reset to the original value
    $(this).prop("checked", oldValue);
  }
});

$(".pin-alias").change(async function () {
  let aliasId = $(this).data("alias");
  let alias = $(this).data("alias-email");
  const oldValue = !$(this).prop("checked");
  let newValue = !oldValue;

  try {
    let res = await fetch(`/api/aliases/${aliasId}`, {
      method: "PUT",
        headers: getHeaders(),
      body: JSON.stringify({
        pinned: newValue,
      }),
    });

    if (res.ok) {
      if (newValue) {
        toastr.success(`${alias} is pinned`);
      } else {
        toastr.info(`${alias} is unpinned`);
      }
    } else {
      toastr.error("Sorry for the inconvenience! Could you refresh the page & retry please?", "Unknown Error");
      // reset to the original value
      $(this).prop("checked", oldValue);
    }
  } catch (e) {
    toastr.error("Sorry for the inconvenience! Could you refresh the page & retry please?", "Unknown Error");
    // reset to the original value
    $(this).prop("checked", oldValue);
  }
});

async function handleNoteChange(aliasId, aliasEmail) {
  const note = document.getElementById(`note-${aliasId}`).value;

  try {
    let res = await fetch(`/api/aliases/${aliasId}`, {
      method: "PUT",
      headers: getHeaders(),
      body: JSON.stringify({
        note: note,
      }),
    });

    if (res.ok) {
      toastr.success(`Description saved for ${aliasEmail}`);
    } else {
      toastr.error("Sorry for the inconvenience! Could you refresh the page & retry please?", "Unknown Error");
    }
  } catch (e) {
    toastr.error("Sorry for the inconvenience! Could you refresh the page & retry please?", "Unknown Error");
  }

}

function handleNoteFocus(aliasId) {
  document.getElementById(`note-focus-message-${aliasId}`).classList.remove('d-none');
}

function handleNoteBlur(aliasId) {
  document.getElementById(`note-focus-message-${aliasId}`).classList.add('d-none');
}

async function handleMailboxChange(aliasId, aliasEmail) {
  const selectedOptions = document.getElementById(`mailbox-${aliasId}`).selectedOptions;
  const mailbox_ids = Array.from(selectedOptions).map((selectedOption) => selectedOption.value);

  if (mailbox_ids.length === 0) {
    toastr.error("You must select at least a mailbox", "Error");
    return;
  }

  try {
    let res = await fetch(`/api/aliases/${aliasId}`, {
      method: "PUT",
      headers: getHeaders(),
      body: JSON.stringify({
        mailbox_ids: mailbox_ids,
      }),
    });

    if (res.ok) {
      toastr.success(`Mailbox updated for ${aliasEmail}`);
    } else {
      toastr.error("Sorry for the inconvenience! Could you refresh the page & retry please?", "Unknown Error");
    }
  } catch (e) {
    toastr.error("Sorry for the inconvenience! Could you refresh the page & retry please?", "Unknown Error");
  }

}

async function handleDisplayNameChange(aliasId, aliasEmail) {
  const name = document.getElementById(`alias-name-${aliasId}`).value;

  try {
    let res = await fetch(`/api/aliases/${aliasId}`, {
      method: "PUT",
      headers: getHeaders(),
      body: JSON.stringify({
        name: name,
      }),
    });

    if (res.ok) {
      toastr.success(`Display name saved for ${aliasEmail}`);
    } else {
      toastr.error("Sorry for the inconvenience! Could you refresh the page & retry please?", "Unknown Error");
    }
  } catch (e) {
    toastr.error("Sorry for the inconvenience! Could you refresh the page & retry please?", "Unknown Error");
  }

}

function handleDisplayNameFocus(aliasId) {
  document.getElementById(`display-name-focus-message-${aliasId}`).classList.remove('d-none');
}

function handleDisplayNameBlur(aliasId) {
  document.getElementById(`display-name-focus-message-${aliasId}`).classList.add('d-none');
}

new Vue({
  el: '#filter-app',
  delimiters: ["[[", "]]"], // necessary to avoid conflict with jinja
  data: {
    showFilter: false,
    showStats: false
  },
  methods: {
    async toggleFilter() {
      let that = this;
      that.showFilter = !that.showFilter;
      store.set('showFilter', that.showFilter);
    },

    async toggleStats() {
      let that = this;
      that.showStats = !that.showStats;
      store.set('showStats', that.showStats);
    }
  },
  async mounted() {
    if (store.get("showFilter"))
      this.showFilter = true;

    if (store.get("showStats"))
      this.showStats = true;
  }
});
