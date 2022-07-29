$('.mailbox-select').multipleSelect();

function confirmDeleteAlias() {
  let that = $(this);
  let alias = that.data("alias-email");
  let aliasDomainTrashUrl = that.data("custom-domain-trash-url");

  let message = `Maybe you want to disable the alias instead? Please note once deleted, it <b>can't</b> be restored.`;
  if (aliasDomainTrashUrl !== undefined) {
    message = `Maybe you want to disable the alias instead? When it's deleted, it's moved to the domain
    <a href="${aliasDomainTrashUrl}">trash</a>`;
  }

  bootbox.dialog({
    title: `Delete ${alias}`,
    message: message,
    size: 'large',
    onEscape: true,
    backdrop: true,
    buttons: {
      disable: {
        label: 'Disable it',
        className: 'btn-primary',
        callback: function () {
          that.closest("form").find('input[name="form-name"]').val("disable-alias");
          that.closest("form").submit();
        }
      },

      delete: {
        label: "Delete it, I don't need it anymore",
        className: 'btn-outline-danger',
        callback: function () {
          that.closest("form").submit();
        }
      },

      cancel: {
        label: 'Cancel',
        className: 'btn-outline-primary'
      },

    }
  });
}

$(".enable-disable-alias").change(async function () {
  let aliasId = $(this).data("alias");
  let alias = $(this).data("alias-email");

  await disableAlias(aliasId, alias);
});

async function disableAlias(aliasId, alias) {
  let oldValue;
  try {
    let res = await fetch(`/api/aliases/${aliasId}/toggle`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      }
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
      headers: {
        "Content-Type": "application/json",
      },
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
      headers: {
        "Content-Type": "application/json",
      },
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

$(".save-note").on("click", async function () {
  let oldValue;
  let aliasId = $(this).data("alias");
  let note = $(`#note-${aliasId}`).val();

  try {
    let res = await fetch(`/api/aliases/${aliasId}`, {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        note: note,
      }),
    });

    if (res.ok) {
      toastr.success(`Saved`);
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

});

$(".save-mailbox").on("click", async function () {
  let oldValue;
  let aliasId = $(this).data("alias");
  let mailbox_ids = $(`#mailbox-${aliasId}`).val();

  if (mailbox_ids.length === 0) {
    toastr.error("You must select at least a mailbox", "Error");
    return;
  }

  try {
    let res = await fetch(`/api/aliases/${aliasId}`, {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        mailbox_ids: mailbox_ids,
      }),
    });

    if (res.ok) {
      toastr.success(`Mailbox Updated`);
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

});

$(".save-alias-name").on("click", async function () {
  let aliasId = $(this).data("alias");
  let name = $(`#alias-name-${aliasId}`).val();

  try {
    let res = await fetch(`/api/aliases/${aliasId}`, {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        name: name,
      }),
    });

    if (res.ok) {
      toastr.success(`Alias Name Saved`);
    } else {
      toastr.error("Sorry for the inconvenience! Could you refresh the page & retry please?", "Unknown Error");
    }
  } catch (e) {
    toastr.error("Sorry for the inconvenience! Could you refresh the page & retry please?", "Unknown Error");
  }

});


new Vue({
  el: '#filter-app',
  delimiters: ["[[", "]]"], // necessary to avoid conflict with jinja
  data: {
    showFilter: false
  },
  methods: {
    async toggleFilter() {
      let that = this;
      that.showFilter = !that.showFilter;
      store.set('showFilter', that.showFilter);
    }
  },
  async mounted() {
    if (store.get("showFilter"))
      this.showFilter = true;
  }
});