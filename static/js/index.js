$('.mailbox-select').multipleSelect();

$(".delete-email").on("click", function () {
  let alias = $(this).parent().find(".alias").val();
  let message = `Once <b>${alias}</b> is deleted, people/apps ` +
    "who used to contact you via this alias cannot reach you any more," +
    " please confirm.";
  let that = $(this);

  bootbox.confirm({
    message: message,
    buttons: {
      confirm: {
        label: 'Yes, delete it',
        className: 'btn-danger'
      },
      cancel: {
        label: 'Cancel',
        className: 'btn-outline-primary'
      }
    },
    callback: function (result) {
      if (result) {
        that.closest("form").submit();
      }
    }
  })


});

$(".enable-disable-alias").change(async function () {
  let aliasId = $(this).data("alias");
  let alias = $(this).data("alias-email");

  await disableAlias(aliasId, alias);
})

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
  } catch (e) {
    toastr.error("Sorry for the inconvenience! Could you refresh the page & retry please?", "Unknown Error");
    // reset to the original value
    $(this).prop("checked", oldValue);
  }
})

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
        toastr.success(`${alias} is added to favorite`);
      } else {
        toastr.info(`${alias} is removed from favorite`);
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
})

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
      toastr.success(`Note Saved`);
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

})

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

})

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

})


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