## API

[Account endpoints](#account-endpoints)
- [POST /api/auth/login](#post-apiauthlogin): Authentication
- [POST /api/auth/mfa](#post-apiauthmfa): 2FA authentication
- [POST /api/auth/facebook](#post-apiauthfacebook) (deprecated)
- [POST /api/auth/google](#post-apiauthgoogle) (deprecated)
- [POST /api/auth/register](#post-apiauthregister): Register a new account.
- [POST /api/auth/activate](#post-apiauthactivate): Activate new account.
- [POST /api/auth/reactivate](##post-apiauthreactivate): Request a new activation code.
- [POST /api/auth/forgot_password](#post-apiauthforgot_password): Request reset password link.
- [GET /api/user_info](#get-apiuser_info): Get user's information.
- [PATCH /api/sudo](#patch-apisudo): Enable sudo mode.
- [DELETE /api/user](#delete-apiuser): Delete the current user.
- [GET /api/user/cookie_token](#get-apiusercookie_token): Get a one time use token to exchange it for a valid cookie
- [PATCH /api/user_info](#patch-apiuser_info): Update user's information.
- [POST /api/api_key](#post-apiapi_key): Create a new API key.
- [GET /api/logout](#get-apilogout): Log out.

[Alias endpoints](#alias-endpoints)
- [GET /api/v5/alias/options](#get-apiv5aliasoptions): Get alias options. Used by create alias process.
- [POST /api/v3/alias/custom/new](#post-apiv3aliascustomnew): Create new alias.
- [POST /api/alias/random/new](#post-apialiasrandomnew): Random an alias.
- [GET /api/v2/aliases](#get-apiv2aliases): Get user's aliases.
- [GET /api/aliases/:alias_id](#get-apialiasesalias_id): Get alias information.
- [DELETE /api/aliases/:alias_id](#delete-apialiasesalias_id): Delete an alias.
- [POST /api/aliases/:alias_id/toggle](#post-apialiasesalias_idtoggle): Enable/disable an alias.
- [GET /api/aliases/:alias_id/activities](#get-apialiasesalias_idactivities): Get alias activities.
- [PATCH /api/aliases/:alias_id](#patch-apialiasesalias_id): Update alias information.
- [GET /api/aliases/:alias_id/contacts](#get-apialiasesalias_idcontacts): Get alias contacts.
- [POST /api/aliases/:alias_id/contacts](#post-apialiasesalias_idcontacts): Create a new contact for an alias.

[Mailbox endpoints](#mailbox-endpoints)
- [POST /api/mailboxes](#post-apimailboxes): Create a new mailbox.
- [DELETE /api/mailboxes/:mailbox_id](#delete-apimailboxesmailbox_id): Delete a mailbox.
- [PUT /api/mailboxes/:mailbox_id](#put-apimailboxesmailbox_id): Update a mailbox.

[Custom domain endpoints](#custom-domain-endpoints)
- [GET /api/custom_domains](#get-apicustom_domains): Get custom domains.
- [PATCH /api/custom_domains/:custom_domain_id](#patch-apicustom_domainscustom_domain_id): Update custom domain's information.
- [GET /api/custom_domains/:custom_domain_id/trash](#get-apicustom_domainscustom_domain_idtrash): Get deleted aliases of a custom domain.

[Contact endpoints](#contact-endpoints)
- [DELETE /api/contacts/:contact_id](#delete-apicontactscontact_id): Delete a contact.
- [POST /api/contacts/:contact_id/toggle](#post-apicontactscontact_idtoggle): Block/unblock a contact.

[Notification endpoints](#notification-endpoints)
- [GET /api/notifications](#get-apinotifications): Get notifications.
- [POST /api/notifications/:notification_id](#post-apinotificationsnotification_id): Mark as read a notification.

[Settings endpoints](#settings-endpoints)
- [GET /api/setting](#get-apisetting): Get user's settings.
- [PATCH /api/setting](#patch-apisetting): Update user's settings.
- [GET /api/v2/setting/domains](#get-apiv2settingdomains): Get domains that user can use to create random alias.

[Import and export endpoints](#import-and-export-endpoints)
- [GET /api/export/data](#get-apiexportdata): Export user's data.
- [GET /api/export/aliases](#get-apiexportaliases): Export aliases into a CSV.

[MISC endpoints](#misc-endpoints)
- [POST /api/apple/process_payment](#post-apiappleprocess_payment): Process Apple's receipt.

[Phone endpoints](#phone-endpoints)
- [GET /api/phone/reservations/:reservation_id](#get-apiphonereservationsreservation_id): Get messages received during a reservation.

---

SimpleLogin current API clients are Chrome/Firefox/Safari extension and mobile (iOS/Android) app. These clients rely
on `API Code` for authentication.

Once the `Api Code` is obtained, either via user entering it (in Browser extension case) or by logging in (in Mobile
case), the client includes the `api code` in `Authentication` header in almost all requests.

For some endpoints, the `hostname` should be passed in query string. `hostname` is the the URL hostname (
cf https://en.wikipedia.org/wiki/URL), for ex if URL is http://www.example.com/index.html then the hostname
is `www.example.com`. This information is important to know where an alias is used in order to suggest user the same
alias if they want to create on alias on the same website in the future.

If error, the API returns 4** with body containing the error message, for example:

```json
{
  "error": "request body cannot be empty"
}
```

The error message could be displayed to user as-is, for example for when user exceeds their alias quota. Some errors
should be fixed during development however: for example error like `request body cannot be empty` is there to catch
development error and should never be shown to user.

All following endpoint return `401` status code if the API Key is incorrect.

### Account endpoints

#### POST /api/auth/login

Input:

- email
- password
- device: device name. Used to create the API Key. Should be humanly readable so user can manage later on the "API Key"
  page.

Output:

- name: user name, could be an empty string
- email: user email
- mfa_enabled: boolean
- mfa_key: only useful when user enables MFA. In this case, user needs to enter their OTP token in order to login.
- api_key: if MFA is not enabled, the `api key` is returned right away.

The `api_key` is used in all subsequent requests. It's empty if MFA is enabled. If user hasn't enabled MFA, `mfa_key` is
empty.

Return 403 if user has enabled FIDO. The client can display a message to suggest user to use the `API Key` instead.

#### POST /api/auth/mfa

Input:

- mfa_token: OTP token that user enters
- mfa_key: MFA key obtained in previous auth request, e.g. /api/auth/login
- device: the device name, used to create an ApiKey associated with this device

Output:

- name: user name, could be an empty string
- api_key: if MFA is not enabled, the `api key` is returned right away.
- email: user email

The `api_key` is used in all subsequent requests. It's empty if MFA is enabled. If user hasn't enabled MFA, `mfa_key` is
empty.

#### POST /api/auth/facebook

Input:

- facebook_token: Facebook access token
- device: device name. Used to create the API Key. Should be humanly readable so user can manage later on the "API Key"
  page.

Output: Same output as for `/api/auth/login` endpoint

#### POST /api/auth/google

Input:

- google_token: Google access token
- device: device name. Used to create the API Key. Should be humanly readable so user can manage later on the "API Key"
  page.

Output: Same output as for `/api/auth/login` endpoint

#### POST /api/auth/register

Input:

- email
- password

Output: 200 means user is going to receive an email that contains an *activation code*. User needs to enter this code to
confirm their account -> next endpoint.

#### POST /api/auth/activate

Input:

- email
- code: the activation code

Output:

- 200: account is activated. User can login now
- 400: wrong email, code
- 410: wrong code too many times. User needs to ask for an reactivation -> next endpoint

#### POST /api/auth/reactivate

Input:

- email

Output:

- 200: user is going to receive an email that contains the activation code.

#### POST /api/auth/forgot_password

Input:

- email

Output: always return 200, even if email doesn't exist. User need to enter correctly their email.

#### GET /api/user_info

Given the API Key, return user name and whether user is premium. This endpoint could be used to validate the api key.

Input:

- `Authentication` header that contains the api key

Output: if api key is correct, return a json with user name and whether user is premium, for example:

```json
{
  "name": "John Wick",
  "is_premium": false,
  "email": "john@wick.com",
  "in_trial": true,
  "profile_picture_url": "https://profile.png",
  "max_alias_free_plan": 5,
}
```

If api key is incorrect, return 401.

#### PATCH /api/user_info

Update user info

Input:

- profile_picture: the profile picture in base64. Setting to `null` remove the current profile picture.
- name

Output: same as GET /api/user_info

#### PATCH /api/sudo

Enable sudo mode

Input:

- `Authentication` header that contains the api key
- password: User password to validate the user presence and enter sudo mode

```json
{
  "password": "yourpassword"
}
```

Output:

- 200 with ```{"ok": true}``` if sudo mode has been enabled.
- 403 with ```{"error": "Some error"}``` if there is an error.

#### DELETE /api/user

Delete the current user. It requires sudo mode.

Input:

- `Authentication` header that contains the api key

Output:

- 200 with ```{"ok": true}``` if account is scheduled to be deleted.
- 440 with ```{"error": "Need sudo"}``` if sudo mode is not enabled.
- 403 with ```{"error": "Some error"}``` if there is an error.


#### GET /api/user/cookie_token

Get a one time use cookie to exchange it for a valid cookie in the web app

Input:

- `Authentication` header that contains the api key

Output:

- 200 with ```{"token": "token value"}```
- 403 with ```{"error": "Some error"}``` if there is an error.

#### POST /api/api_key

Create a new API Key

Input:

- `Authentication` header that contains the api key
- Or the correct cookie is set, i.e. user is already logged in on the web
- device: device's name

Output

- 401 if user is not authenticated
- 201 with the `api_key`

```json
{
  "api_key": "long string"
}
```

#### GET /api/logout

Log user out

Input:

- `Authentication` header that contains the api key
- Or the correct cookie is set, i.e. user is already logged in on the web

Output:

- 401 if user is not authenticated
- 200 if success

### Alias endpoints

#### GET /api/v5/alias/options

User alias info and suggestion. Used by the first extension screen when user opens the extension.

Input:

- `Authentication` header that contains the api key
- (Optional but recommended) `hostname` passed in query string.

Output: a json with the following field:

- can_create: boolean. Whether user can create new alias
- suffixes: list of alias suffix that user can use.
  Each item is a dictionary with `suffix`, `signed-suffix`, `is_custom`, `is_premium` as keys.
  The `signed-suffix` is necessary to avoid request tampering.
- prefix_suggestion: string. Suggestion for the `alias prefix`. Usually this is the website name extracted
  from `hostname`. If no `hostname`, then the `prefix_suggestion` is empty.
- recommendation: optional field, dictionary. If an alias is already used for this website, the recommendation will be
  returned. There are 2 subfields in `recommendation`: `alias` which is the recommended alias and `hostname` is the
  website on which this alias is used before.

For ex:

```json
{
  "can_create": true,
  "prefix_suggestion": "test",
  "suffixes": [
    {
      "signed_suffix": ".cat@d1.test.X6_7OQ.0e9NbZHE_bQvuAapT6NdBml9m6Q",
      "suffix": ".cat@d1.test",
      "is_custom": true,
      "is_premium": false
    },
    {
      "signed_suffix": ".chat@d2.test.X6_7OQ.TTgCrfqPj7UmlY723YsDTHhkess",
      "suffix": ".chat@d2.test",
      "is_custom": false,
      "is_premium": false
    },
    {
      "signed_suffix": ".yeah@sl.local.X6_7OQ.i8XL4xsMsn7dxDEWU8eF-Zap0qo",
      "suffix": ".yeah@sl.local",
      "is_custom": true,
      "is_premium": false
    }
  ]
}
```

#### POST /api/v3/alias/custom/new

Create a new custom alias.

Input:

- `Authentication` header that contains the api key
- (Optional but recommended) `hostname` passed in query string
- Request Message Body in json (`Content-Type` is `application/json`)
    - alias_prefix: string. The first part of the alias that user can choose.
    - signed_suffix: should be one of the suffixes returned in the `GET /api/v4/alias/options` endpoint.
    - mailbox_ids: list of mailbox_id that "owns" this alias
    - (Optional) note: alias note
    - (Optional) name: alias name

Output:
If success, 201 with the new alias info. Use the same format as in GET /api/aliases/:alias_id

#### POST /api/alias/random/new

Create a new random alias.

Input:

- `Authentication` header that contains the api key
- (Optional but recommended) `hostname` passed in query string
- (Optional) mode: either `uuid` or `word`. By default, use the user setting when creating new random alias.
- Request Message Body in json (`Content-Type` is `application/json`)
    - (Optional) note: alias note

Output:
If success, 201 with the new alias info. Use the same format as in GET /api/aliases/:alias_id

#### GET /api/v2/aliases

Get user aliases.

Input:

- `Authentication` header that contains the api key
- `page_id` in query. Used for the pagination. The endpoint returns maximum 20 aliases for each page. `page_id` starts
  at 0.
- (Optional) `pinned` in query. If set, only pinned aliases are returned.
- (Optional) `disabled` in query. If set, only disabled aliases are returned.
- (Optional) `enabled` in query. If set, only enabled aliases are returned.
  Please note `pinned`, `disabled`, `enabled` are exclusive, i.e. only one can be present.
- (Optional) query: included in request body. Some frameworks might prevent GET request having a non-empty body, in this
  case this endpoint also supports POST.

Output:
If success, 200 with the list of aliases. Each alias has the following fields:

- id
- email
- name
- enabled
- creation_timestamp
- note
- nb_block
- nb_forward
- nb_reply
- support_pgp: whether an alias can support PGP, i.e. when one of alias's mailboxes supports PGP.
- disable_pgp: whether the PGP is disabled on this alias. This field should only be used when `support_pgp` is true. By
  setting `disable_pgp=true`, a user can explicitly disable PGP on an alias even its mailboxes support PGP.
- mailbox: obsolete, should use `mailboxes` instead.
    - id
    - email
- mailboxes: list of mailbox, contains at least 1 mailbox.
    - id
    - email
- (nullable) latest_activity:
    - action: forward|reply|block|bounced
    - timestamp
    - contact:
        - email
        - name
        - reverse_alias
- pinned: whether an alias is pinned

Here's an example:

```json
{
  "aliases": [
    {
      "creation_date": "2020-04-06 17:57:14+00:00",
      "creation_timestamp": 1586195834,
      "email": "prefix1.cat@sl.local",
      "name": "A Name",
      "enabled": true,
      "id": 3,
      "mailbox": {
        "email": "a@b.c",
        "id": 1
      },
      "mailboxes": [
        {
          "email": "m1@cd.ef",
          "id": 2
        },
        {
          "email": "john@wick.com",
          "id": 1
        }
      ],
      "latest_activity": {
        "action": "forward",
        "contact": {
          "email": "c1@example.com",
          "name": null,
          "reverse_alias": "\"c1 at example.com\" <re1@SL>"
        },
        "timestamp": 1586195834
      },
      "nb_block": 0,
      "nb_forward": 1,
      "nb_reply": 0,
      "note": null,
      "pinned": true
    }
  ]
}
```

#### GET /api/aliases/:alias_id

Get alias info

Input:

- `Authentication` header that contains the api key
- `alias_id` in url

Output:
Alias info, use the same format as in /api/v2/aliases. For example:

```json
{
  "creation_date": "2020-04-06 17:57:14+00:00",
  "creation_timestamp": 1586195834,
  "email": "prefix1.cat@sl.local",
  "name": "A Name",
  "enabled": true,
  "id": 3,
  "mailbox": {
    "email": "a@b.c",
    "id": 1
  },
  "mailboxes": [
    {
      "email": "m1@cd.ef",
      "id": 2
    },
    {
      "email": "john@wick.com",
      "id": 1
    }
  ],
  "latest_activity": {
    "action": "forward",
    "contact": {
      "email": "c1@example.com",
      "name": null,
      "reverse_alias": "\"c1 at example.com\" <re1@SL>"
    },
    "timestamp": 1586195834
  },
  "nb_block": 0,
  "nb_forward": 1,
  "nb_reply": 0,
  "note": null,
  "pinned": true
}
```

#### DELETE /api/aliases/:alias_id

Delete an alias

Input:

- `Authentication` header that contains the api key
- `alias_id` in url.

Output:
If success, 200.

```json
{
  "deleted": true
}
```

#### POST /api/aliases/:alias_id/toggle

Enable/disable alias

Input:

- `Authentication` header that contains the api key
- `alias_id` in url.

Output:
If success, 200 along with the new alias status:

```json
{
  "enabled": false
}
```

#### GET /api/aliases/:alias_id/activities

Get activities for a given alias.

Input:

- `Authentication` header that contains the api key
- `alias_id`: the alias id, passed in url.
- `page_id` used in request query (`?page_id=0`). The endpoint returns maximum 20 aliases for each page. `page_id`
  starts at 0.

Output:
If success, 200 with the list of activities, for example:

```json
{
  "activities": [
    {
      "action": "reply",
      "from": "yes_meo_chat@sl.local",
      "timestamp": 1580903760,
      "to": "marketing@example.com",
      "reverse_alias": "\"marketing at example.com\" <reply@a.b>",
      "reverse_alias_address": "reply@a.b"
    }
  ]
}
```

#### PATCH /api/aliases/:alias_id

Update alias info.

Input:

- `Authentication` header that contains the api key
- `alias_id` in url.
- (optional) `note` in request body
- (optional) `mailbox_id` in request body
- (optional) `name` in request body
- (optional) `mailbox_ids` in request body: array of mailbox_id
- (optional) `disable_pgp` in request body: boolean
- (optional) `pinned` in request body: boolean

Output:
If success, return 200

#### GET /api/aliases/:alias_id/contacts

Get contacts for a given alias.

Input:

- `Authentication` header that contains the api key
- `alias_id`: the alias id, passed in url.
- `page_id` used in request query (`?page_id=0`). The endpoint returns maximum 20 contacts for each page. `page_id`
  starts at 0.

Output:
If success, 200 with the list of contacts, for example:

```json
{
  "contacts": [
    {
      "id": 1,
      "contact": "marketing@example.com",
      "creation_date": "2020-02-21 11:35:00+00:00",
      "creation_timestamp": 1582284900,
      "last_email_sent_date": null,
      "last_email_sent_timestamp": null,
      "reverse_alias": "marketing at example.com <reply+bzvpazcdedcgcpztehxzgjgzmxskqa@sl.co>",
      "block_forward": false
    },
    {
      "id": 2,
      "contact": "newsletter@example.com",
      "creation_date": "2020-02-21 11:35:00+00:00",
      "creation_timestamp": 1582284900,
      "last_email_sent_date": "2020-02-21 11:35:00+00:00",
      "last_email_sent_timestamp": 1582284900,
      "reverse_alias": "newsletter at example.com <reply+bzvpazcdedcgcpztehxzgjgzmxskqa@sl.co>",
      "reverse_alias_address": "reply+bzvpazcdedcgcpztehxzgjgzmxskqa@sl.co",
      "block_forward": true
    }
  ]
}
```

Please note that last_email_sent_timestamp and last_email_sent_date can be null.

#### POST /api/aliases/:alias_id/contacts

Create a new contact for an alias.

Input:

- `Authentication` header that contains the api key
- `alias_id` in url.
- `contact` in request body

Output:
If success, return 201.

Return 200 and `existed=true` if contact is already added.

```json
{
  "id": 1,
  "contact": "First Last <first@example.com>",
  "creation_date": "2020-03-14 11:52:41+00:00",
  "creation_timestamp": 1584186761,
  "last_email_sent_date": null,
  "last_email_sent_timestamp": null,
  "reverse_alias": "First Last first@example.com <ra+qytyzjhrumrreuszrbjxqjlkh@sl.local>",
  "reverse_alias_address": "reply+bzvpazcdedcgcpztehxzgjgzmxskqa@sl.co",
  "existed": false
}
```

It can return 403 with an error if the user cannot create reverse alias.

``json
{
  "error": "Please upgrade to create a reverse-alias"
}
```

### Mailbox endpoints

#### GET /api/v2/mailboxes

Get user's mailboxes, including unverified ones.

Input:

- `Authentication` header that contains the api key

Output:
List of mailboxes. Each mailbox has id, email, default, creation_timestamp field

```json
{
  "mailboxes": [
    {
      "email": "a@b.c",
      "id": 1,
      "default": true,
      "creation_timestamp": 1590918512,
      "nb_alias": 10,
      "verified": true
    },
    {
      "email": "m1@example.com",
      "id": 2,
      "default": false,
      "creation_timestamp": 1590918512,
      "nb_alias": 0,
      "verified": false
    }
  ]
}
```

## Mailbox endpoints
#### POST /api/mailboxes

Create a new mailbox

Input:

- `Authentication` header that contains the api key
- email: the new mailbox address

Output:

- 201 along with the following response if new mailbox is created successfully. User is going to receive a verification
  email.
    - id: integer
    - email: the mailbox email address
    - verified: boolean.
    - default: whether is the default mailbox. User cannot delete the default mailbox
- 400 with error message otherwise. The error message can be displayed to user.

#### DELETE /api/mailboxes/:mailbox_id

Delete a mailbox. User cannot delete the default mailbox

Input:

- `Authentication` header that contains the api key
- `mailbox_id`: in url

Output:

- 200 if deleted successfully
- 400 if error

#### PUT /api/mailboxes/:mailbox_id

Update a mailbox.

Input:

- `Authentication` header that contains the api key
- `mailbox_id`: in url
- (optional) `default`: boolean. Set a mailbox as default mailbox.
- (optional) `email`: email address. Change a mailbox email address.
- (optional) `cancel_email_change`: boolean. Cancel mailbox email change.

Output:

- 200 if updated successfully
- 400 if error

### Custom domain endpoints

#### GET /api/custom_domains

Return user's custom domains

Input:

- `Authentication` header that contains the api key

Output:
List of custom domains.

```json
[
  {
    "catch_all": false,
    "creation_date": "2021-03-10 21:36:08+00:00",
    "creation_timestamp": 1615412168,
    "domain_name": "test1.org",
    "id": 1,
    "is_verified": true,
    "mailboxes": [
      {
        "email": "a@b.c",
        "id": 1
      }
    ],
    "name": null,
    "nb_alias": 0,
    "random_prefix_generation": false
  },
  {
    "catch_all": false,
    "creation_date": "2021-03-10 21:36:08+00:00",
    "creation_timestamp": 1615412168,
    "domain_name": "test2.org",
    "id": 2,
    "is_verified": false,
    "mailboxes": [
      {
        "email": "a@b.c",
        "id": 1
      }
    ],
    "name": null,
    "nb_alias": 0,
    "random_prefix_generation": false
  }
]
```

#### PATCH /api/custom_domains/:custom_domain_id

Update custom domain's information

Input:

- `Authentication` header that contains the api key
- `custom_domain_id` in url.
- (optional) `catch_all`: boolean, in request body
- (optional) `random_prefix_generation`: boolean, in request body
- (optional) `name`: text, in request body
- (optional) `mailbox_ids`: array of mailbox id, in request body

Output:
If success, return 200 along with updated custom domain

#### GET /api/custom_domains/:custom_domain_id/trash

Get deleted alias for a custom domain

Input:

- `Authentication` header that contains the api key

Output:
List of deleted alias.

```json
{
  "aliases": [
    {
      "alias": "first@test1.org",
      "deletion_timestamp": 1605464595
    }
  ]
}
```

### Contact endpoints

#### DELETE /api/contacts/:contact_id

Delete a contact

Input:

- `Authentication` header that contains the api key
- `contact_id` in url.

Output:
If success, 200.

```json
{
  "deleted": true
}
```

#### POST /api/contacts/:contact_id/toggle

Block/unblock contact

Input:

- `Authentication` header that contains the api key
- `contact_id` in url.

Output:
If success, 200 along with the new alias status:

```json
{
  "block_forward": false
}
```

### Notification endpoints

#### GET /api/notifications

Get notifications

Input:

- `Authentication` in header: the api key
- page in url: the page number, starts at 0

Output:

- more: whether there's more notifications
- notifications: list of notification, each notification has:
    - id
    - message: the message in html
    - title: the message title
    - read: whether the user has read the notification
    - created_at: when the notification is created

For example

```json
{
  "more": false,
  "notifications": [
    {
      "created_at": "2 minutes ago",
      "id": 1,
      "message": "Hey!",
      "read": false
    }
  ]
}
```

#### POST /api/notifications/:notification_id

Mark a notification as read

Input:

- `Authentication` in header: the api key
- notification_id in url: the page number, starts at 0

Output:
200 if success

### Settings endpoints

#### GET /api/setting

Return user setting.

```json
{
  "alias_generator": "word",
  "notification": true,
  "random_alias_default_domain": "sl.local",
  "sender_format": "AT",
  "random_alias_suffix": "random_string"
}
```

#### PATCH /api/setting

Update user setting. All input fields are optional.

Input:

- alias_generator (string): `uuid` or `word`
- notification (boolean): `true` or `false`
- random_alias_default_domain (string): one of the domains returned by `GET /api/setting/domains`
- sender_format (string): possible values are `AT`, `A`, `NAME_ONLY`, `AT_ONLY`, `NO_NAME`
- random_alias_suffix (string): possible values are `word`, `random_string`

Output: same as `GET /api/setting`

#### GET /api/v2/setting/domains

Return domains that user can use to create random alias

`is_custom` is true if this is a user's domain, otherwise false.

```json
[
  {
    "domain": "d1.test",
    "is_custom": false
  },
  {
    "domain": "d2.test",
    "is_custom": false
  },
  {
    "domain": "sl.local",
    "is_custom": false
  },
  {
    "domain": "ab.cd",
    "is_custom": true
  }
]
```

### Import and export endpoints

#### GET /api/export/data

Export user data

Input:

- `Authentication` in header: the api key

Output:
Alias, custom domain and app info

#### GET /api/export/aliases

Export user aliases in an importable CSV format

Input:

- `Authentication` in header: the api key

Output:
A CSV file with alias information that can be imported in the settings screen

### Misc endpoints

#### POST /api/apple/process_payment

Process payment receipt

Input:

- `Authentication` in header: the api key
- `receipt_data` in body: the receipt_data base64Encoded returned by StoreKit, i.e. `rawReceiptData.base64EncodedString`
- (optional) `is_macapp` in body: if this field is present, the request is sent from the MacApp (Safari Extension) and
  not iOS app.

Output:
200 if user is upgraded successfully 4** if any error.

### Phone endpoints

#### GET /api/phone/reservations/:reservation_id

Get messages received during a reservation.

Input:

- `Authentication` in header: the api key
- `reservation_id`

Output:
List of messages for this reservation and whether the reservation is ended.

```json
{
  "ended": false,
  "messages": [
    {
      "body": "body",
      "created_at": "just now",
      "from_number": "from_number",
      "id": 7
    }
  ]
}
```
