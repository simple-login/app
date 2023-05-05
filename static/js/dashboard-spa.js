new Vue({
  el: '#dashboard-app',
  delimiters: ["[[", "]]"], // necessary to avoid conflict with jinja
  data: {
    showFilter: false,
    showStats: false,

    mailboxes: [],

    // variables for aliases list
    isFetchingAlias: true,
    aliasesArray: [], // array of existing alias
    aliasesArrayOfNextPage: [], // to know there is a next page if not empty
    page: 0,
    isLoadingMoreAliases: false,
    searchString: "",
    filter: "", // TODO add more filters and also sorting when backend API is ready
  },
  computed: {
    isLastPage: function () {
      return this.aliasesArrayOfNextPage.length === 0;
    },
  },
  async mounted() {

    if (store.get("showFilter")) {
      this.showFilter = true;
    }

    if (store.get("showStats")) {
      this.showStats = true;
    }

    await this.loadInitialData();

  },
  methods: {
    // initialize mailboxes and aliases
    async loadInitialData() {
      await this.loadMailboxes();
      await this.loadAliases();
    },

    async loadMailboxes() {
      try {
        const res = await fetch("/api/mailboxes");
        if (res.ok) {
          const result = await res.json();
          this.mailboxes = result.mailboxes;
        } else {
          throw new Error("Could not load mailboxes");
        }
      } catch (e) {
        toastr.error("Sorry for the inconvenience! Could you try refreshing the page? ", "Could not load mailboxes");
      }
    },

    async loadAliases() {
      this.aliasesArray = [];
      this.page = 0;

      this.aliasesArray = await this.fetchAlias(this.page, this.searchString);
      this.aliasesArrayOfNextPage = await this.fetchAlias(this.page + 1, this.searchString);

      // use jquery multiple select plugin after Vue has rendered the aliases in the DOM
      this.$nextTick(() => {
        $('.mailbox-select').multipleSelect();
        $('.mailbox-select').removeClass('mailbox-select');
      })
    },

    async fetchAlias(page, query) {
      this.isFetchingAlias = true;
      try {
        const res = await fetch(`/api/v2/aliases?page_id=${page}&${this.filter}`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          ...(query && { body: JSON.stringify({ query }) }),
        });
        if (res.ok) {
          const result = await res.json();
          this.isFetchingAlias = false;
          return result.aliases;
        } else {
          throw new Error("Aliases could not be loaded");
        }
      } catch (e) {
        toastr.error("Sorry for the inconvenience! Could you try refreshing the page? ", "Aliases could not be loaded");
        this.isFetchingAlias = false;
        return [];
      }
    },

    async toggleFilter() {
      this.showFilter = !this.showFilter;
      store.set('showFilter', this.showFilter);
    },

    async toggleStats() {
      this.showStats = !this.showStats;
      store.set('showStats', this.showStats);
    },

    async toggleAlias(alias) {
      try {
        const res = await fetch(`/api/aliases/${alias.id}/toggle`, {
          method: "POST",
        });

        if (res.ok) {
          const result = await res.json();
          alias.enabled = result.enabled;
          toastr.success(`${alias.email} is ${alias.enabled ? "enabled" : "disabled"}`);
        } else {
          throw new Error("Could not disable/enable alias");
        }

      } catch (e) {
        alias.enabled = !alias.enabled;
        toastr.error("Sorry for the inconvenience! Could you refresh the page & retry please?", "Could not disable/enable alias");
      }
    },

    async handleNoteChange(alias) {
      try {
        const res = await fetch(`/api/aliases/${alias.id}`, {
          method: "PUT",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            note: alias.note,
          }),
        });

        if (res.ok) {
          toastr.success(`Description saved for ${alias.email}`);
        } else {
          throw new Error("Could not save alias description");
        }

      } catch (e) {
        toastr.error("Sorry for the inconvenience! Could you refresh the page & retry please?", "Could not save alias description");
      }
    },

    async handleDisplayNameChange(alias) {
      try {
        let res = await fetch(`/api/aliases/${alias.id}`, {
          method: "PUT",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            name: alias.name,
          }),
        });

        if (res.ok) {
          toastr.success(`Display name saved for ${alias.email}`);
        } else {
          throw new Error("Could not save Display name");
        }

      } catch (e) {
        toastr.error("Sorry for the inconvenience! Could you refresh the page & retry please?", "Could not save Display name")
      }

    },

    async handlePgpToggle(alias) {
      try {
        let res = await fetch(`/api/aliases/${alias.id}`, {
          method: "PUT",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            disable_pgp: alias.disable_pgp,
          }),
        });

        if (res.ok) {
          toastr.success(`PGP ${alias.disable_pgp ? "disabled" : "enabled"} for ${alias.email}`);
        } else {
          throw new Error("Could not toggle PGP")
        }

      } catch (err) {
        alias.disable_pgp = !alias.disable_pgp;
        toastr.error("Sorry for the inconvenience! Could you refresh the page & retry please?", "Could not toggle PGP");
      }
    },

    async handlePin(alias) {
      try {
        let res = await fetch(`/api/aliases/${alias.id}`, {
          method: "PUT",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            pinned: !alias.pinned,
          }),
        });

        if (res.ok) {
          alias.pinned = !alias.pinned;
          if (alias.pinned) {
            // make alias appear at the top of the alias list
            const index = this.aliasesArray.findIndex((a) => a.id === alias.id);
            this.aliasesArray.splice(index, 1);
            this.aliasesArray.unshift(alias);
            toastr.success(`${alias.email} is pinned`);
          } else {
            // unpin: make alias appear at the bottom of the alias list
            const index = this.aliasesArray.findIndex((a) => a.id === alias.id);
            this.aliasesArray.splice(index, 1);
            this.aliasesArray.push(alias);
            toastr.success(`${alias.email} is unpinned`);
          }
        } else {
          throw new Error("Alias could not be pinned");
        }

      } catch (err) {
        toastr.error("Sorry for the inconvenience! Could you refresh the page & retry please?", "Alias could not be pinned");
      }
    },


    async handleDeleteAliasClick(alias, aliasDomainTrashUrl) {

      let message = `If you don't want to receive emails from this alias, you can disable it. Please note that once deleted, it <b>can't</b> be restored.`;
      if (aliasDomainTrashUrl !== undefined) {
        message = `If you want to stop receiving emails from this alias, you can disable it instead. When it's deleted, it's moved to the domain
    <a href="${aliasDomainTrashUrl}">trash</a>`;
      }

      const that = this;
      bootbox.dialog({
        title: `Delete alias ${alias.email}?`,
        message: message,
        onEscape: true,
        backdrop: true,
        centerVertical: true,
        buttons: {
          // show disable button only if alias is enabled
          ...(alias.enabled ? {
            disable: {
              label: 'Disable it',
              className: 'btn-primary',
              callback: function () {
                that.disableAlias(alias);
              }
            }
          } : {}),

          delete: {
            label: "Delete it, I don't need it anymore",
            className: 'btn-danger',
            callback: function () {
              that.deleteAlias(alias);
            }
          },

          cancel: {
            label: 'Cancel',
            className: 'btn-outline-primary'
          },

        }
      });
    },

    async deleteAlias(alias) {
      try {
        let res = await fetch(`/api/aliases/${alias.id}`, {
          method: "DELETE",
          headers: {
            "Content-Type": "application/json",
          },
        });

        if (res.ok) {
          toastr.success(`Alias ${alias.email} deleted`);
          this.aliasesArray = this.aliasesArray.filter((a) => a.id !== alias.id);
        } else {
          throw new Error("Alias could not be deleted");
        }

      } catch (err) {
        toastr.error("Sorry for the inconvenience! Could you refresh the page & retry please?", "Alias could not be deleted");
      }
    },

    async disableAlias(alias) {
      try {
        if (alias.enabled === false) {
          return;
        }
        let res = await fetch(`/api/aliases/${alias.id}/toggle`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            alias_id: alias.id,
          }),
        });

        if (res.ok) {
          alias.enabled = false;
          toastr.success(`${alias.email} is disabled`);
        } else {
          throw new Error("Alias could not be disabled");
        }

      } catch (err) {
        toastr.error("Sorry for the inconvenience! Could you refresh the page & retry please?", "Alias could not be disabled");
      }
    },

    // merge newAliases into currentAliases. If conflict, keep the new one
    mergeAliases(currentAliases, newAliases) {
      // dict of aliasId and alias to speed up research
      let newAliasesDict = {};
      for (let i = 0; i < newAliases.length; i++) {
        let alias = newAliases[i];
        newAliasesDict[alias.id] = alias;
      }

      let ret = [];

      // keep track of added aliases
      let alreadyAddedId = {};
      for (let i = 0; i < currentAliases.length; i++) {
        let alias = currentAliases[i];
        if (newAliasesDict[alias.id]) ret.push(newAliasesDict[alias.id]);
        else ret.push(alias);

        alreadyAddedId[alias.id] = true;
      }

      for (let i = 0; i < newAliases.length; i++) {
        let alias = newAliases[i];
        if (!alreadyAddedId[alias.id]) {
          ret.push(alias);
        }
      }

      return ret;
    },

    async loadMoreAliases() {
      this.isLoadingMoreAliases = true;
      this.page++;

      // we already fetched aliases of the next page, just merge it
      this.aliasesArray = this.mergeAliases(this.aliasesArray, this.aliasesArrayOfNextPage);

      // fetch next page in advance to know if there is a next page
      this.aliasesArrayOfNextPage = await this.fetchAlias(this.page + 1, this.searchString);

      // use jquery multiple select plugin after Vue has rendered the aliases in the DOM
      this.$nextTick(() => {
        $('.mailbox-select').multipleSelect();
        $('.mailbox-select').removeClass('mailbox-select');
      })

      this.isLoadingMoreAliases = false;
    },

    resetFilter() {
      this.searchString = "";
      this.filter = "";
      this.loadAliases();
    },

  }
});

async function handleMailboxChange(event) {
  aliasId = event.target.dataset.aliasId;
  aliasEmail = event.target.dataset.aliasEmail;
  const selectedOptions = event.target.selectedOptions;
  const mailbox_ids = Array.from(selectedOptions).map((selectedOption) => selectedOption.value);

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
      toastr.success(`Mailbox updated for ${aliasEmail}`);
    } else {
      throw new Error("Mailbox could not be updated");
    }
  } catch (e) {
    toastr.error("Sorry for the inconvenience! Could you refresh the page & retry please?", "Mailbox could not be updated");
  }

}
